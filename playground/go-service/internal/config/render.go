package config

import (
	"fmt"
	"io"
	"slices"
	"text/tabwriter"

	"github.com/knadh/koanf/providers/structs"
	"github.com/knadh/koanf/v2"
)

// Print writes the effective configuration, one key per line, annotated with
// the source that supplied the winning value. This is what `make config` and
// `--print-config` show.
//
// Values are re-read from the decoded Config rather than from the raw merged
// layers, so a duration prints as "15s" whether it arrived as a Go default, a
// YAML string, or an environment variable — and adding a field to Config needs
// no change here.
//
// There are no secret-typed fields yet. When one is added, mask it here so
// masking is a property of the type rather than of every call site.
func (l *Loaded) Print(w io.Writer) error {
	effective := koanf.New(".")
	if err := effective.Load(structs.Provider(l.Config, "koanf"), nil); err != nil {
		return fmt.Errorf("render config: %w", err)
	}

	keys := effective.Keys()
	slices.Sort(keys)

	tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
	for _, key := range keys {
		source := l.sources[key]
		if source == "" {
			source = "default"
		}
		if _, err := fmt.Fprintf(tw, "%s\t%v\t# %s\n", key, effective.Get(key), source); err != nil {
			return err
		}
	}
	return tw.Flush()
}
