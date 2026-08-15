// Package http is the HTTP transport. Handlers parse and validate the *shape*
// of a request, call the service layer, and serialize the result. Business
// rules live in the service layer, not here.
//
// The package nests under internal/transport deliberately. There is one
// transport today; the nesting is what makes a second one an addition rather
// than a refactor.
package http

import (
	"log/slog"
	"net/http"

	"github.com/danielgtaylor/huma/v2"
	"github.com/danielgtaylor/huma/v2/adapters/humago"

	"{@ module_path @}/internal/config"
{% if include_examples %}	"{@ module_path @}/internal/service"
{% endif %})

// NewAPI builds the public API handler: every resource's operations, the
// OpenAPI 3.1 document at /openapi.json, and Swagger UI at /docs.
//
// It returns the concrete *http.ServeMux rather than an http.Handler so the
// middleware can ask it to resolve a route template before dispatch — see
// MuxResolver.
func NewAPI(cfg config.Config, {% if include_examples %}widgets *service.Widgets, orders *service.Orders, {% endif %}logger *slog.Logger) *http.ServeMux {
	configureErrorModel()

	mux := http.NewServeMux()

	humaCfg := huma.DefaultConfig(cfg.Service.Name, cfg.Service.Version)
	humaCfg.Info.Description = "{@ service_description @}"
	humaCfg.DocsPath = "/docs"
	humaCfg.DocsRenderer = huma.DocsRendererSwaggerUI

	// Drop huma's schema-link transformer. It injects a "$schema" property into
	// every response body and serves a /schemas route; neither is part of the
	// contract this service publishes.
	humaCfg.CreateHooks = nil
	humaCfg.SchemasPath = ""

	api := humago.New(mux, humaCfg)

	// One call per resource. Each lives in its own file alongside this one.
{% if include_examples %}	registerWidgets(api, widgets)
	registerOrders(api, orders)
{% else %}	// registerThings(api, things)
	_ = api // remove once the first resource is registered
{% endif %}
	// Anything that matches no route still gets a problem+json body rather than
	// net/http's plain-text "404 page not found".
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeProblem(w, r, http.StatusNotFound, "Not Found", "no route matches "+r.Method+" "+r.URL.Path)
	})

	return mux
}

// configureErrorModel fills in the two RFC 9457 fields huma leaves empty, so
// that an error body from this service is indistinguishable from one minted
// from the Python template.
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
