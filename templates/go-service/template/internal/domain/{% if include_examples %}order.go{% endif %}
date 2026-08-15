package domain

import "time"

// MaxOrderQuantity bounds how many widgets one order may ask for.
const MaxOrderQuantity = 1000

// Order is a request for some number of one widget.
//
// It exists in the template to show a resource that *references* another one:
// creating an order has to consult widgets, which is what makes the dependency
// direction between service packages visible.
type Order struct {
	ID        string    `json:"id" doc:"Unique order identifier."`
	WidgetID  string    `json:"widget_id" doc:"The widget being ordered."`
	Quantity  int       `json:"quantity" doc:"How many widgets were ordered."`
	CreatedAt time.Time `json:"created_at" format:"date-time" doc:"When the order was placed, RFC 3339."`
}

// NewOrder is the input to placing an order.
type NewOrder struct {
	WidgetID string `json:"widget_id" minLength:"1" maxLength:"64" doc:"The widget to order."`
	Quantity int    `json:"quantity" minimum:"1" maximum:"1000" doc:"How many to order."`
}
