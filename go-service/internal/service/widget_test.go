package service

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"
)

// newTestWidgets returns a Widgets with a fixed clock and predictable IDs, so
// assertions can name exact values instead of matching patterns.
func newTestWidgets() *Widgets {
	var n int
	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	return &Widgets{
		items: map[string]Widget{},
		now: func() time.Time {
			n++
			return base.Add(time.Duration(n) * time.Second)
		},
		newID: func() string {
			return fmt.Sprintf("widget-%d", n)
		},
	}
}

func TestCreateWidget(t *testing.T) {
	tests := []struct {
		name      string
		input     NewWidget
		wantName  string
		wantError Category
	}{
		{
			name:     "valid",
			input:    NewWidget{Name: "sprocket", Color: "red"},
			wantName: "sprocket",
		},
		{
			name:     "trims surrounding whitespace",
			input:    NewWidget{Name: "  sprocket  ", Color: "blue"},
			wantName: "sprocket",
		},
		{
			name:      "blank name is invalid",
			input:     NewWidget{Name: "   ", Color: "red"},
			wantError: CategoryInvalid,
		},
		{
			name:      "unknown color is invalid",
			input:     NewWidget{Name: "sprocket", Color: "puce"},
			wantError: CategoryInvalid,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			widgets := newTestWidgets()

			got, err := widgets.Create(t.Context(), tt.input)

			if tt.wantError != "" {
				if err == nil {
					t.Fatalf("Create(%+v) = %+v, want error category %q", tt.input, got, tt.wantError)
				}
				if category := CategoryOf(err); category != tt.wantError {
					t.Fatalf("Create(%+v) error category = %q, want %q", tt.input, category, tt.wantError)
				}
				return
			}

			if err != nil {
				t.Fatalf("Create(%+v) returned unexpected error: %v", tt.input, err)
			}
			if got.Name != tt.wantName {
				t.Errorf("Create(%+v).Name = %q, want %q", tt.input, got.Name, tt.wantName)
			}
			if got.ID == "" {
				t.Error("Create assigned an empty ID")
			}
			if got.CreatedAt.IsZero() {
				t.Error("Create left CreatedAt zero")
			}
		})
	}
}

func TestCreateWidgetRejectsDuplicateName(t *testing.T) {
	widgets := newTestWidgets()
	ctx := t.Context()

	if _, err := widgets.Create(ctx, NewWidget{Name: "sprocket", Color: "red"}); err != nil {
		t.Fatalf("first Create returned unexpected error: %v", err)
	}

	// The duplicate check is case-insensitive, so this must collide.
	_, err := widgets.Create(ctx, NewWidget{Name: "SPROCKET", Color: "blue"})
	if err == nil {
		t.Fatal("second Create with a duplicate name succeeded, want a conflict")
	}
	if category := CategoryOf(err); category != CategoryConflict {
		t.Errorf("duplicate name error category = %q, want %q", category, CategoryConflict)
	}
}

func TestGetWidget(t *testing.T) {
	widgets := newTestWidgets()
	ctx := t.Context()

	created, err := widgets.Create(ctx, NewWidget{Name: "sprocket", Color: "red"})
	if err != nil {
		t.Fatalf("Create returned unexpected error: %v", err)
	}

	t.Run("existing", func(t *testing.T) {
		got, err := widgets.Get(ctx, created.ID)
		if err != nil {
			t.Fatalf("Get(%q) returned unexpected error: %v", created.ID, err)
		}
		if got != created {
			t.Errorf("Get(%q) = %+v, want %+v", created.ID, got, created)
		}
	})

	t.Run("missing", func(t *testing.T) {
		_, err := widgets.Get(ctx, "no-such-id")
		if err == nil {
			t.Fatal("Get with an unknown ID succeeded, want not_found")
		}
		if category := CategoryOf(err); category != CategoryNotFound {
			t.Errorf("Get error category = %q, want %q", category, CategoryNotFound)
		}
	})
}

func TestListWidgetsIsOrderedOldestFirst(t *testing.T) {
	widgets := newTestWidgets()
	ctx := t.Context()

	for _, name := range []string{"first", "second", "third"} {
		if _, err := widgets.Create(ctx, NewWidget{Name: name, Color: "red"}); err != nil {
			t.Fatalf("Create(%q) returned unexpected error: %v", name, err)
		}
	}

	got, err := widgets.List(ctx)
	if err != nil {
		t.Fatalf("List returned unexpected error: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("List returned %d widgets, want 3", len(got))
	}
	for i, want := range []string{"first", "second", "third"} {
		if got[i].Name != want {
			t.Errorf("List()[%d].Name = %q, want %q", i, got[i].Name, want)
		}
	}
}

func TestListWidgetsIsEmptyNotNil(t *testing.T) {
	// A nil slice serializes as JSON null; an empty one as []. The API
	// contract promises a list, so this must not regress.
	got, err := newTestWidgets().List(t.Context())
	if err != nil {
		t.Fatalf("List returned unexpected error: %v", err)
	}
	if got == nil {
		t.Fatal("List returned a nil slice, want an empty one")
	}
	if len(got) != 0 {
		t.Fatalf("List returned %d widgets, want 0", len(got))
	}
}

func TestCategoryOfUnknownErrorIsInternal(t *testing.T) {
	// Anything that is not a domain error is an internal one — the transport
	// must never turn an unexpected failure into a 4xx.
	if category := CategoryOf(errors.New("boom")); category != CategoryInternal {
		t.Errorf("CategoryOf(plain error) = %q, want %q", category, CategoryInternal)
	}
}

func TestInternalErrorKeepsCauseUnexported(t *testing.T) {
	cause := errors.New("connection refused")
	err := Internal(cause, "could not reach the store")

	if !errors.Is(err, cause) {
		t.Error("Internal did not wrap its cause; errors.Is could not find it")
	}
	if CategoryOf(err) != CategoryInternal {
		t.Errorf("CategoryOf(Internal) = %q, want %q", CategoryOf(err), CategoryInternal)
	}
}

func TestOperationsRespectContextCancellation(t *testing.T) {
	widgets := newTestWidgets()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if _, err := widgets.List(ctx); err == nil {
		t.Error("List on a cancelled context succeeded, want an error")
	}
	if _, err := widgets.Get(ctx, "any"); err == nil {
		t.Error("Get on a cancelled context succeeded, want an error")
	}
	if _, err := widgets.Create(ctx, NewWidget{Name: "x", Color: "red"}); err == nil {
		t.Error("Create on a cancelled context succeeded, want an error")
	}
}
