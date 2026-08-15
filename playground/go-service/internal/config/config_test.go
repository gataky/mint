package config

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"
)

// writeYAML writes a config file into a temp dir and returns its path.
func writeYAML(t *testing.T, name, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("write %s: %v", name, err)
	}
	return path
}

func TestLoadWithNoSourcesUsesDefaults(t *testing.T) {
	// The service must boot with no config file and no environment at all.
	loaded, err := Load("does-not-exist.yaml")
	if err != nil {
		t.Fatalf("Load with no sources failed: %v", err)
	}

	want := Defaults()
	if loaded.Config != want {
		t.Errorf("Load() = %+v, want the defaults %+v", loaded.Config, want)
	}
}

func TestEnvironmentBeatsYAML(t *testing.T) {
	path := writeYAML(t, "config.yaml", "logging:\n  level: info\n")
	t.Setenv("MINT_LOGGING__LEVEL", "debug")

	loaded, err := Load(path)
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	if got := loaded.Config.Logging.Level; got != "debug" {
		t.Errorf("logging.level = %q, want %q — the environment must beat YAML", got, "debug")
	}
}

func TestLaterYAMLFileBeatsEarlier(t *testing.T) {
	base := writeYAML(t, "config.yaml", "logging:\n  level: info\n  format: console\n")
	local := writeYAML(t, "config.local.yaml", "logging:\n  level: debug\n")

	loaded, err := Load(base, local)
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	if got := loaded.Config.Logging.Level; got != "debug" {
		t.Errorf("logging.level = %q, want %q — the local file must win", got, "debug")
	}
	// The local file said nothing about format, so the base file still holds.
	if got := loaded.Config.Logging.Format; got != "console" {
		t.Errorf("logging.format = %q, want %q — an absent key must not reset to the default", got, "console")
	}
}

func TestDoubleUnderscoreSeparatesLevels(t *testing.T) {
	// Single-underscore nesting cannot distinguish server.read_timeout from
	// server.read.timeout. The key's own underscores are preserved; only "__"
	// descends a level.
	t.Setenv("MINT_SERVER__READ_TIMEOUT", "42s")

	loaded, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	if got := loaded.Config.Server.ReadTimeout; got != 42*time.Second {
		t.Errorf("server.read_timeout = %v, want %v", got, 42*time.Second)
	}
}

func TestUnprefixedEnvironmentVariablesAreIgnored(t *testing.T) {
	// Kubernetes injects {SVCNAME}_PORT into every pod. Nothing without the
	// MINT_ prefix may reach the configuration.
	t.Setenv("PORT", "1234")
	t.Setenv("WIDGET_SVC_PORT", "tcp://10.0.162.149:8080")

	loaded, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	if got := loaded.Config.Server.Port; got != Defaults().Server.Port {
		t.Errorf("server.port = %d, want the default %d — an unprefixed variable leaked in", got, Defaults().Server.Port)
	}
}

func TestValidateReportsEveryProblemAtOnce(t *testing.T) {
	cfg := Defaults()
	cfg.Env = "bogus"
	cfg.Server.Port = 99
	cfg.Logging.Level = "chatty"
	cfg.Server.ReadTimeout = 0

	err := cfg.Validate()
	if err == nil {
		t.Fatal("Validate accepted a config with four invalid fields")
	}

	// Stopping at the first problem means four deploy-fix cycles instead of one.
	for _, want := range []string{"env", "server.port", "logging.level", "server.read_timeout"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("Validate error does not mention %q:\n%v", want, err)
		}
	}
}

func TestValidateAcceptsEveryDeclaredEnum(t *testing.T) {
	for _, env := range ValidEnvs {
		cfg := Defaults()
		cfg.Env = env
		if err := cfg.Validate(); err != nil {
			t.Errorf("Validate rejected env %q, which is in ValidEnvs: %v", env, err)
		}
	}
	for _, level := range ValidLevels {
		cfg := Defaults()
		cfg.Logging.Level = level
		if err := cfg.Validate(); err != nil {
			t.Errorf("Validate rejected logging.level %q, which is in ValidLevels: %v", level, err)
		}
	}
	for _, format := range ValidFormats {
		cfg := Defaults()
		cfg.Logging.Format = format
		if err := cfg.Validate(); err != nil {
			t.Errorf("Validate rejected logging.format %q, which is in ValidFormats: %v", format, err)
		}
	}
}

func TestInvalidConfigurationIsAStartupError(t *testing.T) {
	t.Setenv("MINT_ENV", "production") // the valid value is "prod"

	if _, err := Load(); err == nil {
		t.Fatal("Load accepted an invalid env; it must fail fast at startup")
	}
}

func TestPrintAnnotatesTheWinningSource(t *testing.T) {
	path := writeYAML(t, "config.yaml", "logging:\n  format: json\n")
	t.Setenv("MINT_LOGGING__LEVEL", "debug")

	loaded, err := Load(path)
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	var out bytes.Buffer
	if err := loaded.Print(&out); err != nil {
		t.Fatalf("Print failed: %v", err)
	}
	printed := out.String()

	for _, want := range []string{
		"logging.level",           // set by the environment
		"env:MINT_LOGGING__LEVEL", // ...and says so
		"logging.format",          // set by the file
		path,                      // ...and names it
		"# default",               // and untouched keys say that
	} {
		if !strings.Contains(printed, want) {
			t.Errorf("Print output does not contain %q:\n%s", want, printed)
		}
	}

	// Durations print readably, not as a nanosecond count.
	if !regexp.MustCompile(`server\.read_timeout\s+15s\s`).MatchString(printed) {
		t.Errorf("Print did not render server.read_timeout as \"15s\":\n%s", printed)
	}
}

func TestSplitListeners(t *testing.T) {
	cfg := Defaults()
	if !cfg.SplitListeners() {
		t.Error("SplitListeners() = false for the default ports, want true")
	}

	// Collapsing onto one listener must remain expressible.
	cfg.Server.AdminPort = cfg.Server.Port
	if cfg.SplitListeners() {
		t.Error("SplitListeners() = true when admin_port equals port, want false")
	}
}

func TestOTLPEndpointFallsBackToTheEcosystemVariable(t *testing.T) {
	// Mint defers on OTLP *transport*: an operator who has already set the
	// standard variable should not have to set a second one.
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")

	loaded, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	if got := loaded.Config.Observability.Tracing.OTLPEndpoint; got != "http://collector:4318" {
		t.Errorf("otlp_endpoint = %q, want the OTEL_ variable's value", got)
	}

	var out bytes.Buffer
	if err := loaded.Print(&out); err != nil {
		t.Fatalf("Print failed: %v", err)
	}
	// It still has to say where it came from.
	if !strings.Contains(out.String(), "env:OTEL_EXPORTER_OTLP_ENDPOINT") {
		t.Errorf("Print does not attribute the endpoint to OTEL_EXPORTER_OTLP_ENDPOINT:\n%s", out.String())
	}
}

func TestMintVariableBeatsTheEcosystemVariable(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://ecosystem:4318")
	t.Setenv("MINT_OBSERVABILITY__TRACING__OTLP_ENDPOINT", "http://explicit:4318")

	loaded, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	// The fallback is a fallback, not an override.
	if got := loaded.Config.Observability.Tracing.OTLPEndpoint; got != "http://explicit:4318" {
		t.Errorf("otlp_endpoint = %q, want the MINT_ variable to win", got)
	}
}

func TestServiceIdentityEnvironmentVariablesAreIgnored(t *testing.T) {
	// Mint owns identity. Logs and spans disagreeing about service or env would
	// break the error-to-trace path.
	t.Setenv("OTEL_SERVICE_NAME", "something-else")
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "service.name=something-else")

	loaded, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	if got := loaded.Config.Service.Name; got != Defaults().Service.Name {
		t.Errorf("service.name = %q, want the default %q", got, Defaults().Service.Name)
	}
}

func TestSampleRatioIsValidated(t *testing.T) {
	cfg := Defaults()
	cfg.Observability.Tracing.SampleRatio = 1.5

	if err := cfg.Validate(); err == nil {
		t.Error("Validate accepted a sample_ratio above 1.0")
	}
}
