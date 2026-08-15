// Package config is the only place in the service that reads environment
// variables or files. Everything else receives a *Config.
//
// Precedence, lowest to highest:
//
//	built-in defaults  <  config/config.yaml  <  config/config.local.yaml  <  environment
//
// Environment variables are named MINT_ + the config path upper-cased, with
// "__" between levels and the key's own underscores preserved:
//
//	server.read_timeout  ->  MINT_SERVER__READ_TIMEOUT
//	logging.format       ->  MINT_LOGGING__FORMAT
//
// Single-underscore nesting is deliberately not used: it cannot distinguish
// server.read_timeout from server.read.timeout. The constant MINT_ prefix is
// deliberate too — Kubernetes injects {SVCNAME}_PORT into every pod, so a
// service-name prefix would collide with it.
package config

import (
	"errors"
	"fmt"
	"os"
	"slices"
	"strings"
	"time"

	"github.com/knadh/koanf/parsers/yaml"
	"github.com/knadh/koanf/providers/env/v2"
	"github.com/knadh/koanf/providers/file"
	"github.com/knadh/koanf/providers/structs"
	"github.com/knadh/koanf/v2"
)

// EnvPrefix is the required prefix on every configuration environment variable.
const EnvPrefix = "MINT_"

const (
	otlpEndpointKey = "observability.tracing.otlp_endpoint"

	// otlpEndpointEnv is the single exception to the MINT_ prefix rule. It is
	// enumerated explicitly — never read as a wildcard OTEL_* lookup — so that
	// every value reaching the config still has one named source.
	otlpEndpointEnv = "OTEL_EXPORTER_OTLP_ENDPOINT"
)

// Config is the whole of the service's configuration.
type Config struct {
	Env           string        `koanf:"env"`
	Service       Service       `koanf:"service"`
	Server        Server        `koanf:"server"`
	Logging       Logging       `koanf:"logging"`
	Observability Observability `koanf:"observability"`
}

// Observability configures tracing. Metrics need no configuration: they are
// always collected and always served on the admin port.
type Observability struct {
	Tracing Tracing `koanf:"tracing"`
}

// Tracing configures the OpenTelemetry tracer provider.
type Tracing struct {
	// Enabled turns span creation off entirely. When false there is no trace
	// context, so log lines carry no trace_id.
	Enabled bool `koanf:"enabled"`

	// OTLPEndpoint is the collector to export to, e.g. http://localhost:4318.
	// Empty installs a no-op exporter: spans are still created, so logs still
	// correlate, but nothing leaves the process and a fresh `make run` emits no
	// connection-refused retries.
	OTLPEndpoint string `koanf:"otlp_endpoint"`

	// SampleRatio is the head sampling ratio, 0.0 to 1.0, applied only to
	// traces this service starts. A sampling decision made upstream is
	// respected.
	SampleRatio float64 `koanf:"sample_ratio"`
}

// Service identifies this service to logs, traces and metrics.
type Service struct {
	Name    string `koanf:"name"`
	Version string `koanf:"version"`
	Owner   string `koanf:"owner"`
}

// Server holds the HTTP listener settings. Every timeout is non-zero by
// default: a zero ReadHeaderTimeout is a slowloris vector.
type Server struct {
	Port      int `koanf:"port"`
	AdminPort int `koanf:"admin_port"`

	ReadHeaderTimeout time.Duration `koanf:"read_header_timeout"`
	ReadTimeout       time.Duration `koanf:"read_timeout"`
	WriteTimeout      time.Duration `koanf:"write_timeout"`
	IdleTimeout       time.Duration `koanf:"idle_timeout"`

	// RequestTimeout is the per-request context deadline handlers work against.
	RequestTimeout time.Duration `koanf:"request_timeout"`
	// ShutdownTimeout bounds the drain on SIGTERM.
	ShutdownTimeout time.Duration `koanf:"shutdown_timeout"`
}

// Logging selects the log tier and verbosity.
type Logging struct {
	// Level is one of debug, info, warn, error.
	Level string `koanf:"level"`
	// Format is "console" (tier 1, colorized, for humans) or "json" (tier 2).
	Format string `koanf:"format"`
}

// Valid values, exported so validation messages and tests share one list.
var (
	ValidEnvs    = []string{"local", "dev", "staging", "prod"}
	ValidLevels  = []string{"debug", "info", "warn", "error"}
	ValidFormats = []string{"console", "json"}
)

// Defaults returns a Config that boots with no configuration at all.
func Defaults() Config {
	return Config{
		Env: "local",
		Service: Service{
			Name:    "widget-svc",
			Version: "0.1.0",
			Owner:   "unowned",
		},
		Server: Server{
			Port:              8080,
			AdminPort:         9080,
			ReadHeaderTimeout: 5 * time.Second,
			ReadTimeout:       15 * time.Second,
			WriteTimeout:      15 * time.Second,
			IdleTimeout:       60 * time.Second,
			RequestTimeout:    10 * time.Second,
			ShutdownTimeout:   15 * time.Second,
		},
		Logging: Logging{
			Level:  "info",
			Format: "console",
		},
		Observability: Observability{
			Tracing: Tracing{
				Enabled:      true,
				OTLPEndpoint: "",
				SampleRatio:  1.0,
			},
		},
	}
}

// Loaded is a Config plus a record of which source supplied each key, so
// `--print-config` can explain itself.
type Loaded struct {
	Config  Config
	sources map[string]string
}

// Load reads the configuration from defaults, then each YAML file that exists,
// then the environment. Missing files are not an error: the service is meant to
// boot with none of them.
func Load(files ...string) (*Loaded, error) {
	k := koanf.New(".")
	sources := map[string]string{}

	// Layer 1: built-in defaults.
	defaults := koanf.New(".")
	if err := defaults.Load(structs.Provider(Defaults(), "koanf"), nil); err != nil {
		return nil, fmt.Errorf("load defaults: %w", err)
	}
	if err := k.Merge(defaults); err != nil {
		return nil, fmt.Errorf("merge defaults: %w", err)
	}
	for _, key := range defaults.Keys() {
		sources[key] = "default"
	}

	// Layer 2: YAML files, in the order given, each overlaying the last.
	for _, path := range files {
		if _, err := os.Stat(path); errors.Is(err, os.ErrNotExist) {
			continue
		}
		layer := koanf.New(".")
		if err := layer.Load(file.Provider(path), yaml.Parser()); err != nil {
			return nil, fmt.Errorf("load %s: %w", path, err)
		}
		if err := k.Merge(layer); err != nil {
			return nil, fmt.Errorf("merge %s: %w", path, err)
		}
		for _, key := range layer.Keys() {
			sources[key] = path
		}
	}

	// Layer 3: the environment, which wins.
	envLayer := koanf.New(".")
	envNames := map[string]string{}
	err := envLayer.Load(env.Provider(".", env.Opt{
		Prefix: EnvPrefix,
		TransformFunc: func(name, value string) (string, any) {
			key := strings.ToLower(strings.TrimPrefix(name, EnvPrefix))
			key = strings.ReplaceAll(key, "__", ".")
			envNames[key] = name
			return key, value
		},
	}), nil)
	if err != nil {
		return nil, fmt.Errorf("load environment: %w", err)
	}
	if err := k.Merge(envLayer); err != nil {
		return nil, fmt.Errorf("merge environment: %w", err)
	}
	for _, key := range envLayer.Keys() {
		sources[key] = "env:" + envNames[key]
	}

	// Layer 3b: the one ecosystem variable this service honours.
	//
	// Mint defers on OTLP *transport* and owns *identity*: OTEL_SERVICE_NAME
	// and OTEL_RESOURCE_ATTRIBUTES are deliberately ignored, because logs and
	// spans disagreeing about `service` or `env` would break the error-to-trace
	// path. Reading it here rather than in the observability package keeps the
	// one-reader rule and keeps `make config` honest about where a value came
	// from.
	//
	// "Unset" means empty, not absent: the defaults layer always supplies this
	// key, so k.Exists is true even when nobody has chosen a value.
	if k.String(otlpEndpointKey) == "" {
		if endpoint := os.Getenv(otlpEndpointEnv); endpoint != "" {
			if err := k.Set(otlpEndpointKey, endpoint); err != nil {
				return nil, fmt.Errorf("apply %s: %w", otlpEndpointEnv, err)
			}
			sources[otlpEndpointKey] = "env:" + otlpEndpointEnv
		}
	}

	var cfg Config
	if err := k.Unmarshal("", &cfg); err != nil {
		return nil, fmt.Errorf("decode config: %w", err)
	}
	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	return &Loaded{Config: cfg, sources: sources}, nil
}

// Validate reports every invalid field at once rather than stopping at the
// first, so a misconfigured deploy is fixed in one pass instead of four.
func (c Config) Validate() error {
	var problems []error

	if !slices.Contains(ValidEnvs, c.Env) {
		problems = append(problems, fmt.Errorf("env: %q is not one of %s", c.Env, strings.Join(ValidEnvs, ", ")))
	}
	if c.Service.Name == "" {
		problems = append(problems, errors.New("service.name: must not be empty"))
	}
	if !slices.Contains(ValidLevels, c.Logging.Level) {
		problems = append(problems, fmt.Errorf("logging.level: %q is not one of %s", c.Logging.Level, strings.Join(ValidLevels, ", ")))
	}
	if !slices.Contains(ValidFormats, c.Logging.Format) {
		problems = append(problems, fmt.Errorf("logging.format: %q is not one of %s", c.Logging.Format, strings.Join(ValidFormats, ", ")))
	}
	for _, p := range []struct {
		name  string
		value int
	}{{"server.port", c.Server.Port}, {"server.admin_port", c.Server.AdminPort}} {
		if p.value < 1024 || p.value > 65535 {
			problems = append(problems, fmt.Errorf("%s: %d is outside 1024-65535", p.name, p.value))
		}
	}
	for _, d := range []struct {
		name  string
		value time.Duration
	}{
		{"server.read_header_timeout", c.Server.ReadHeaderTimeout},
		{"server.read_timeout", c.Server.ReadTimeout},
		{"server.write_timeout", c.Server.WriteTimeout},
		{"server.idle_timeout", c.Server.IdleTimeout},
		{"server.request_timeout", c.Server.RequestTimeout},
		{"server.shutdown_timeout", c.Server.ShutdownTimeout},
	} {
		if d.value <= 0 {
			problems = append(problems, fmt.Errorf("%s: must be greater than zero", d.name))
		}
	}

	if ratio := c.Observability.Tracing.SampleRatio; ratio < 0 || ratio > 1 {
		problems = append(problems, fmt.Errorf("observability.tracing.sample_ratio: %v is outside 0.0-1.0", ratio))
	}

	if len(problems) == 0 {
		return nil
	}
	return fmt.Errorf("invalid configuration:\n  - %s", strings.Join(messages(problems), "\n  - "))
}

func messages(errs []error) []string {
	out := make([]string, len(errs))
	for i, err := range errs {
		out[i] = err.Error()
	}
	return out
}

// SplitListeners reports whether the API and admin servers need separate
// listeners. Setting admin_port equal to port collapses them onto one.
func (c Config) SplitListeners() bool {
	return c.Server.Port != c.Server.AdminPort
}
