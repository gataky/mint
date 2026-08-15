package http

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"

	"github.com/jeffmgreg/widget-svc/internal/config"
	"github.com/jeffmgreg/widget-svc/internal/logging"
)

// newTracedAPI builds the API with tracing wired as the composition root does,
// recording spans in memory instead of exporting them.
func newTracedAPI(t *testing.T) (http.Handler, *tracetest.SpanRecorder, *bytes.Buffer) {
	t.Helper()

	recorder := tracetest.NewSpanRecorder()
	provider := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(recorder))
	t.Cleanup(func() {
		// Not t.Context(): it is already cancelled by the time cleanup runs.
		if err := provider.Shutdown(context.Background()); err != nil {
			t.Errorf("provider shutdown: %v", err)
		}
	})

	previous := otel.GetTracerProvider()
	otel.SetTracerProvider(provider)
	otel.SetTextMapPropagator(propagation.TraceContext{})
	t.Cleanup(func() { otel.SetTracerProvider(previous) })

	logs := &bytes.Buffer{}
	logger := logging.New(logging.Options{
		Level: "debug", Format: "json",
		Service: "widget-svc", ServiceVersion: "0.1.0", Env: "local",
		Output: logs,
	})

	cfg := config.Defaults()
	widgets, orders := newTestServices(t)
	mux := NewAPI(cfg, widgets, orders, logger)
	resolve := MuxResolver(mux)

	handler := Chain(mux,
		Recovery(logger),
		RequestContext(),
		Tracing(cfg.Service.Name, resolve),
		Logging(logger, resolve),
		Timeout(cfg.Server.RequestTimeout),
	)
	return handler, recorder, logs
}

func TestLogLinesCarryTheTraceAndSpanID(t *testing.T) {
	handler, recorder, logs := newTracedAPI(t)

	do(t, handler, http.MethodGet, "/widgets", "")

	line := lastLogLine(t, logs)
	traceID, ok := line[logging.KeyTraceID].(string)
	if !ok || traceID == "" {
		t.Fatalf("access log has no %s: %v", logging.KeyTraceID, line)
	}
	if _, ok := line[logging.KeySpanID].(string); !ok {
		t.Errorf("access log has no %s: %v", logging.KeySpanID, line)
	}

	// The ID on the log line must be the ID of the span that was actually
	// recorded, or the error-to-trace path leads nowhere.
	spans := recorder.Ended()
	if len(spans) != 1 {
		t.Fatalf("recorded %d spans, want 1", len(spans))
	}
	if got := spans[0].SpanContext().TraceID().String(); got != traceID {
		t.Errorf("log trace_id = %q, recorded span trace_id = %q", traceID, got)
	}
}

func TestTraceFieldsAreOmittedWithoutASpan(t *testing.T) {
	// An empty trace_id is worse than an absent one: it looks like a trace that
	// exists and cannot be found.
	logs := &bytes.Buffer{}
	logger := logging.New(logging.Options{Level: "debug", Format: "json", Output: logs})

	logger.InfoContext(t.Context(), "no span here")

	line := lastLogLine(t, logs)
	if _, found := line[logging.KeyTraceID]; found {
		t.Errorf("%s present with no active span: %v", logging.KeyTraceID, line)
	}
	if _, found := line[logging.KeySpanID]; found {
		t.Errorf("%s present with no active span: %v", logging.KeySpanID, line)
	}
}

func TestSpanIsNamedForTheRouteTemplate(t *testing.T) {
	handler, recorder, _ := newTracedAPI(t)

	do(t, handler, http.MethodGet, "/widgets/abc123", "")

	spans := recorder.Ended()
	if len(spans) != 1 {
		t.Fatalf("recorded %d spans, want 1", len(spans))
	}
	// Not "/widgets/abc123": every widget ID would be its own operation name.
	if got := spans[0].Name(); got != "GET /widgets/{id}" {
		t.Errorf("span name = %q, want %q", got, "GET /widgets/{id}")
	}
}

func TestInboundTraceContextIsContinued(t *testing.T) {
	handler, recorder, _ := newTracedAPI(t)

	// A caller's trace must continue here rather than a new one starting, or a
	// distributed trace breaks at every service boundary.
	const traceID = "4bf92f3577b34da6a3ce929d0e0e4736"
	const parentSpanID = "00f067aa0ba902b7"

	req := httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/widgets", nil)
	req.Header.Set("traceparent", "00-"+traceID+"-"+parentSpanID+"-01")
	handler.ServeHTTP(httptest.NewRecorder(), req)

	spans := recorder.Ended()
	if len(spans) != 1 {
		t.Fatalf("recorded %d spans, want 1", len(spans))
	}
	if got := spans[0].SpanContext().TraceID().String(); got != traceID {
		t.Errorf("trace ID = %q, want the inbound %q", got, traceID)
	}
	if got := spans[0].Parent().SpanID().String(); got != parentSpanID {
		t.Errorf("parent span ID = %q, want the inbound %q", got, parentSpanID)
	}
}

func TestHealthAndScrapePathsAreNotTraced(t *testing.T) {
	recorder := tracetest.NewSpanRecorder()
	provider := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(recorder))
	t.Cleanup(func() { _ = provider.Shutdown(context.Background()) })

	previous := otel.GetTracerProvider()
	otel.SetTracerProvider(provider)
	t.Cleanup(func() { otel.SetTracerProvider(previous) })

	logger := logging.New(logging.Options{Level: "error", Format: "json", Output: &bytes.Buffer{}})
	admin := NewAdmin(NewHealth(), nil)

	handler := Chain(admin,
		Recovery(logger),
		RequestContext(),
		Tracing("widget-svc", MuxResolver(admin)),
	)

	// A probe every second and a scrape every fifteen would be most of the
	// spans, and none of them describe anything anyone traces.
	for _, path := range []string{"/healthz", "/readyz"} {
		do(t, handler, http.MethodGet, path, "")
	}

	if spans := recorder.Ended(); len(spans) != 0 {
		names := make([]string, len(spans))
		for i, span := range spans {
			names[i] = span.Name()
		}
		t.Errorf("recorded spans for admin paths: %s", strings.Join(names, ", "))
	}
}
