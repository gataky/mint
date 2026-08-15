package http

import (
	"net/http"
	"testing"

	"github.com/jeffmgreg/widget-svc/internal/repository/memory"
	"github.com/jeffmgreg/widget-svc/internal/service"
)

// newTestServices builds the service layer over empty in-memory repositories,
// wired exactly as the composition root wires it.
//
// Adding a resource means adding it here once, rather than in every test that
// builds an API.
func newTestServices(t *testing.T) (*service.Widgets, *service.Orders) {
	t.Helper()

	widgets := service.NewWidgets(memory.NewWidgets(), service.RandomID, service.SystemClock)
	orders := service.NewOrders(memory.NewOrders(), widgets, service.RandomID, service.SystemClock)
	return widgets, orders
}

// seedWidget creates a widget through the API and returns its ID, for tests
// that need one to exist.
func seedWidget(t *testing.T, handler http.Handler, name string) string {
	t.Helper()

	rec := do(t, handler, http.MethodPost, "/widgets",
		`{"name":"`+name+`","color":"red"}`)
	if rec.Code != http.StatusCreated {
		t.Fatalf("seeding widget %q failed with %d: %s", name, rec.Code, rec.Body)
	}
	return decode[map[string]any](t, rec)["id"].(string)
}
