package http

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/jeffmgreg/widget-svc/internal/config"
	"github.com/jeffmgreg/widget-svc/internal/domain"
	"github.com/jeffmgreg/widget-svc/internal/logging"
)

// newTestAPI builds the API exactly as the composition root does, so the tests
// exercise the real middleware chain rather than a bare handler.
func newTestAPI(t *testing.T) (http.Handler, *bytes.Buffer) {
	t.Helper()

	logs := &bytes.Buffer{}
	logger := logging.New(logging.Options{
		Level:          "debug",
		Format:         "json",
		Service:        "widget-svc",
		ServiceVersion: "0.1.0",
		Env:            "local",
		Output:         logs,
	})

	cfg := config.Defaults()
	widgets, orders := newTestServices(t)
	mux := NewAPI(cfg, widgets, orders, logger)
	handler := Chain(
		mux,
		Recovery(logger),
		RequestContext(),
		Logging(logger, MuxResolver(mux)),
		Timeout(cfg.Server.RequestTimeout),
	)
	return handler, logs
}

func do(t *testing.T, handler http.Handler, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()

	var reader io.Reader
	if body != "" {
		reader = strings.NewReader(body)
	}
	req := httptest.NewRequestWithContext(t.Context(), method, path, reader)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

func decode[T any](t *testing.T, rec *httptest.ResponseRecorder) T {
	t.Helper()
	var out T
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("response body is not valid JSON (%v): %s", err, rec.Body.String())
	}
	return out
}

func TestCreateAndFetchWidget(t *testing.T) {
	handler, _ := newTestAPI(t)

	created := do(t, handler, http.MethodPost, "/widgets", `{"name":"sprocket","color":"red"}`)
	if created.Code != http.StatusCreated {
		t.Fatalf("POST /widgets = %d, want %d: %s", created.Code, http.StatusCreated, created.Body)
	}

	widget := decode[domain.Widget](t, created)
	if widget.ID == "" {
		t.Fatal("POST /widgets returned a widget with no ID")
	}
	if widget.Name != "sprocket" || widget.Color != "red" {
		t.Errorf("POST /widgets returned %+v, want name=sprocket color=red", widget)
	}

	fetched := do(t, handler, http.MethodGet, "/widgets/"+widget.ID, "")
	if fetched.Code != http.StatusOK {
		t.Fatalf("GET /widgets/{id} = %d, want %d: %s", fetched.Code, http.StatusOK, fetched.Body)
	}
	if got := decode[domain.Widget](t, fetched); got.ID != widget.ID {
		t.Errorf("GET /widgets/{id} returned ID %q, want %q", got.ID, widget.ID)
	}
}

func TestListWidgetsReturnsEmptyArray(t *testing.T) {
	handler, _ := newTestAPI(t)

	rec := do(t, handler, http.MethodGet, "/widgets", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /widgets = %d, want %d", rec.Code, http.StatusOK)
	}
	// null would break a client that iterates the result without a nil check.
	if got := strings.TrimSpace(rec.Body.String()); got != "[]" {
		t.Errorf("GET /widgets on an empty store = %s, want []", got)
	}
}

func TestErrorResponsesUseProblemJSON(t *testing.T) {
	tests := []struct {
		name       string
		method     string
		path       string
		body       string
		wantStatus int
		wantTitle  string
	}{
		{
			name:       "unknown widget is not found",
			method:     http.MethodGet,
			path:       "/widgets/no-such-id",
			wantStatus: http.StatusNotFound,
			wantTitle:  "Not Found",
		},
		{
			name:       "unroutable path is not found",
			method:     http.MethodGet,
			path:       "/nothing-here",
			wantStatus: http.StatusNotFound,
			wantTitle:  "Not Found",
		},
		{
			name:       "shape violation is unprocessable",
			method:     http.MethodPost,
			path:       "/widgets",
			body:       `{"name":"","color":"puce"}`,
			wantStatus: http.StatusUnprocessableEntity,
			wantTitle:  "Unprocessable Entity",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			handler, _ := newTestAPI(t)
			rec := do(t, handler, tt.method, tt.path, tt.body)

			if rec.Code != tt.wantStatus {
				t.Fatalf("%s %s = %d, want %d: %s", tt.method, tt.path, rec.Code, tt.wantStatus, rec.Body)
			}
			if got := rec.Header().Get("Content-Type"); got != ProblemContentType {
				t.Errorf("Content-Type = %q, want %q", got, ProblemContentType)
			}

			problem := decode[map[string]any](t, rec)
			// RFC 9457 requires these; both languages emit all four.
			if problem["type"] != DefaultProblemType {
				t.Errorf(`body["type"] = %v, want %q`, problem["type"], DefaultProblemType)
			}
			if problem["title"] != tt.wantTitle {
				t.Errorf(`body["title"] = %v, want %q`, problem["title"], tt.wantTitle)
			}
			if problem["status"] != float64(tt.wantStatus) {
				t.Errorf(`body["status"] = %v, want %d`, problem["status"], tt.wantStatus)
			}
			if problem["instance"] != tt.path {
				t.Errorf(`body["instance"] = %v, want %q`, problem["instance"], tt.path)
			}
		})
	}
}

func TestDuplicateNameIsAConflict(t *testing.T) {
	handler, _ := newTestAPI(t)
	body := `{"name":"sprocket","color":"red"}`

	if rec := do(t, handler, http.MethodPost, "/widgets", body); rec.Code != http.StatusCreated {
		t.Fatalf("first POST = %d, want %d", rec.Code, http.StatusCreated)
	}

	rec := do(t, handler, http.MethodPost, "/widgets", body)
	if rec.Code != http.StatusConflict {
		t.Fatalf("duplicate POST = %d, want %d: %s", rec.Code, http.StatusConflict, rec.Body)
	}
	if got := decode[map[string]any](t, rec)["title"]; got != "Conflict" {
		t.Errorf(`body["title"] = %v, want "Conflict"`, got)
	}
}

func TestRequestIDIsEchoedAndReused(t *testing.T) {
	handler, _ := newTestAPI(t)

	t.Run("generated when absent", func(t *testing.T) {
		rec := do(t, handler, http.MethodGet, "/widgets", "")
		if rec.Header().Get(RequestIDHeader) == "" {
			t.Errorf("response has no %s header", RequestIDHeader)
		}
	})

	t.Run("reused when supplied", func(t *testing.T) {
		// A caller's ID must survive the hop, or a trace across services breaks.
		req := httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/widgets", nil)
		req.Header.Set(RequestIDHeader, "caller-supplied-id")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)

		if got := rec.Header().Get(RequestIDHeader); got != "caller-supplied-id" {
			t.Errorf("%s = %q, want the inbound %q", RequestIDHeader, got, "caller-supplied-id")
		}
	})
}

func TestAccessLogCarriesTheReservedFields(t *testing.T) {
	handler, logs := newTestAPI(t)
	do(t, handler, http.MethodGet, "/widgets", "")

	line := lastLogLine(t, logs)
	for _, key := range []string{
		logging.KeyTime, logging.KeyLevel, logging.KeyMessage,
		logging.KeyService, logging.KeyServiceVersion, logging.KeyEnv,
		logging.KeyRequestID,
		"method", "route", "path", "status", "duration_ms",
	} {
		if _, ok := line[key]; !ok {
			t.Errorf("access log line has no %q field: %v", key, line)
		}
	}
}

func TestAccessLogRecordsTheRouteTemplateNotThePath(t *testing.T) {
	handler, logs := newTestAPI(t)

	// Logging the concrete path would make every widget ID its own value —
	// unbounded cardinality once this label reaches metrics.
	do(t, handler, http.MethodGet, "/widgets/abc123", "")

	line := lastLogLine(t, logs)
	if got := line["route"]; got != "/widgets/{id}" {
		t.Errorf("access log route = %v, want %q", got, "/widgets/{id}")
	}
	if got := line["path"]; got != "/widgets/abc123" {
		t.Errorf("access log path = %v, want the concrete %q", got, "/widgets/abc123")
	}
}

func TestAccessLogLevelTracksTheStatus(t *testing.T) {
	tests := []struct {
		name      string
		path      string
		wantLevel string
	}{
		{name: "success logs at info", path: "/widgets", wantLevel: "info"},
		{name: "client error logs at warn", path: "/widgets/missing", wantLevel: "warn"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			handler, logs := newTestAPI(t)
			do(t, handler, http.MethodGet, tt.path, "")

			if got := lastLogLine(t, logs)[logging.KeyLevel]; got != tt.wantLevel {
				t.Errorf("access log level = %v, want %q", got, tt.wantLevel)
			}
		})
	}
}

func TestPanicIsRecoveredAsProblemJSON(t *testing.T) {
	logs := &bytes.Buffer{}
	logger := logging.New(logging.Options{Level: "debug", Format: "json", Output: logs})

	exploding := http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		panic("handler exploded")
	})
	handler := Chain(exploding, Recovery(logger), RequestContext(),
		Logging(logger, func(r *http.Request) string { return r.URL.Path }))

	rec := do(t, handler, http.MethodGet, "/boom", "")

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("panicking handler returned %d, want %d", rec.Code, http.StatusInternalServerError)
	}
	if got := rec.Header().Get("Content-Type"); got != ProblemContentType {
		t.Errorf("Content-Type = %q, want %q", got, ProblemContentType)
	}
	// The panic value and stack are logged, never serialized.
	if body := rec.Body.String(); strings.Contains(body, "handler exploded") {
		t.Errorf("panic detail leaked into the response body: %s", body)
	}
	if !strings.Contains(logs.String(), "handler exploded") {
		t.Error("panic detail was not logged")
	}
}

func TestOpenAPIDocumentDescribesEveryOperation(t *testing.T) {
	handler, _ := newTestAPI(t)

	rec := do(t, handler, http.MethodGet, "/openapi.json", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /openapi.json = %d, want 200", rec.Code)
	}

	var doc struct {
		OpenAPI string                                `json:"openapi"`
		Paths   map[string]map[string]json.RawMessage `json:"paths"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &doc); err != nil {
		t.Fatalf("/openapi.json is not valid JSON: %v", err)
	}

	if !strings.HasPrefix(doc.OpenAPI, "3.1") {
		t.Errorf("openapi version = %q, want 3.1.x", doc.OpenAPI)
	}
	for path, methods := range map[string][]string{
		"/widgets":      {"get", "post"},
		"/widgets/{id}": {"get"},
	} {
		for _, method := range methods {
			if _, ok := doc.Paths[path][method]; !ok {
				t.Errorf("/openapi.json does not document %s %s", strings.ToUpper(method), path)
			}
		}
	}
}

func TestResponseBodyHasNoSchemaKey(t *testing.T) {
	handler, _ := newTestAPI(t)

	rec := do(t, handler, http.MethodPost, "/widgets", `{"name":"sprocket","color":"red"}`)

	// huma injects a "$schema" property by default. It is disabled, because the
	// Python service does not emit it and a client must not be able to tell the
	// two apart.
	if _, found := decode[map[string]any](t, rec)["$schema"]; found {
		t.Errorf("response body contains a $schema key: %s", rec.Body)
	}
}

func TestDocsAreServed(t *testing.T) {
	handler, _ := newTestAPI(t)

	rec := do(t, handler, http.MethodGet, "/docs", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /docs = %d, want 200", rec.Code)
	}
	if got := rec.Header().Get("Content-Type"); !strings.HasPrefix(got, "text/html") {
		t.Errorf("GET /docs Content-Type = %q, want text/html", got)
	}
}

// lastLogLine returns the final JSON log line written to buf.
func lastLogLine(t *testing.T, buf *bytes.Buffer) map[string]any {
	t.Helper()

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	last := lines[len(lines)-1]
	if last == "" {
		t.Fatal("no log lines were written")
	}

	var out map[string]any
	if err := json.Unmarshal([]byte(last), &out); err != nil {
		t.Fatalf("log line is not valid JSON (%v): %s", err, last)
	}
	return out
}
