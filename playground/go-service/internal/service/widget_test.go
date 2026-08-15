package service_test

import (
	"context"
	"testing"

	"github.com/jeffmgreg/widget-svc/internal/domain"
)

func TestCreateWidget(t *testing.T) {
	tests := []struct {
		name      string
		input     domain.NewWidget
		wantName  string
		wantError domain.Category
	}{
		{
			name:     "valid",
			input:    domain.NewWidget{Name: "sprocket", Color: "red"},
			wantName: "sprocket",
		},
		{
			name:     "trims surrounding whitespace",
			input:    domain.NewWidget{Name: "  sprocket  ", Color: "blue"},
			wantName: "sprocket",
		},
		{
			name:      "blank name is invalid",
			input:     domain.NewWidget{Name: "   ", Color: "red"},
			wantError: domain.CategoryInvalid,
		},
		{
			name:      "unknown color is invalid",
			input:     domain.NewWidget{Name: "sprocket", Color: "puce"},
			wantError: domain.CategoryInvalid,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			widgets := newWidgets(t)

			got, err := widgets.Create(t.Context(), tt.input)

			if tt.wantError != "" {
				if err == nil {
					t.Fatalf("Create(%+v) = %+v, want error category %q", tt.input, got, tt.wantError)
				}
				if category := domain.CategoryOf(err); category != tt.wantError {
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
	widgets := newWidgets(t)
	ctx := t.Context()

	if _, err := widgets.Create(ctx, domain.NewWidget{Name: "sprocket", Color: "red"}); err != nil {
		t.Fatalf("first Create returned unexpected error: %v", err)
	}

	// The duplicate check is case-insensitive, so this must collide.
	_, err := widgets.Create(ctx, domain.NewWidget{Name: "SPROCKET", Color: "blue"})
	if err == nil {
		t.Fatal("second Create with a duplicate name succeeded, want a conflict")
	}
	if category := domain.CategoryOf(err); category != domain.CategoryConflict {
		t.Errorf("duplicate name error category = %q, want %q", category, domain.CategoryConflict)
	}
}

func TestGetWidget(t *testing.T) {
	widgets := newWidgets(t)
	ctx := t.Context()

	created, err := widgets.Create(ctx, domain.NewWidget{Name: "sprocket", Color: "red"})
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
		if category := domain.CategoryOf(err); category != domain.CategoryNotFound {
			t.Errorf("Get error category = %q, want %q", category, domain.CategoryNotFound)
		}
	})
}

func TestListWidgetsIsOrderedOldestFirst(t *testing.T) {
	widgets := newWidgets(t)
	ctx := t.Context()

	for _, name := range []string{"first", "second", "third"} {
		if _, err := widgets.Create(ctx, domain.NewWidget{Name: name, Color: "red"}); err != nil {
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
	// A nil slice serializes as JSON null; an empty one as []. The API contract
	// promises a list, so this must not regress.
	got, err := newWidgets(t).List(t.Context())
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

func TestWidgetOperationsRespectContextCancellation(t *testing.T) {
	widgets := newWidgets(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if _, err := widgets.List(ctx); err == nil {
		t.Error("List on a cancelled context succeeded, want an error")
	}
	if _, err := widgets.Get(ctx, "any"); err == nil {
		t.Error("Get on a cancelled context succeeded, want an error")
	}
	if _, err := widgets.Create(ctx, domain.NewWidget{Name: "x", Color: "red"}); err == nil {
		t.Error("Create on a cancelled context succeeded, want an error")
	}
}
