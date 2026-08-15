package observability

import (
	"context"
	"fmt"
	"net/url"
	"strings"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
	"go.opentelemetry.io/otel/trace/noop"

	"github.com/jeffmgreg/widget-svc/internal/config"
)

// Tracing owns the tracer provider and knows how to shut it down.
type Tracing struct {
	provider  *sdktrace.TracerProvider
	Exporting bool
}

// NewTracing builds the tracer provider and installs it globally.
//
// **A real provider is installed even with no collector configured.** The
// exporter is what becomes a no-op, not the tracer: spans are still created, so
// every log line still carries a trace_id and a request can still be followed
// through the logs — while a fresh `make run` emits no connection-refused
// retries. Disabling the tracer instead would silently drop trace_id from the
// logs, which is the thing most worth having locally.
func NewTracing(ctx context.Context, cfg config.Config) (*Tracing, error) {
	if !cfg.Observability.Tracing.Enabled {
		// Explicitly off. No spans at all, so no trace_id anywhere.
		otel.SetTracerProvider(noop.NewTracerProvider())
		installPropagator()
		return &Tracing{}, nil
	}

	exporter, exporting, err := newExporter(ctx, cfg.Observability.Tracing.OTLPEndpoint)
	if err != nil {
		return nil, err
	}

	provider := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		// Mint owns identity. OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES
		// are deliberately not consulted: logs and spans disagreeing about
		// service or env would break the error-to-trace path.
		sdktrace.WithResource(resourceFor(cfg)),
		// ParentBased so an upstream sampling decision is respected; the ratio
		// applies only to traces this service starts.
		sdktrace.WithSampler(sdktrace.ParentBased(
			sdktrace.TraceIDRatioBased(cfg.Observability.Tracing.SampleRatio),
		)),
	)

	otel.SetTracerProvider(provider)
	installPropagator()

	return &Tracing{provider: provider, Exporting: exporting}, nil
}

// installPropagator sets W3C trace context and baggage, so a trace survives the
// hop between services regardless of which language each one is written in.
func installPropagator() {
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))
}

func resourceFor(cfg config.Config) *resource.Resource {
	return resource.NewSchemaless(
		attribute.String("service.name", cfg.Service.Name),
		attribute.String("service.version", cfg.Service.Version),
		attribute.String("service.owner", cfg.Service.Owner),
		attribute.String("deployment.environment.name", cfg.Env),
	)
}

// newExporter returns the span exporter and whether it actually exports.
func newExporter(ctx context.Context, endpoint string) (sdktrace.SpanExporter, bool, error) {
	if strings.TrimSpace(endpoint) == "" {
		return discardExporter{}, false, nil
	}

	parsed, err := url.Parse(endpoint)
	if err != nil {
		return nil, false, fmt.Errorf("parse otlp_endpoint %q: %w", endpoint, err)
	}

	options := []otlptracehttp.Option{otlptracehttp.WithEndpoint(parsed.Host)}
	if parsed.Scheme != "https" {
		options = append(options, otlptracehttp.WithInsecure())
	}
	if path := strings.TrimSuffix(parsed.Path, "/"); path != "" {
		options = append(options, otlptracehttp.WithURLPath(path+"/v1/traces"))
	}

	exporter, err := otlptracehttp.New(ctx, options...)
	if err != nil {
		return nil, false, fmt.Errorf("build otlp exporter: %w", err)
	}
	return exporter, true, nil
}

// Shutdown flushes and stops the tracer provider.
//
// This must run after the drain and before the process exits: the spans for the
// last requests served sit in the batcher's queue, and are silently lost
// otherwise.
func (t *Tracing) Shutdown(ctx context.Context) error {
	if t == nil || t.provider == nil {
		return nil
	}
	return t.provider.Shutdown(ctx)
}

// Tracer returns a tracer for manual instrumentation in the service layer.
func Tracer(name string) trace.Tracer {
	return otel.Tracer(name)
}

// discardExporter accepts spans and drops them. Used when no collector is
// configured, so that spans — and therefore trace IDs on log lines — still
// exist locally without anything trying to reach the network.
type discardExporter struct{}

func (discardExporter) ExportSpans(context.Context, []sdktrace.ReadOnlySpan) error { return nil }
func (discardExporter) Shutdown(context.Context) error                             { return nil }
