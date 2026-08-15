package http

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"

	"github.com/jeffmgreg/widget-svc/internal/logging"
)

// RequestIDHeader carries the request correlation ID in and out.
const RequestIDHeader = "X-Request-Id"

// Middleware is the shape of every entry in the chain.
type Middleware func(http.Handler) http.Handler

// Chain applies middleware so that the first argument is the outermost.
//
// The order is fixed and deliberate:
//
//	recovery -> request-id -> [tracing] -> [metrics] -> logging -> [auth] -> timeout -> handler
//
// Bracketed entries are not built yet. Their positions are what matters:
//
//   - tracing and metrics sit outside logging so a log line can carry the
//     trace ID that the tracing middleware put on the context.
//   - auth sits INSIDE logging and metrics — observe everything, then
//     authorize, then execute. An access log that omits rejected requests is a
//     success log; it cannot answer "401s are spiking, from where?". The
//     accepted cost is that an unauthenticated flood drives log volume.
//   - auth sits OUTSIDE timeout, because the request deadline is the handler's
//     budget, not the authorizer's.
func Chain(h http.Handler, middleware ...Middleware) http.Handler {
	for i := len(middleware) - 1; i >= 0; i-- {
		h = middleware[i](h)
	}
	return h
}

// routeBox lets an inner layer report the matched route template back to an
// outer one. The outer middleware runs before routing, so it cannot know the
// template; the box is placed on the context on the way in and filled by the
// huma middleware on the way through.
//
// The route template — not the concrete path — is what the access log records
// and what a metrics label will use, so that /widgets/abc and /widgets/def are
// one series rather than two.
type routeBox struct{ pattern string }

type routeBoxKey struct{}

func withRouteBox(ctx context.Context, box *routeBox) context.Context {
	return context.WithValue(ctx, routeBoxKey{}, box)
}

func routeBoxFrom(ctx context.Context) *routeBox {
	box, _ := ctx.Value(routeBoxKey{}).(*routeBox)
	return box
}

// SetRoute records the matched route template for the current request, if
// anything is listening. Safe to call when nothing is.
func SetRoute(ctx context.Context, pattern string) {
	if box := routeBoxFrom(ctx); box != nil {
		box.pattern = pattern
	}
}

type requestIDKey struct{}

type pathKey struct{}

// RequestIDFrom returns the correlation ID for the current request.
func RequestIDFrom(ctx context.Context) string {
	id, _ := ctx.Value(requestIDKey{}).(string)
	return id
}

// PathFrom returns the concrete request path, which RFC 9457 error bodies
// report as "instance".
func PathFrom(ctx context.Context) string {
	path, _ := ctx.Value(pathKey{}).(string)
	return path
}

// Recovery turns a panic into a 500 problem+json response and keeps the
// process alive. It is outermost so it covers every other layer.
func Recovery(logger *slog.Logger) Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				recovered := recover()
				if recovered == nil {
					return
				}
				// http.ErrAbortHandler is the documented way to abort a
				// response; it is not a bug and must not be logged as one.
				if err, ok := recovered.(error); ok && errors.Is(err, http.ErrAbortHandler) {
					panic(recovered)
				}
				// Recovery is outermost, so on most paths there is no
				// request-scoped logger on the context yet. Falling back to
				// the logger this middleware was built with keeps the service
				// fields on the line; slog.Default() would not.
				logging.FromContextOr(r.Context(), logger).ErrorContext(r.Context(),
					"panic recovered",
					slog.Any("panic", recovered),
					slog.String("stack", stack()),
				)
				writeProblem(w, r, http.StatusInternalServerError, "Internal Server Error", "an unexpected error occurred")
			}()
			next.ServeHTTP(w, r)
		})
	}
}

// RequestContext seeds the per-request context: a correlation ID, reusing an
// inbound one so a caller's ID survives the hop and echoing it on the response,
// and the request path, which error bodies report as "instance".
//
// These are set together, in one place, because everything downstream — the
// access log, the error writer, and later the tracing middleware — expects them
// to be present on any request that has been routed at all.
func RequestContext() Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			id := r.Header.Get(RequestIDHeader)
			if id == "" {
				id = uuid.NewString()
			}
			w.Header().Set(RequestIDHeader, id)

			ctx := context.WithValue(r.Context(), requestIDKey{}, id)
			ctx = context.WithValue(ctx, pathKey{}, r.URL.Path)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// Logging emits one structured line per request and puts a request-scoped
// logger on the context, so anything a handler logs carries the same
// request_id without being passed a logger.
func Logging(logger *slog.Logger) Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()

			ctx := r.Context()
			scoped := logger.With(slog.String(logging.KeyRequestID, RequestIDFrom(ctx)))
			ctx = logging.NewContext(ctx, scoped)

			box := &routeBox{}
			ctx = withRouteBox(ctx, box)

			recorder := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(recorder, r.WithContext(ctx))

			route := box.pattern
			if route == "" {
				// Nothing claimed a template: either the request 404'd before
				// reaching a route, or it hit a handler registered on a fixed
				// path, where path and template are the same thing.
				route = r.URL.Path
			}

			scoped.LogAttrs(ctx, levelFor(recorder.status), "request",
				slog.String("method", r.Method),
				slog.String("route", route),
				slog.String("path", r.URL.Path),
				slog.Int("status", recorder.status),
				slog.Int64("duration_ms", time.Since(start).Milliseconds()),
			)
		})
	}
}

// Timeout gives each request a context deadline and propagates it downward.
//
// This deliberately does not use http.TimeoutHandler, which writes a plain-text
// body and would break the problem+json contract. Handlers observe ctx.Done();
// the server's WriteTimeout is the hard backstop for one that does not.
func Timeout(d time.Duration) Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ctx, cancel := context.WithTimeout(r.Context(), d)
			defer cancel()
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func levelFor(status int) slog.Level {
	switch {
	case status >= 500:
		return slog.LevelError
	case status >= 400:
		return slog.LevelWarn
	default:
		return slog.LevelInfo
	}
}

// statusRecorder captures the response status for the access log. Unwrap keeps
// http.ResponseController working for anything that needs flushing or
// hijacking further down.
type statusRecorder struct {
	http.ResponseWriter
	status  int
	written bool
}

func (s *statusRecorder) WriteHeader(status int) {
	if !s.written {
		s.status = status
		s.written = true
	}
	s.ResponseWriter.WriteHeader(status)
}

func (s *statusRecorder) Write(b []byte) (int, error) {
	s.written = true
	return s.ResponseWriter.Write(b)
}

func (s *statusRecorder) Unwrap() http.ResponseWriter { return s.ResponseWriter }
