// Package http is the HTTP transport. Handlers parse and validate the *shape*
// of a request, call the service layer, and serialize the result. Business
// rules live in the service layer, not here.
//
// The package nests under internal/transport deliberately. There is one
// transport today; the nesting is what makes a second one an addition rather
// than a refactor.
package http

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/danielgtaylor/huma/v2"
	"github.com/danielgtaylor/huma/v2/adapters/humago"

	"github.com/jeffmgreg/widget-svc/internal/config"
	"github.com/jeffmgreg/widget-svc/internal/service"
)

// NewAPI builds the public API handler: the widget operations, the OpenAPI 3.1
// document at /openapi.json, and Swagger UI at /docs.
//
// It returns the concrete *http.ServeMux rather than an http.Handler so the
// middleware can ask it to resolve a route template before dispatch — see
// MuxResolver.
func NewAPI(cfg config.Config, widgets *service.Widgets, logger *slog.Logger) *http.ServeMux {
	configureErrorModel()

	mux := http.NewServeMux()

	humaCfg := huma.DefaultConfig(cfg.Service.Name, cfg.Service.Version)
	humaCfg.Info.Description = "Widget service. Generated from the Mint template."
	humaCfg.DocsPath = "/docs"
	humaCfg.DocsRenderer = huma.DocsRendererSwaggerUI

	// Drop huma's schema-link transformer. It injects a "$schema" property into
	// every response body and serves a /schemas route; neither is part of the
	// contract this service shares with the Python implementation.
	humaCfg.CreateHooks = nil
	humaCfg.SchemasPath = ""

	api := humago.New(mux, humaCfg)

	registerWidgets(api, widgets)

	// Anything that matches no route still gets a problem+json body rather than
	// net/http's plain-text "404 page not found".
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeProblem(w, r, http.StatusNotFound, "Not Found", "no route matches "+r.Method+" "+r.URL.Path)
	})

	return mux
}

// configureErrorModel fills in the two RFC 9457 fields huma leaves empty, so
// that an error body from this service is indistinguishable from the Python
// service's.
//
// huma exposes this as a package-level variable rather than per-API config, so
// this is a process-wide setting. It is idempotent and set once at startup.
func configureErrorModel() {
	huma.NewErrorWithContext = func(ctx huma.Context, status int, msg string, errs ...error) huma.StatusError {
		err := huma.NewError(status, msg, errs...)
		if model, ok := err.(*huma.ErrorModel); ok {
			model.Type = DefaultProblemType
			model.Instance = ctx.URL().Path
		}
		return err
	}
}

type listWidgetsOutput struct {
	Body []service.Widget
}

type getWidgetInput struct {
	ID string `path:"id" minLength:"1" maxLength:"64" doc:"Widget identifier."`
}

type widgetOutput struct {
	Body service.Widget
}

type createWidgetInput struct {
	Body service.NewWidget
}

// registerWidgets wires the widget operations. Each one is declared once here:
// the router and the OpenAPI document both read this, so there is no second
// place to update when an operation changes.
func registerWidgets(api huma.API, widgets *service.Widgets) {
	huma.Register(api, huma.Operation{
		OperationID: "widgets.list",
		Method:      http.MethodGet,
		Path:        "/widgets",
		Summary:     "List widgets",
		Description: "Returns every widget, oldest first.",
		Tags:        []string{"widgets"},
	}, func(ctx context.Context, _ *struct{}) (*listWidgetsOutput, error) {
		found, err := widgets.List(ctx)
		if err != nil {
			return nil, problem(ctx, err)
		}
		return &listWidgetsOutput{Body: found}, nil
	})

	huma.Register(api, huma.Operation{
		OperationID: "widgets.get",
		Method:      http.MethodGet,
		Path:        "/widgets/{id}",
		Summary:     "Fetch a widget by ID",
		Tags:        []string{"widgets"},
		Errors:      []int{http.StatusNotFound},
	}, func(ctx context.Context, in *getWidgetInput) (*widgetOutput, error) {
		found, err := widgets.Get(ctx, in.ID)
		if err != nil {
			return nil, problem(ctx, err)
		}
		return &widgetOutput{Body: found}, nil
	})

	huma.Register(api, huma.Operation{
		OperationID:   "widgets.create",
		Method:        http.MethodPost,
		Path:          "/widgets",
		Summary:       "Create a widget",
		Tags:          []string{"widgets"},
		DefaultStatus: http.StatusCreated,
		Errors:        []int{http.StatusBadRequest, http.StatusConflict},
	}, func(ctx context.Context, in *createWidgetInput) (*widgetOutput, error) {
		created, err := widgets.Create(ctx, in.Body)
		if err != nil {
			return nil, problem(ctx, err)
		}
		return &widgetOutput{Body: created}, nil
	})
}
