package service_test

import (
	"testing"

	"github.com/jeffmgreg/widget-svc/internal/domain"
	"github.com/jeffmgreg/widget-svc/internal/service"
)

// newOrderFixture returns an order service and the ID of a widget that exists,
// since an order cannot be placed without one.
func newOrderFixture(t *testing.T) (*service.Orders, string) {
	t.Helper()

	widgets := newWidgets(t)
	widget, err := widgets.Create(t.Context(), domain.NewWidget{Name: "sprocket", Color: "red"})
	if err != nil {
		t.Fatalf("seeding a widget failed: %v", err)
	}
	return newOrders(t, widgets), widget.ID
}

func TestCreateOrder(t *testing.T) {
	orders, widgetID := newOrderFixture(t)

	got, err := orders.Create(t.Context(), domain.NewOrder{WidgetID: widgetID, Quantity: 3})
	if err != nil {
		t.Fatalf("Create returned unexpected error: %v", err)
	}

	if got.WidgetID != widgetID {
		t.Errorf("Create().WidgetID = %q, want %q", got.WidgetID, widgetID)
	}
	if got.Quantity != 3 {
		t.Errorf("Create().Quantity = %d, want 3", got.Quantity)
	}
	if got.ID == "" {
		t.Error("Create assigned an empty ID")
	}
}

func TestCreateOrderForUnknownWidgetIsInvalid(t *testing.T) {
	orders, _ := newOrderFixture(t)

	_, err := orders.Create(t.Context(), domain.NewOrder{WidgetID: "no-such-widget", Quantity: 1})

	if err == nil {
		t.Fatal("Create for a nonexistent widget succeeded, want an error")
	}
	// Invalid, not not-found: the request is well formed and /orders exists —
	// what is wrong is the reference inside the body.
	if category := domain.CategoryOf(err); category != domain.CategoryInvalid {
		t.Errorf("error category = %q, want %q", category, domain.CategoryInvalid)
	}
}

func TestCreateOrderValidatesQuantity(t *testing.T) {
	tests := []struct {
		name     string
		quantity int
	}{
		{name: "zero", quantity: 0},
		{name: "negative", quantity: -1},
		{name: "above the maximum", quantity: domain.MaxOrderQuantity + 1},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			orders, widgetID := newOrderFixture(t)

			_, err := orders.Create(t.Context(), domain.NewOrder{WidgetID: widgetID, Quantity: tt.quantity})

			if err == nil {
				t.Fatalf("Create with quantity %d succeeded, want an error", tt.quantity)
			}
			if category := domain.CategoryOf(err); category != domain.CategoryInvalid {
				t.Errorf("error category = %q, want %q", category, domain.CategoryInvalid)
			}
		})
	}
}

func TestGetOrder(t *testing.T) {
	orders, widgetID := newOrderFixture(t)
	ctx := t.Context()

	created, err := orders.Create(ctx, domain.NewOrder{WidgetID: widgetID, Quantity: 2})
	if err != nil {
		t.Fatalf("Create returned unexpected error: %v", err)
	}

	t.Run("existing", func(t *testing.T) {
		got, err := orders.Get(ctx, created.ID)
		if err != nil {
			t.Fatalf("Get(%q) returned unexpected error: %v", created.ID, err)
		}
		if got != created {
			t.Errorf("Get(%q) = %+v, want %+v", created.ID, got, created)
		}
	})

	t.Run("missing", func(t *testing.T) {
		_, err := orders.Get(ctx, "no-such-id")
		if err == nil {
			t.Fatal("Get with an unknown ID succeeded, want not_found")
		}
		if category := domain.CategoryOf(err); category != domain.CategoryNotFound {
			t.Errorf("Get error category = %q, want %q", category, domain.CategoryNotFound)
		}
	})
}

func TestListOrdersIsEmptyNotNil(t *testing.T) {
	orders, _ := newOrderFixture(t)

	got, err := orders.List(t.Context())
	if err != nil {
		t.Fatalf("List returned unexpected error: %v", err)
	}
	if got == nil {
		t.Fatal("List returned a nil slice, want an empty one")
	}
}
