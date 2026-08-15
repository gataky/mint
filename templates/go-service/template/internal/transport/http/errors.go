package http

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"runtime"

	"github.com/danielgtaylor/huma/v2"

	"{@ module_path @}/internal/domain"
	"{@ module_path @}/internal/logging"
)

// ProblemContentType is the RFC 9457 media type. Every error response uses it.
const ProblemContentType = "application/problem+json"

// DefaultProblemType is RFC 9457's default when an error has no documentation
// URI of its own. It is written explicitly rather than omitted so that every
// service minted from this template produces byte-comparable error bodies.
const DefaultProblemType = "about:blank"

// statusFor maps the domain's error taxonomy onto HTTP. This table is the
// transport's business; the service layer never names a status code.
func statusFor(category domain.Category) int {
	switch category {
	case domain.CategoryInvalid:
		return http.StatusBadRequest
	case domain.CategoryNotFound:
		return http.StatusNotFound
	case domain.CategoryConflict:
		return http.StatusConflict
	case domain.CategoryUnauthorized:
		return http.StatusUnauthorized
	case domain.CategoryForbidden:
		return http.StatusForbidden
	default:
		return http.StatusInternalServerError
	}
}

// problem converts a domain error into the error huma will serialize.
//
// A driver error, a wrapped cause, or a stack trace never crosses this
// boundary: the detail is logged here and the client is told the category.
func problem(ctx context.Context, err error) error {
	category := domain.CategoryOf(err)
	status := statusFor(category)

	// A blown request deadline is a timeout, not an internal failure. The
	// Python template returns 504 here because asyncio cancels the task
	// outright; reporting the same status keeps every minted service agreeing
	// on a case a client actually retries on.
	if errors.Is(err, context.DeadlineExceeded) {
		return &huma.ErrorModel{
			Type:     DefaultProblemType,
			Title:    http.StatusText(http.StatusGatewayTimeout),
			Status:   http.StatusGatewayTimeout,
			Detail:   "request exceeded its deadline",
			Instance: PathFrom(ctx),
		}
	}

	message := "an unexpected error occurred"
	if category == domain.CategoryInternal {
		// The cause is recorded here and goes no further. Driver errors and
		// stack traces never cross this boundary: log the detail, return the
		// category.
		logging.FromContext(ctx).ErrorContext(ctx, "request failed",
			slog.String("error", err.Error()),
			slog.String("category", string(category)),
		)
	} else {
		message = err.Error()
		var domainErr *domain.Error
		if errors.As(err, &domainErr) {
			message = domainErr.Message
		}
	}

	// huma writes a returned StatusError verbatim rather than routing it
	// through NewErrorWithContext, so type and instance are filled in here.
	// Skipping this is how an error body ends up shaped differently from the
	// ones huma generates itself for validation failures.
	return &huma.ErrorModel{
		Type:     DefaultProblemType,
		Title:    http.StatusText(status),
		Status:   status,
		Detail:   message,
		Instance: PathFrom(ctx),
	}
}

// problemBody is the wire shape of an error. It matches huma.ErrorModel field
// for field, and every service minted from this template emits the same
// object.
type problemBody struct {
	Type     string `json:"type"`
	Title    string `json:"title"`
	Status   int    `json:"status"`
	Detail   string `json:"detail,omitempty"`
	Instance string `json:"instance,omitempty"`
}

// writeProblem emits an error response directly, for the paths that never
// reach huma: a panic, or a request that misses every route.
func writeProblem(w http.ResponseWriter, r *http.Request, status int, title, detail string) {
	w.Header().Set("Content-Type", ProblemContentType)
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(problemBody{
		Type:     DefaultProblemType,
		Title:    title,
		Status:   status,
		Detail:   detail,
		Instance: r.URL.Path,
	})
}

func stack() string {
	buf := make([]byte, 8<<10)
	n := runtime.Stack(buf, false)
	return string(buf[:n])
}
