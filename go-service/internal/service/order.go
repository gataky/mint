package service

import (
	"context"

	"github.com/jeffmgreg/widget-svc/internal/domain"
)

// OrderRepository is the persistence the order service needs.
type OrderRepository interface {
	List(ctx context.Context) ([]domain.Order, error)
	Get(ctx context.Context, id string) (domain.Order, error)
	Create(ctx context.Context, order domain.Order) error
}

// WidgetLookup is the part of the widget service that orders depend on.
//
// **It is deliberately narrower than *Widgets.** Depending on the whole widget
// service would make every change to widgets a potential change to orders; this
// says exactly what orders need, and *Widgets satisfies it without knowing that
// orders exist. This is the pattern to copy when one resource needs another.
type WidgetLookup interface {
	Get(ctx context.Context, id string) (domain.Widget, error)
}

// Orders is the order business logic.
type Orders struct {
	repo    OrderRepository
	widgets WidgetLookup
	ids     IDGenerator
	now     Clock
}

// NewOrders wires the order service to its dependencies.
func NewOrders(repo OrderRepository, widgets WidgetLookup, ids IDGenerator, now Clock) *Orders {
	return &Orders{repo: repo, widgets: widgets, ids: ids, now: now}
}

// List returns every order, oldest first.
func (o *Orders) List(ctx context.Context) ([]domain.Order, error) {
	return o.repo.List(ctx)
}

// Get returns one order by ID.
func (o *Orders) Get(ctx context.Context, id string) (domain.Order, error) {
	return o.repo.Get(ctx, id)
}

// Create validates and stores a new order.
func (o *Orders) Create(ctx context.Context, in domain.NewOrder) (domain.Order, error) {
	if in.Quantity < 1 || in.Quantity > domain.MaxOrderQuantity {
		return domain.Order{}, domain.Invalid("quantity must be between 1 and %d", domain.MaxOrderQuantity)
	}

	// The referenced widget has to exist. This is reported as invalid rather
	// than not-found: the request is well formed and /orders exists — what is
	// wrong is the reference inside the body.
	switch _, err := o.widgets.Get(ctx, in.WidgetID); {
	case domain.CategoryOf(err) == domain.CategoryNotFound:
		return domain.Order{}, domain.Invalid("no widget with id %q", in.WidgetID)
	case err != nil:
		return domain.Order{}, err
	}

	order := domain.Order{
		ID:        o.ids(),
		WidgetID:  in.WidgetID,
		Quantity:  in.Quantity,
		CreatedAt: o.now(),
	}
	if err := o.repo.Create(ctx, order); err != nil {
		return domain.Order{}, err
	}
	return order, nil
}
