package http

import (
	"context"
	"encoding/json"
	"net/http"
	"sync"
	"sync/atomic"
	"time"
)

// Check is one readiness probe: a dependency the service needs, with its own
// timeout and its own opinion about whether failing it should take the service
// out of rotation.
type Check struct {
	Name     string
	Required bool
	Timeout  time.Duration
	Probe    func(ctx context.Context) error
}

// Health owns the liveness and readiness endpoints.
type Health struct {
	mu       sync.RWMutex
	checks   []Check
	draining atomic.Bool
}

// NewHealth returns a Health with no checks registered. With none, /readyz
// reports ready.
func NewHealth() *Health { return &Health{} }

// Register adds a readiness check. Call it during startup, before the
// listeners come up.
func (h *Health) Register(c Check) {
	if c.Timeout <= 0 {
		c.Timeout = 2 * time.Second
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	h.checks = append(h.checks, c)
}

// Drain marks the service as shutting down. /readyz starts failing
// immediately so a load balancer stops sending new work, while in-flight
// requests finish.
func (h *Health) Drain() { h.draining.Store(true) }

type checkResult struct {
	Name       string `json:"name"`
	Status     string `json:"status"`
	Required   bool   `json:"required"`
	DurationMS int64  `json:"duration_ms"`
	Error      string `json:"error,omitempty"`
}

type healthBody struct {
	Status string        `json:"status"`
	Checks []checkResult `json:"checks"`
}

// NewAdmin builds the admin handler: liveness, readiness, and — once metrics
// land — /metrics. It is served on its own port by default.
func NewAdmin(health *Health) http.Handler {
	mux := http.NewServeMux()

	// Liveness answers one question: is the process running? It touches no
	// dependency, ever. A liveness probe that checks a database restarts the
	// service when the database is the thing that is broken.
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, healthBody{Status: "ok", Checks: []checkResult{}})
	})

	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		body, status := health.ready(r.Context())
		writeJSON(w, status, body)
	})

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeProblem(w, r, http.StatusNotFound, "Not Found", "no route matches "+r.Method+" "+r.URL.Path)
	})

	return mux
}

// ready runs every registered check and reports all of them, whatever the
// outcome. Only a failing *required* check makes the service unready — an
// optional dependency being down is worth surfacing, not worth removing the
// service from rotation for.
func (h *Health) ready(ctx context.Context) (healthBody, int) {
	if h.draining.Load() {
		return healthBody{Status: "draining", Checks: []checkResult{}}, http.StatusServiceUnavailable
	}

	h.mu.RLock()
	checks := make([]Check, len(h.checks))
	copy(checks, h.checks)
	h.mu.RUnlock()

	results := make([]checkResult, len(checks))
	var wg sync.WaitGroup
	for i, check := range checks {
		wg.Add(1)
		go func() {
			defer wg.Done()
			results[i] = run(ctx, check)
		}()
	}
	wg.Wait()

	status := http.StatusOK
	overall := "ok"
	for _, result := range results {
		if result.Status != "ok" && result.Required {
			status = http.StatusServiceUnavailable
			overall = "fail"
		}
	}
	return healthBody{Status: overall, Checks: results}, status
}

func run(ctx context.Context, check Check) checkResult {
	ctx, cancel := context.WithTimeout(ctx, check.Timeout)
	defer cancel()

	start := time.Now()
	err := check.Probe(ctx)
	result := checkResult{
		Name:       check.Name,
		Status:     "ok",
		Required:   check.Required,
		DurationMS: time.Since(start).Milliseconds(),
	}
	if err != nil {
		result.Status = "fail"
		result.Error = err.Error()
	}
	return result
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
