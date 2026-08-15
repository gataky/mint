package http

import (
	"net/http"
	"strings"
)

// UnmatchedRoute is the route label used when a request matched no registered
// route.
//
// It exists to bound cardinality. Labelling an unrouted request with its
// concrete path would let anyone create unbounded series by sending requests to
// random URLs.
const UnmatchedRoute = "<unmatched>"

// RouteResolver reports the route template a request will be dispatched to,
// before it is dispatched.
//
// Resolving up front — rather than having the router report the template on the
// way back out — is what lets the in-flight gauge be labelled with the route it
// is holding open, and lets the access log and the metrics agree on one value.
type RouteResolver func(*http.Request) string

// MuxResolver resolves routes by asking the mux itself, which is the same
// lookup ServeMux performs when it dispatches.
func MuxResolver(mux *http.ServeMux) RouteResolver {
	return func(r *http.Request) string {
		_, pattern := mux.Handler(r)
		return routeTemplate(pattern)
	}
}

// routeTemplate turns a registered ServeMux pattern into a route label.
//
// Go 1.22 patterns may carry a method ("GET /widgets/{id}") and may end in the
// exact-match marker ("/healthz{$}"); neither belongs in the label.
func routeTemplate(pattern string) string {
	if pattern == "" {
		return UnmatchedRoute
	}

	// Strip a leading method. The space separates it from the path, and a
	// pattern with no method has no space.
	if method, rest, found := strings.Cut(pattern, " "); found {
		_ = method
		pattern = rest
	}
	pattern = strings.TrimSpace(pattern)
	pattern = strings.TrimSuffix(pattern, "{$}")

	// A bare "/" is the catch-all both muxes register to return problem+json
	// for an unrouted request. A genuine root route would be registered as
	// "/{$}", so this is unambiguous.
	if pattern == "/" {
		return UnmatchedRoute
	}
	if pattern == "" {
		return UnmatchedRoute
	}
	return pattern
}
