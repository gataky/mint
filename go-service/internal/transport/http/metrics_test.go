package http

import (
	"net/http"
	"slices"
	"strings"
	"testing"

	dto "github.com/prometheus/client_model/go"

	"github.com/jeffmgreg/widget-svc/internal/config"
	"github.com/jeffmgreg/widget-svc/internal/logging"
	"github.com/jeffmgreg/widget-svc/internal/observability"
	"github.com/jeffmgreg/widget-svc/internal/service"
)

// newInstrumentedAPI builds the API with metrics wired exactly as the
// composition root does.
func newInstrumentedAPI(t *testing.T) (http.Handler, *observability.Metrics) {
	t.Helper()

	cfg := config.Defaults()
	cfg.Service.Owner = "platform"

	metrics, err := observability.NewMetrics(cfg)
	if err != nil {
		t.Fatalf("NewMetrics: %v", err)
	}

	logger := logging.New(logging.Options{Level: "error", Format: "json", Output: &strings.Builder{}})
	mux := NewAPI(cfg, service.NewWidgets(), logger)

	handler := Chain(
		mux,
		Recovery(logger),
		RequestContext(),
		Metrics(metrics, MuxResolver(mux)),
		Logging(logger, MuxResolver(mux)),
		Timeout(cfg.Server.RequestTimeout),
	)
	return handler, metrics
}

func TestMetricsRecordTheAgreedNamesAndLabels(t *testing.T) {
	handler, metrics := newInstrumentedAPI(t)

	do(t, handler, http.MethodGet, "/widgets", "")

	families := gather(t, metrics)

	// The names and label keys are the contract. Anything outside this set is
	// language-specific runtime instrumentation and is not compared.
	want := map[string][]string{
		"http_server_requests_total":           {"method", "route", "status"},
		"http_server_request_duration_seconds": {"method", "route", "status"},
		"http_server_active_requests":          {"method"},
	}

	for name, wantLabels := range want {
		family, found := families[name]
		if !found {
			t.Errorf("no metric family named %q", name)
			continue
		}
		if got := labelKeys(family); !slices.Equal(got, wantLabels) {
			t.Errorf("%s label keys = %v, want %v", name, got, wantLabels)
		}
	}
}

func TestMetricsLabelTheRouteTemplateNotThePath(t *testing.T) {
	handler, metrics := newInstrumentedAPI(t)

	// Two different widgets must land on one series, or every ID ever
	// requested becomes its own time series.
	do(t, handler, http.MethodGet, "/widgets/abc", "")
	do(t, handler, http.MethodGet, "/widgets/def", "")

	routes := labelValues(t, metrics, "http_server_requests_total", "route")
	if len(routes) != 1 || routes[0] != "/widgets/{id}" {
		t.Errorf("route label values = %v, want exactly [/widgets/{id}]", routes)
	}
}

func TestMetricsBoundCardinalityForUnroutedRequests(t *testing.T) {
	handler, metrics := newInstrumentedAPI(t)

	// A flood of requests to random paths must not be able to create a series
	// per path.
	for _, path := range []string{"/nope-1", "/nope-2", "/nope-3"} {
		do(t, handler, http.MethodGet, path, "")
	}

	routes := labelValues(t, metrics, "http_server_requests_total", "route")
	if len(routes) != 1 || routes[0] != UnmatchedRoute {
		t.Errorf("route label values = %v, want exactly [%s]", routes, UnmatchedRoute)
	}
}

func TestMetricsCountByStatus(t *testing.T) {
	handler, metrics := newInstrumentedAPI(t)

	do(t, handler, http.MethodGet, "/widgets", "")
	do(t, handler, http.MethodGet, "/widgets/missing", "")

	statuses := labelValues(t, metrics, "http_server_requests_total", "status")
	if !slices.Equal(statuses, []string{"200", "404"}) {
		t.Errorf("status label values = %v, want [200 404]", statuses)
	}
}

func TestActiveRequestsReturnsToZero(t *testing.T) {
	handler, metrics := newInstrumentedAPI(t)

	do(t, handler, http.MethodGet, "/widgets", "")

	family, found := gather(t, metrics)["http_server_active_requests"]
	if !found {
		t.Fatal("no http_server_active_requests family")
	}
	for _, metric := range family.GetMetric() {
		if got := metric.GetGauge().GetValue(); got != 0 {
			t.Errorf("in-flight gauge = %v after the request completed, want 0", got)
		}
	}
}

func TestActiveRequestsIsDecrementedAfterAPanic(t *testing.T) {
	cfg := config.Defaults()
	metrics, err := observability.NewMetrics(cfg)
	if err != nil {
		t.Fatalf("NewMetrics: %v", err)
	}

	logger := logging.New(logging.Options{Level: "error", Format: "json", Output: &strings.Builder{}})
	exploding := http.HandlerFunc(func(http.ResponseWriter, *http.Request) { panic("boom") })
	resolve := func(*http.Request) string { return "/boom" }

	handler := Chain(exploding,
		Recovery(logger),
		RequestContext(),
		Metrics(metrics, resolve),
	)

	do(t, handler, http.MethodGet, "/boom", "")

	// Recovery sits OUTSIDE the metrics middleware, so without a deferred
	// decrement the gauge would climb by one on every panic and never come down.
	family, found := gather(t, metrics)["http_server_active_requests"]
	if !found {
		t.Fatal("no http_server_active_requests family")
	}
	for _, metric := range family.GetMetric() {
		if got := metric.GetGauge().GetValue(); got != 0 {
			t.Errorf("in-flight gauge = %v after a panic, want 0", got)
		}
	}
}

func TestTargetInfoCarriesTheOwner(t *testing.T) {
	_, metrics := newInstrumentedAPI(t)

	family, found := gather(t, metrics)["target_info"]
	if !found {
		t.Fatal("no target_info family")
	}

	// service_owner belongs here and NOT on the request metrics: a re-org
	// would otherwise change the identity of every series and break rate()
	// across the boundary.
	got := labelKeys(family)
	want := []string{"deployment_environment_name", "service_name", "service_owner", "service_version"}
	if !slices.Equal(got, want) {
		t.Errorf("target_info label keys = %v, want %v", got, want)
	}

	for _, name := range []string{"http_server_requests_total", "http_server_request_duration_seconds"} {
		if keys := labelKeys(gather(t, metrics)[name]); slices.Contains(keys, "service_owner") {
			t.Errorf("%s carries a service_owner label; it belongs on target_info only", name)
		}
	}
}

func TestDurationUsesTheAdvisoryBuckets(t *testing.T) {
	handler, metrics := newInstrumentedAPI(t)

	do(t, handler, http.MethodGet, "/widgets", "")

	family := gather(t, metrics)["http_server_request_duration_seconds"]
	if family == nil {
		t.Fatal("no duration family")
	}

	var bounds []float64
	for _, bucket := range family.GetMetric()[0].GetHistogram().GetBucket() {
		bounds = append(bounds, bucket.GetUpperBound())
	}
	if len(bounds) != len(observability.DurationBuckets) {
		t.Fatalf("histogram has %d buckets, want the %d advisory ones",
			len(bounds), len(observability.DurationBuckets))
	}
	for i, want := range observability.DurationBuckets {
		if bounds[i] != want {
			t.Errorf("bucket %d = %v, want %v", i, bounds[i], want)
		}
	}
}

func TestMetricsEndpointIsServedOnAdmin(t *testing.T) {
	api, metrics := newInstrumentedAPI(t)

	// A labelled metric family is not exposed until it has been observed at
	// least once, so serve a request before scraping.
	do(t, api, http.MethodGet, "/widgets", "")

	rec := do(t, NewAdmin(NewHealth(), metrics), http.MethodGet, "/metrics", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("GET /metrics = %d, want 200", rec.Code)
	}
	for _, name := range []string{
		"http_server_requests_total",
		"http_server_request_duration_seconds",
		"http_server_active_requests",
		"target_info",
	} {
		if !strings.Contains(rec.Body.String(), name) {
			t.Errorf("/metrics does not mention %q", name)
		}
	}
}

// gather collects the registry into a map keyed by family name.
func gather(t *testing.T, m *observability.Metrics) map[string]*dto.MetricFamily {
	t.Helper()

	gathered, err := m.Gatherer().Gather()
	if err != nil {
		t.Fatalf("gather: %v", err)
	}

	families := make(map[string]*dto.MetricFamily, len(gathered))
	for _, family := range gathered {
		families[family.GetName()] = family
	}
	return families
}

// labelKeys returns the sorted label keys of a family's first metric.
func labelKeys(family *dto.MetricFamily) []string {
	if family == nil || len(family.GetMetric()) == 0 {
		return nil
	}
	var keys []string
	for _, pair := range family.GetMetric()[0].GetLabel() {
		keys = append(keys, pair.GetName())
	}
	slices.Sort(keys)
	return keys
}

// labelValues returns the sorted distinct values a family carries for one label.
func labelValues(t *testing.T, m *observability.Metrics, family, label string) []string {
	t.Helper()

	found := gather(t, m)[family]
	if found == nil {
		t.Fatalf("no metric family named %q", family)
	}

	seen := map[string]bool{}
	for _, metric := range found.GetMetric() {
		for _, pair := range metric.GetLabel() {
			if pair.GetName() == label {
				seen[pair.GetValue()] = true
			}
		}
	}

	values := make([]string, 0, len(seen))
	for value := range seen {
		values = append(values, value)
	}
	slices.Sort(values)
	return values
}
