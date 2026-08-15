package http

import (
	"context"
	"net/http"

	"github.com/danielgtaylor/huma/v2"

	"github.com/jeffmgreg/widget-svc/internal/domain"
	"github.com/jeffmgreg/widget-svc/internal/service"
)

type listWidgetsOutput struct {
	Body []domain.Widget
}

type getWidgetInput struct {
	ID string `path:"id" minLength:"1" maxLength:"64" doc:"Widget identifier."`
}

type widgetOutput struct {
	Body domain.Widget
}

type createWidgetInput struct {
	Body domain.NewWidget
}

// registerWidgets wires the widget operations.
//
// Each is declared in one huma.Register call: the router and /openapi.json both
// read it, so there is no second place to update when an operation changes.
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
