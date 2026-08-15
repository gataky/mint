// Package observability owns the metrics registry and, later, the tracer
// provider. Nothing else in the service talks to Prometheus or OpenTelemetry
// directly.
package observability

import (
	"net/http"
	"strconv"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/jeffmgreg/widget-svc/internal/config"
)

// DurationBuckets are OpenTelemetry's advisory buckets for
// http.server.request.duration, declared literally so both services use the
// same boundaries rather than each library's default.
var DurationBuckets = []float64{
	0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10,
}

// Metrics holds the HTTP server instruments and the registry they live in.
//
// The instrumentation is hand-written over the raw primitives rather than using
// promhttp's InstrumentHandler helpers: those panic on a `route` label and
// lower-case the method, so they cannot produce the agreed label set.
type Metrics struct {
	registry *prometheus.Registry

	requests *prometheus.CounterVec
	duration *prometheus.HistogramVec
	active   *prometheus.GaugeVec
}

// NewMetrics builds the registry and registers every collector.
//
// The registry is a fresh one, not the default: the default registry is
// process-global, which makes it impossible to build two independent services
// in one test binary.
func NewMetrics(cfg config.Config) (*Metrics, error) {
	m := &Metrics{
		registry: prometheus.NewRegistry(),

		requests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "http_server_requests_total",
			Help: "Total HTTP requests served.",
		}, []string{"method", "route", "status"}),

		duration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "http_server_request_duration_seconds",
			Help:    "HTTP request duration in seconds.",
			Buckets: DurationBuckets,
		}, []string{"method", "route", "status"}),

		// No route label: the route is not known when a request starts.
		// OpenTelemetry's convention for http.server.active_requests omits it
		// for exactly that reason, and the Python service cannot resolve a
		// route up front at all.
		active: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Name: "http_server_active_requests",
			Help: "HTTP requests currently in flight.",
		}, []string{"method"}),
	}

	// service_owner is deliberately NOT a label on the metrics above. A
	// re-org would otherwise change the identity of every series and break
	// rate() across the boundary. It lives here instead, joinable with
	// Prometheus 3's info().
	targetInfo := prometheus.NewGaugeVec(prometheus.GaugeOpts{
		Name: "target_info",
		Help: "Metadata about the service exposing these metrics.",
	}, []string{"service_name", "service_version", "service_owner", "deployment_environment_name"})
	targetInfo.WithLabelValues(
		cfg.Service.Name, cfg.Service.Version, cfg.Service.Owner, cfg.Env,
	).Set(1)

	for _, collector := range []prometheus.Collector{
		m.requests, m.duration, m.active, targetInfo,
		// Runtime and process metrics are language-specific by nature. They
		// are worth having; nothing compares them against the Python service.
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
	} {
		if err := m.registry.Register(collector); err != nil {
			return nil, err
		}
	}

	return m, nil
}

// Handler serves the Prometheus exposition format. It is mounted on the admin
// port.
func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{
		// A broken collector should not take the endpoint down; report what
		// can be reported.
		ErrorHandling: promhttp.ContinueOnError,
	})
}

// Gatherer exposes the registry for tests that want to read the metrics back.
func (m *Metrics) Gatherer() prometheus.Gatherer { return m.registry }

// RequestStarted increments the in-flight gauge.
func (m *Metrics) RequestStarted(method string) {
	m.active.WithLabelValues(method).Inc()
}

// RequestFinished decrements the in-flight gauge and records the outcome.
func (m *Metrics) RequestFinished(method, route string, status int, elapsed time.Duration) {
	m.active.WithLabelValues(method).Dec()

	code := strconv.Itoa(status)
	m.requests.WithLabelValues(method, route, code).Inc()
	m.duration.WithLabelValues(method, route, code).Observe(elapsed.Seconds())
}
