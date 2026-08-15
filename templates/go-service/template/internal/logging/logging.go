// Package logging builds the service logger.
//
// Two tiers, selected by logging.format:
//
//	console — colorized, one line per event, for a human at a terminal (default
//	          when env is local)
//	json    — one JSON object per line, for an aggregator
//
// The contract with the outside world is the set of field NAMES, not the bytes.
// An aggregator parses JSON; it does not care about key order or whitespace.
// Every line carries: timestamp, level, msg, service, service_version, env.
// Request-scoped lines add request_id.
//
// A line emitted inside a span also carries trace_id and span_id. They are
// taken from the active span on the context and omitted entirely when there is
// none — never empty and never fabricated, because an empty trace_id looks like
// a trace that exists and cannot be found. That is why the logger is reached
// through the context (see FromContext) and why call sites use the *Context
// variants of slog's methods.
package logging

import (
	"context"
	"io"
	"log/slog"
	"os"
	"strings"
	"time"

	"github.com/lmittmann/tint"
	"go.opentelemetry.io/otel/trace"
)

// Reserved field names. Call sites cannot override these; they are set once,
// on the logger, at startup.
const (
	KeyTime           = "timestamp"
	KeyLevel          = "level"
	KeyMessage        = "msg"
	KeyService        = "service"
	KeyServiceVersion = "service_version"
	KeyEnv            = "env"
	KeyRequestID      = "request_id"
	KeyTraceID        = "trace_id"
	KeySpanID         = "span_id"
)

// TimeFormat is the timestamp layout in the console tier. The JSON tier uses
// RFC 3339 with milliseconds.
const TimeFormat = "15:04:05.000"

// Options configure the logger.
type Options struct {
	Level          string // debug, info, warn, error
	Format         string // console, json
	Service        string
	ServiceVersion string
	Env            string
	// Output defaults to os.Stdout.
	Output io.Writer
}

// New builds the root logger. It never fails: an unrecognised level falls back
// to info, because losing all logging is a worse outcome than logging too much,
// and config.Validate has already rejected a bad value before this is reached.
func New(opts Options) *slog.Logger {
	out := opts.Output
	if out == nil {
		out = os.Stdout
	}

	var handler slog.Handler
	if opts.Format == "json" {
		handler = slog.NewJSONHandler(out, &slog.HandlerOptions{
			Level:       parseLevel(opts.Level),
			ReplaceAttr: replaceAttr(true),
		})
	} else {
		// tint's defaults are "Aug 14 18:42:27.231" and "INF"; both are
		// overridden here to match the reserved-field contract.
		handler = tint.NewTextHandler(out, &tint.Options{
			Level:      parseLevel(opts.Level),
			TimeFormat: TimeFormat,
			NoColor:    !isTerminal(out),
			// tint renders the timestamp itself, so the time key is left alone.
			ReplaceAttr: replaceAttr(false),
		})
	}

	return slog.New(&traceHandler{Handler: handler}).With(
		slog.String(KeyService, opts.Service),
		slog.String(KeyServiceVersion, opts.ServiceVersion),
		slog.String(KeyEnv, opts.Env),
	)
}

// traceHandler adds trace_id and span_id from the active span.
//
// Doing it in the handler rather than at call sites is what makes the
// correlation automatic: any code that logs with a context gets the fields, and
// no call site can forget them.
//
// **The fields are omitted entirely when there is no span** — never empty,
// never fabricated. An empty trace_id in an aggregator is worse than an absent
// one: it looks like a trace that exists and cannot be found.
type traceHandler struct{ slog.Handler }

func (h *traceHandler) Handle(ctx context.Context, record slog.Record) error {
	if spanCtx := trace.SpanContextFromContext(ctx); spanCtx.IsValid() {
		record.AddAttrs(
			slog.String(KeyTraceID, spanCtx.TraceID().String()),
			slog.String(KeySpanID, spanCtx.SpanID().String()),
		)
	}
	return h.Handler.Handle(ctx, record)
}

func (h *traceHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return &traceHandler{Handler: h.Handler.WithAttrs(attrs)}
}

func (h *traceHandler) WithGroup(name string) slog.Handler {
	return &traceHandler{Handler: h.Handler.WithGroup(name)}
}

// replaceAttr maps slog's built-in keys onto the shared field names, renders
// the level in the shared vocabulary, and renders durations readably.
//
// renameTime is false for the console tier, where tint formats the timestamp
// itself.
func replaceAttr(renameTime bool) func([]string, slog.Attr) slog.Attr {
	return func(groups []string, a slog.Attr) slog.Attr {
		// A duration is an int64 of nanoseconds. Logging it raw produces
		// "timeout":15000000000, which nothing reads well. Converting here
		// rather than at call sites means no call site can get it wrong.
		if a.Value.Kind() == slog.KindDuration {
			return slog.String(a.Key, a.Value.Duration().String())
		}
		if len(groups) > 0 {
			return a
		}
		switch a.Key {
		case slog.TimeKey:
			if renameTime {
				return slog.String(KeyTime, a.Value.Time().Format(time.RFC3339Nano))
			}
		case slog.LevelKey:
			return slog.String(KeyLevel, levelString(a.Value))
		}
		return a
	}
}

// levelString renders a level in the vocabulary every minted service shares:
// debug, info, warn, error.
func levelString(v slog.Value) string {
	if lvl, ok := v.Any().(slog.Level); ok {
		return strings.ToLower(lvl.String())
	}
	return strings.ToLower(v.String())
}

func parseLevel(name string) slog.Level {
	switch strings.ToLower(name) {
	case "debug":
		return slog.LevelDebug
	case "warn":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func isTerminal(w io.Writer) bool {
	if os.Getenv("NO_COLOR") != "" {
		return false
	}
	f, ok := w.(*os.File)
	if !ok {
		return false
	}
	info, err := f.Stat()
	if err != nil {
		return false
	}
	return info.Mode()&os.ModeCharDevice != 0
}

type contextKey struct{}

// NewContext returns a context carrying logger.
func NewContext(ctx context.Context, logger *slog.Logger) context.Context {
	return context.WithValue(ctx, contextKey{}, logger)
}

// FromContext returns the logger stored on ctx, or the default logger. Using
// this rather than a package-level logger is what lets a request-scoped field
// like request_id — and later trace_id — appear on every line a handler emits
// without threading a logger argument through every function.
func FromContext(ctx context.Context) *slog.Logger {
	return FromContextOr(ctx, slog.Default())
}

// FromContextOr is FromContext with an explicit fallback, for callers that run
// outside the request-scoped part of the middleware chain and would otherwise
// silently drop to the default logger — losing service, service_version and env
// from the very lines that most need them.
func FromContextOr(ctx context.Context, fallback *slog.Logger) *slog.Logger {
	if logger, ok := ctx.Value(contextKey{}).(*slog.Logger); ok {
		return logger
	}
	return fallback
}
