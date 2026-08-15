// Package service holds the business logic. It takes and returns plain Go
// types: no http.Request, no huma types, no driver types. The transport layer
// calls into it; it never calls back out.
//
// Widgets are held in memory. A real service would put a repository interface
// here — owned by this package, implemented elsewhere — and depend on that.
package service

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"slices"
	"strings"
	"sync"
	"time"
)

// Colors a widget may be. Kept as a list so the validation message, the OpenAPI
// enum, and the check below cannot drift apart.
var Colors = []string{"red", "green", "blue"}

// Widget is the example resource, threaded through both layers.
type Widget struct {
	ID        string    `json:"id" doc:"Unique widget identifier."`
	Name      string    `json:"name" doc:"Human-readable widget name."`
	Color     string    `json:"color" enum:"red,green,blue" doc:"Widget color."`
	CreatedAt time.Time `json:"created_at" format:"date-time" doc:"When the widget was created, RFC 3339."`
}

// NewWidget is the input to Create. It is a separate type from Widget because
// the server, not the client, owns ID and CreatedAt.
type NewWidget struct {
	Name  string `json:"name" minLength:"1" maxLength:"64" doc:"Human-readable widget name."`
	Color string `json:"color" enum:"red,green,blue" doc:"Widget color."`
}

// Widgets is the widget business logic over an in-memory store.
type Widgets struct {
	mu    sync.RWMutex
	items map[string]Widget

	// Injected so tests get deterministic output without touching the clock.
	now   func() time.Time
	newID func() string
}

// NewWidgets returns a Widgets with real time and random IDs.
func NewWidgets() *Widgets {
	return &Widgets{
		items: map[string]Widget{},
		now:   time.Now,
		newID: randomID,
	}
}

// List returns every widget, oldest first.
func (w *Widgets) List(ctx context.Context) ([]Widget, error) {
	if err := ctx.Err(); err != nil {
		return nil, Internal(err, "request cancelled")
	}

	w.mu.RLock()
	defer w.mu.RUnlock()

	out := make([]Widget, 0, len(w.items))
	for _, widget := range w.items {
		out = append(out, widget)
	}
	slices.SortFunc(out, func(a, b Widget) int {
		if c := a.CreatedAt.Compare(b.CreatedAt); c != 0 {
			return c
		}
		return strings.Compare(a.ID, b.ID)
	})
	return out, nil
}

// Get returns one widget by ID.
func (w *Widgets) Get(ctx context.Context, id string) (Widget, error) {
	if err := ctx.Err(); err != nil {
		return Widget{}, Internal(err, "request cancelled")
	}

	w.mu.RLock()
	defer w.mu.RUnlock()

	widget, ok := w.items[id]
	if !ok {
		return Widget{}, NotFound("no widget with id %q", id)
	}
	return widget, nil
}

// Create stores a new widget and returns it.
func (w *Widgets) Create(ctx context.Context, in NewWidget) (Widget, error) {
	if err := ctx.Err(); err != nil {
		return Widget{}, Internal(err, "request cancelled")
	}

	// Business rules live here, not in the transport. The transport has already
	// checked the shape; this checks the meaning.
	name := strings.TrimSpace(in.Name)
	if name == "" {
		return Widget{}, Invalid("name must not be blank")
	}
	if !slices.Contains(Colors, in.Color) {
		return Widget{}, Invalid("color must be one of %s", strings.Join(Colors, ", "))
	}

	w.mu.Lock()
	defer w.mu.Unlock()

	for _, existing := range w.items {
		if strings.EqualFold(existing.Name, name) {
			return Widget{}, Conflict("a widget named %q already exists", name)
		}
	}

	widget := Widget{
		ID:        w.newID(),
		Name:      name,
		Color:     in.Color,
		CreatedAt: w.now().UTC().Truncate(time.Millisecond),
	}
	w.items[widget.ID] = widget
	return widget, nil
}

func randomID() string {
	buf := make([]byte, 8)
	// rand.Read from crypto/rand cannot fail as of Go 1.24; it panics instead.
	_, _ = rand.Read(buf)
	return hex.EncodeToString(buf)
}
