package http

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"{@ module_path @}/internal/config"
	"{@ module_path @}/internal/logging"
)

// The shared test helpers live here rather than beside the tests of any one
// resource, so that removing a resource never takes them with it.

// newTestAPI builds the API exactly as the composition root does, so the tests
// exercise the real middleware chain rather than a bare handler.
func newTestAPI(t *testing.T) (http.Handler, *bytes.Buffer) {
	t.Helper()

	logs := &bytes.Buffer{}
	logger := logging.New(logging.Options{
		Level:          "debug",
		Format:         "json",
		Service:        "{@ service_name @}",
		ServiceVersion: "0.1.0",
		Env:            "local",
		Output:         logs,
	})

	cfg := config.Defaults()
{% if include_examples %}	widgets, orders := newTestServices(t)
	mux := NewAPI(cfg, widgets, orders, logger)
{% else %}	mux := NewAPI(cfg, logger)
{% endif %}	handler := Chain(
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
