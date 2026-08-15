package domain

import "time"

// Colors a widget may be. Kept as a list so the validation message, the OpenAPI
// enum, and the check in the service layer cannot drift apart.
var Colors = []string{"red", "green", "blue"}

// Widget is a thing this service manages.
type Widget struct {
	ID        string    `json:"id" doc:"Unique widget identifier."`
	Name      string    `json:"name" doc:"Human-readable widget name."`
	Color     string    `json:"color" enum:"red,green,blue" doc:"Widget color."`
	CreatedAt time.Time `json:"created_at" format:"date-time" doc:"When the widget was created, RFC 3339."`
}

// NewWidget is the input to creating a widget. It is a separate type from
// Widget because the server, not the client, owns ID and CreatedAt.
type NewWidget struct {
	Name  string `json:"name" minLength:"1" maxLength:"64" doc:"Human-readable widget name."`
	Color string `json:"color" enum:"red,green,blue" doc:"Widget color."`
}
