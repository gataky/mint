package http

import (
	"net/http"
	"strings"
	"testing"

	"github.com/jeffmgreg/widget-svc/internal/domain"
)

func TestPlaceAndFetchOrder(t *testing.T) {
	handler, _ := newTestAPI(t)
	widgetID := seedWidget(t, handler, "sprocket")

	created := do(t, handler, http.MethodPost, "/orders",
		`{"widget_id":"`+widgetID+`","quantity":3}`)
	if created.Code != http.StatusCreated {
		t.Fatalf("POST /orders = %d, want %d: %s", created.Code, http.StatusCreated, created.Body)
	}

	order := decode[domain.Order](t, created)
	if order.WidgetID != widgetID {
		t.Errorf("POST /orders returned widget_id %q, want %q", order.WidgetID, widgetID)
	}
	if order.Quantity != 3 {
		t.Errorf("POST /orders returned quantity %d, want 3", order.Quantity)
	}

	fetched := do(t, handler, http.MethodGet, "/orders/"+order.ID, "")
	if fetched.Code != http.StatusOK {
		t.Fatalf("GET /orders/{id} = %d, want 200: %s", fetched.Code, fetched.Body)
	}
	if got := decode[domain.Order](t, fetched); got.ID != order.ID {
		t.Errorf("GET /orders/{id} returned ID %q, want %q", got.ID, order.ID)
	}
}

func TestOrderForUnknownWidgetIsBadRequest(t *testing.T) {
	handler, _ := newTestAPI(t)

	rec := do(t, handler, http.MethodPost, "/orders",
		`{"widget_id":"no-such-widget","quantity":1}`)

	// 400, not 404: the request is well formed and /orders exists — what is
	// wrong is the reference inside the body.
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("POST /orders for a missing widget = %d, want 400: %s", rec.Code, rec.Body)
	}
	if got := rec.Header().Get("Content-Type"); got != ProblemContentType {
		t.Errorf("Content-Type = %q, want %q", got, ProblemContentType)
	}
	if got := decode[map[string]any](t, rec)["title"]; got != "Bad Request" {
		t.Errorf(`body["title"] = %v, want "Bad Request"`, got)
	}
}

func TestOrderQuantityIsValidatedAtTheEdge(t *testing.T) {
	tests := []struct {
		name string
		body string
	}{
		{name: "zero", body: `{"widget_id":"%s","quantity":0}`},
		{name: "negative", body: `{"widget_id":"%s","quantity":-1}`},
		{name: "above the maximum", body: `{"widget_id":"%s","quantity":99999}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			handler, _ := newTestAPI(t)
			widgetID := seedWidget(t, handler, "sprocket")

			rec := do(t, handler, http.MethodPost, "/orders",
				strings.Replace(tt.body, "%s", widgetID, 1))

			// The bounds are declared on the input struct, so huma rejects
			// these before the service is reached.
			if rec.Code != http.StatusUnprocessableEntity {
				t.Fatalf("POST /orders = %d, want 422: %s", rec.Code, rec.Body)
			}
		})
	}
}

func TestListOrdersReturnsEmptyArray(t *testing.T) {
	handler, _ := newTestAPI(t)

	rec := do(t, handler, http.MethodGet, "/orders", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("GET /orders = %d, want 200", rec.Code)
	}
	if got := strings.TrimSpace(rec.Body.String()); got != "[]" {
		t.Errorf("GET /orders on an empty store = %s, want []", got)
	}
}

func TestUnknownOrderIsNotFound(t *testing.T) {
	handler, _ := newTestAPI(t)

	rec := do(t, handler, http.MethodGet, "/orders/no-such-id", "")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("GET /orders/no-such-id = %d, want 404: %s", rec.Code, rec.Body)
	}
	if got := decode[map[string]any](t, rec)["instance"]; got != "/orders/no-such-id" {
		t.Errorf(`body["instance"] = %v, want the request path`, got)
	}
}

func TestOpenAPIDocumentsBothResources(t *testing.T) {
	handler, _ := newTestAPI(t)

	rec := do(t, handler, http.MethodGet, "/openapi.json", "")
	body := rec.Body.String()

	// Adding a resource must show up in the published document without anyone
	// editing it by hand.
	for _, want := range []string{
		`"/widgets"`, `"/widgets/{id}"`,
		`"/orders"`, `"/orders/{id}"`,
		`"widgets.list"`, `"orders.create"`,
	} {
		if !strings.Contains(body, want) {
			t.Errorf("/openapi.json does not mention %s", want)
		}
	}
}
