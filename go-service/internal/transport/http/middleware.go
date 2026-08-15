package http

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

	"github.com/jeffmgreg/widget-svc/internal/logging"
	"github.com/jeffmgreg/widget-svc/internal/observability"
)

// RequestIDHeader carries the request correlation ID in and out.
const RequestIDHeader = "X-Request-Id"

// Middleware is the shape of every entry in the chain.
type Middleware func(http.Handler) http.Handler

// Chain applies middleware so that the first argument is the outermost.
//
// The order is fixed and deliberate:
//
//	recovery -> request-id -> [tracing] -> metrics -> logging -> [auth] -> timeout -> handler
//
// Bracketed entries are not built yet. Their positions are what matters:
//
//   - tracing sits outside metrics and logging so both can carry the trace ID
//     it put on the context, and so a span covers the whole request.
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

// Tracing starts a server span per request and extracts any inbound trace
// context, so a trace begun by a caller continues here rather than restarting.
//
// otelhttp does the W3C extraction, the semantic-convention attributes and the
// status mapping. What it cannot do on its own is name the span usefully: its
// default is the handler name it was given, which would be one value for every
// route. The span name is the route template, which is the convention
// (`{method} {route}`) and matches the metrics label.
func Tracing(service string, resolve RouteResolver) Middleware {
	return func(next http.Handler) http.Handler {
		return otelhttp.NewHandler(next, service,
			otelhttp.WithSpanNameFormatter(func(_ string, r *http.Request) string {
				return r.Method + " " + resolve(r)
			}),
			// Health checks and scrapes would otherwise be most of the spans.
			otelhttp.WithFilter(func(r *http.Request) bool {
				switch r.URL.Path {
				case "/healthz", "/readyz", "/metrics":
					return false
				default:
					return true
				}
			}),
		)
	}
}

// Metrics records the three HTTP server metrics.
//
// It sits outside Logging so that both observe the same requests, and inside
// tracing so a future exemplar can carry the trace ID.
func Metrics(m *observability.Metrics, resolve RouteResolver) Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()

			// The in-flight gauge is labelled by method alone; the route is
			// resolved for the counter and histogram below.
			m.RequestStarted(r.Method)

			recorder := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
			// The gauge must come down even if the handler panics; Recovery is
			// outside this middleware and would otherwise leak the increment.
			defer func() {
				m.RequestFinished(r.Method, resolve(r), recorder.status, time.Since(start))
			}()

			next.ServeHTTP(recorder, r)
		})
	}
}

// Logging emits one structured line per request and puts a request-scoped
// logger on the context, so anything a handler logs carries the same
// request_id without being passed a logger.
func Logging(logger *slog.Logger, resolve RouteResolver) Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()

			ctx := r.Context()
			scoped := logger.With(slog.String(logging.KeyRequestID, RequestIDFrom(ctx)))
			ctx = logging.NewContext(ctx, scoped)

			recorder := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(recorder, r.WithContext(ctx))

			// route is the template and path is what was actually asked for.
			// Both are logged: the template is what you group by, the path is
			// what you need when reading one line.
			scoped.LogAttrs(ctx, levelFor(recorder.status), "request",
				slog.String("method", r.Method),
				slog.String("route", resolve(r)),
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
