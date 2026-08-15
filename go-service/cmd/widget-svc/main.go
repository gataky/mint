// Command widget-svc is the service entrypoint.
//
// This file is the composition root: it is the only place that decides what is
// wired to what. It contains no business logic and no HTTP handling — every
// other package is constructed here and knows nothing about how it was built.
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/jeffmgreg/widget-svc/internal/config"
	"github.com/jeffmgreg/widget-svc/internal/logging"
	"github.com/jeffmgreg/widget-svc/internal/observability"
	"github.com/jeffmgreg/widget-svc/internal/service"
	transport "github.com/jeffmgreg/widget-svc/internal/transport/http"
)

func main() {
	if err := run(); err != nil {
		// The logger may not exist yet, so startup failures go to stderr
		// directly. Fail fast and loudly.
		fmt.Fprintf(os.Stderr, "fatal: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	printConfig := flag.Bool("print-config", false, "print the effective configuration and exit")
	flag.Parse()

	// Startup order is fixed: config, then logging, then the service, then the
	// health registry, then the listeners. Nothing observable starts before
	// there is a logger to record it.
	loaded, err := config.Load("config/config.yaml", "config/config.local.yaml")
	if err != nil {
		return err
	}
	cfg := loaded.Config

	if *printConfig {
		return loaded.Print(os.Stdout)
	}

	logger := logging.New(logging.Options{
		Level:          cfg.Logging.Level,
		Format:         cfg.Logging.Format,
		Service:        cfg.Service.Name,
		ServiceVersion: cfg.Service.Version,
		Env:            cfg.Env,
	})
	slog.SetDefault(logger)

	// Signals are owned here, in one place, rather than by each server. Two
	// servers each installing their own handlers is how a process dies before
	// it drains.
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()

	// env, service and service_version are already on every line from the root
	// logger; repeating them here would emit a duplicate key.
	logger.InfoContext(ctx, "starting",
		slog.Bool("split_listeners", cfg.SplitListeners()),
	)

	if cfg.Env != "local" {
		// The middleware chain has a reserved, empty auth slot. Authentication
		// is expected at a gateway or mesh; this makes the deferral mechanical
		// rather than remembered.
		logger.WarnContext(ctx, "no authentication middleware is registered",
			slog.String("expectation", "authentication is handled by an upstream gateway or mesh"))
	}

	widgets := service.NewWidgets()
	health := transport.NewHealth()

	metrics, err := observability.NewMetrics(cfg)
	if err != nil {
		return fmt.Errorf("build metrics: %w", err)
	}

	apiMux := transport.NewAPI(cfg, widgets, logger)
	api := transport.Chain(
		apiMux,
		transport.Recovery(logger),
		transport.RequestContext(),
		// tracing belongs here, outside metrics and logging.
		transport.Metrics(metrics, transport.MuxResolver(apiMux)),
		transport.Logging(logger, transport.MuxResolver(apiMux)),
		// auth belongs here: after observation, before execution.
		transport.Timeout(cfg.Server.RequestTimeout),
	)

	// The admin surface is not instrumented, not access-logged, and not part of
	// the request-timeout budget: a readiness probe every second and a scrape
	// every fifteen would be most of both the log volume and the metrics.
	admin := transport.Chain(
		transport.NewAdmin(health, metrics),
		transport.Recovery(logger),
		transport.RequestContext(),
	)

	return transport.Serve(ctx, logger, cfg.Server, health, transport.Listeners(cfg, api, admin)...)
}
