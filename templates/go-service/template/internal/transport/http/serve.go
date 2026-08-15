package http

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"sync"

	"{@ module_path @}/internal/config"
)

// Listener is one named HTTP server to run.
type Listener struct {
	Name    string
	Addr    string
	Handler http.Handler
}

// Serve runs every listener until ctx is cancelled or one of them fails, then
// drains.
//
// It takes a slice rather than a fixed pair on purpose. Today that slice holds
// the API and admin servers, and holds one entry when admin_port equals port.
// Tomorrow it may hold a third. Owning the signal handling and the server
// construction in one place — rather than letting each server install its own
// handlers — is what keeps a second listener from racing the first on SIGTERM.
func Serve(ctx context.Context, logger *slog.Logger, cfg config.Server, health *Health, listeners ...Listener) error {
	if len(listeners) == 0 {
		return errors.New("no listeners configured")
	}

	servers := make([]*http.Server, len(listeners))
	bound := make([]net.Listener, len(listeners))
	var binder net.ListenConfig

	// Bind every port before serving any of them, so a port conflict is a
	// startup failure rather than a half-running service.
	for i, l := range listeners {
		socket, err := binder.Listen(ctx, "tcp", l.Addr)
		if err != nil {
			for _, opened := range bound[:i] {
				_ = opened.Close()
			}
			return fmt.Errorf("listen %s on %s: %w", l.Name, l.Addr, err)
		}
		bound[i] = socket
		servers[i] = &http.Server{
			Handler:           l.Handler,
			ReadHeaderTimeout: cfg.ReadHeaderTimeout,
			ReadTimeout:       cfg.ReadTimeout,
			WriteTimeout:      cfg.WriteTimeout,
			IdleTimeout:       cfg.IdleTimeout,
		}
	}

	failed := make(chan error, len(servers))
	var wg sync.WaitGroup
	for i, server := range servers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			logger.InfoContext(ctx, "listening",
				slog.String("listener", listeners[i].Name),
				slog.String("addr", bound[i].Addr().String()),
			)
			if err := server.Serve(bound[i]); err != nil && !errors.Is(err, http.ErrServerClosed) {
				failed <- fmt.Errorf("%s: %w", listeners[i].Name, err)
			}
		}()
	}

	var serveErr error
	select {
	case <-ctx.Done():
		logger.InfoContext(ctx, "shutdown signal received, draining",
			slog.Duration("timeout", cfg.ShutdownTimeout))
	case serveErr = <-failed:
		logger.ErrorContext(ctx, "listener failed", slog.String("error", serveErr.Error()))
	}

	// Fail readiness first. A load balancer needs to see /readyz go
	// unhealthy before connections stop being accepted, or it keeps routing
	// traffic into a closing socket.
	health.Drain()

	drainCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), cfg.ShutdownTimeout)
	defer cancel()

	var drainErr error
	for i, server := range servers {
		if err := server.Shutdown(drainCtx); err != nil {
			drainErr = errors.Join(drainErr, fmt.Errorf("drain %s: %w", listeners[i].Name, err))
		}
	}
	wg.Wait()

	// When tracing lands, the tracer provider is flushed here — after the
	// drain, before the process exits. Final-request spans are lost otherwise.

	if drainErr != nil {
		return drainErr
	}
	return serveErr
}

// Listeners returns the listeners to run for cfg. When admin_port equals port
// the two handlers collapse onto a single listener, which must keep working: it
// is how the service runs where only one port is available.
//
// Splitting them by default buys drain visibility, not security — any client
// that can reach the pod IP can reach every container port. Mid-drain, a split
// admin port still answers /readyz with 503 "draining" and still serves a final
// metrics scrape; collapsed onto one listener, both become connection-refused.
func Listeners(cfg config.Config, api, admin http.Handler) []Listener {
	if !cfg.SplitListeners() {
		mux := http.NewServeMux()
		mux.Handle("/healthz", admin)
		mux.Handle("/readyz", admin)
		mux.Handle("/", api)
		return []Listener{{
			Name:    "combined",
			Addr:    fmt.Sprintf(":%d", cfg.Server.Port),
			Handler: mux,
		}}
	}
	return []Listener{
		{Name: "api", Addr: fmt.Sprintf(":%d", cfg.Server.Port), Handler: api},
		{Name: "admin", Addr: fmt.Sprintf(":%d", cfg.Server.AdminPort), Handler: admin},
	}
}
