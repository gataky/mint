package http

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func newTestAdmin(t *testing.T, checks ...Check) (http.Handler, *Health) {
	t.Helper()

	health := NewHealth()
	for _, check := range checks {
		health.Register(check)
	}
	return NewAdmin(health, nil), health
}

func TestLivenessIgnoresDependencies(t *testing.T) {
	// A liveness probe that checks a dependency restarts the service when the
	// dependency is the thing that is broken. It must pass regardless.
	handler, _ := newTestAdmin(t, Check{
		Name:     "always-fails",
		Required: true,
		Probe:    func(context.Context) error { return errors.New("down") },
	})

	rec := do(t, handler, http.MethodGet, "/healthz", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /healthz = %d, want 200 even with a failing required check", rec.Code)
	}
	if got := decode[map[string]any](t, rec)["status"]; got != "ok" {
		t.Errorf(`body["status"] = %v, want "ok"`, got)
	}
}

func TestReadinessWithNoChecksIsReady(t *testing.T) {
	handler, _ := newTestAdmin(t)

	rec := do(t, handler, http.MethodGet, "/readyz", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /readyz = %d, want 200", rec.Code)
	}
}

func TestReadinessFailsOnlyOnRequiredChecks(t *testing.T) {
	tests := []struct {
		name       string
		required   bool
		wantStatus int
		wantBody   string
	}{
		{
			name:       "a failing optional check is reported but stays ready",
			required:   false,
			wantStatus: http.StatusOK,
			wantBody:   "ok",
		},
		{
			name:       "a failing required check takes the service out of rotation",
			required:   true,
			wantStatus: http.StatusServiceUnavailable,
			wantBody:   "fail",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			handler, _ := newTestAdmin(t, Check{
				Name:     "database",
				Required: tt.required,
				Probe:    func(context.Context) error { return errors.New("connection refused") },
			})

			rec := do(t, handler, http.MethodGet, "/readyz", "")
			if rec.Code != tt.wantStatus {
				t.Fatalf("GET /readyz = %d, want %d: %s", rec.Code, tt.wantStatus, rec.Body)
			}

			body := decode[map[string]any](t, rec)
			if body["status"] != tt.wantBody {
				t.Errorf(`body["status"] = %v, want %q`, body["status"], tt.wantBody)
			}

			// Whatever the outcome, the body lists every check — that is what
			// makes the endpoint useful for diagnosis rather than just routing.
			checks, ok := body["checks"].([]any)
			if !ok || len(checks) != 1 {
				t.Fatalf(`body["checks"] = %v, want one entry`, body["checks"])
			}
			reported := checks[0].(map[string]any)
			if reported["name"] != "database" {
				t.Errorf(`check name = %v, want "database"`, reported["name"])
			}
			if reported["error"] != "connection refused" {
				t.Errorf(`check error = %v, want the probe's message`, reported["error"])
			}
		})
	}
}

func TestReadinessReportsEveryCheck(t *testing.T) {
	handler, _ := newTestAdmin(t,
		Check{Name: "database", Required: true, Probe: func(context.Context) error { return nil }},
		Check{Name: "cache", Required: false, Probe: func(context.Context) error { return errors.New("down") }},
	)

	rec := do(t, handler, http.MethodGet, "/readyz", "")

	checks, ok := decode[map[string]any](t, rec)["checks"].([]any)
	if !ok || len(checks) != 2 {
		t.Fatalf("readiness body listed %v, want two checks", checks)
	}

	byName := map[string]string{}
	for _, entry := range checks {
		check := entry.(map[string]any)
		byName[check["name"].(string)] = check["status"].(string)
	}
	if byName["database"] != "ok" {
		t.Errorf("database check = %q, want ok", byName["database"])
	}
	if byName["cache"] != "fail" {
		t.Errorf("cache check = %q, want fail", byName["cache"])
	}
}

func TestReadinessTimesOutASlowCheck(t *testing.T) {
	// A check with no timeout of its own would hang the whole probe.
	handler, _ := newTestAdmin(t, Check{
		Name:     "slow",
		Required: true,
		Timeout:  20 * time.Millisecond,
		Probe: func(ctx context.Context) error {
			<-ctx.Done()
			return ctx.Err()
		},
	})

	rec := do(t, handler, http.MethodGet, "/readyz", "")
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("GET /readyz with a timing-out required check = %d, want 503", rec.Code)
	}
}

func TestDrainMakesTheServiceUnready(t *testing.T) {
	handler, health := newTestAdmin(t)

	health.Drain()

	rec := do(t, handler, http.MethodGet, "/readyz", "")
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("GET /readyz while draining = %d, want 503", rec.Code)
	}
	// "draining" is distinguishable from "fail" on purpose: mid-drain the
	// service is healthy, it is just leaving rotation deliberately.
	if got := decode[map[string]any](t, rec)["status"]; got != "draining" {
		t.Errorf(`body["status"] = %v, want "draining"`, got)
	}
}

func TestLivenessStaysUpWhileDraining(t *testing.T) {
	handler, health := newTestAdmin(t)

	health.Drain()

	// Failing liveness during a drain gets the process killed instead of
	// allowed to finish its in-flight requests.
	rec := do(t, handler, http.MethodGet, "/healthz", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /healthz while draining = %d, want 200", rec.Code)
	}
}

func TestAdminRejectsUnknownPathsWithProblemJSON(t *testing.T) {
	handler, _ := newTestAdmin(t)

	rec := do(t, handler, http.MethodGet, "/not-a-thing", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("GET /not-a-thing = %d, want 404", rec.Code)
	}
	if got := rec.Header().Get("Content-Type"); got != ProblemContentType {
		t.Errorf("Content-Type = %q, want %q", got, ProblemContentType)
	}
}

func TestChainAppliesOutermostFirst(t *testing.T) {
	var order []string

	record := func(name string) Middleware {
		return func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				order = append(order, name)
				next.ServeHTTP(w, r)
			})
		}
	}

	handler := Chain(
		http.HandlerFunc(func(http.ResponseWriter, *http.Request) { order = append(order, "handler") }),
		record("first"), record("second"), record("third"),
	)

	req := httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/", nil)
	handler.ServeHTTP(httptest.NewRecorder(), req)

	want := []string{"first", "second", "third", "handler"}
	for i, name := range want {
		if i >= len(order) || order[i] != name {
			t.Fatalf("middleware ran in order %v, want %v", order, want)
		}
	}
}
