package domain

import (
	"errors"
	"fmt"
)

// Category is the domain's error taxonomy. The transport owns the mapping from
// category to HTTP status; the service layer never names a status code.
type Category string

const (
	CategoryInvalid      Category = "invalid"
	CategoryNotFound     Category = "not_found"
	CategoryConflict     Category = "conflict"
	CategoryUnauthorized Category = "unauthorized"
	CategoryForbidden    Category = "forbidden"
	CategoryInternal     Category = "internal"
)

// Error is a domain error: a category, a message safe to show a client, and an
// optional wrapped cause that is logged but never serialized.
type Error struct {
	Category Category
	Message  string
	cause    error
}

func (e *Error) Error() string {
	if e.cause != nil {
		return fmt.Sprintf("%s: %s: %v", e.Category, e.Message, e.cause)
	}
	return fmt.Sprintf("%s: %s", e.Category, e.Message)
}

func (e *Error) Unwrap() error { return e.cause }

// CategoryOf reports the category of err, defaulting to internal for anything
// that is not a domain error. An unexpected error is an internal one.
func CategoryOf(err error) Category {
	var domain *Error
	if errors.As(err, &domain) {
		return domain.Category
	}
	return CategoryInternal
}

// Invalid reports a request that is well-formed but violates a business rule.
func Invalid(format string, args ...any) *Error {
	return &Error{Category: CategoryInvalid, Message: fmt.Sprintf(format, args...)}
}

// NotFound reports a resource that does not exist.
func NotFound(format string, args ...any) *Error {
	return &Error{Category: CategoryNotFound, Message: fmt.Sprintf(format, args...)}
}

// Conflict reports a request that collides with existing state.
func Conflict(format string, args ...any) *Error {
	return &Error{Category: CategoryConflict, Message: fmt.Sprintf(format, args...)}
}

// Internal wraps an unexpected failure. The cause is logged; the client sees
// only a generic message.
func Internal(cause error, format string, args ...any) *Error {
	return &Error{Category: CategoryInternal, Message: fmt.Sprintf(format, args...), cause: cause}
}
