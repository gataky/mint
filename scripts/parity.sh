#!/usr/bin/env bash
#
# parity.sh — fail when the Go and Python templates drift apart.
#
# Every guarantee in the spec that says "these must be identical" needs
# something here that exits non-zero when they stop being identical. Chunks
# add their checks as they land; chunk 10 proves each one fails on the drift
# it targets, because a check that has never been seen to fail is not known
# to work.
#
# Checks implemented so far (chunk 02):
#   1  question-set shape          — only the two language questions are gated
#   2  one fixture generates both  — the single-question-set property
#   3  package directory sets
#   4  normalized file trees
#   5  `make help` succeeds in both, then matches
#   6  no generated artifacts shipped as template files (ADR 0007)
#   7  no unrendered template delimiters in generated output
#   8  the shared docs exist exactly once
#   9  no Jinja default {{ }} syntax, which renders as literal text
#  10  `make config` succeeds in both, then matches
#  11  ordered config sources are exactly ["yaml", "env"] (ADR 0006)
#
# Four of these (5, 7, 8, 9) exist because something slipped through the
# others. A check earns its place by having caught something.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WORK="${MINT_PARITY_WORK:-$(mktemp -d)}"
CLEANUP="${MINT_PARITY_KEEP:-1}"
trap '[[ "$CLEANUP" == "1" ]] && rm -rf "$WORK"' EXIT

FAILED=0
CHECK_NO=0

red()   { printf '\033[31m%s\033[0m' "$*"; }
green() { printf '\033[32m%s\033[0m' "$*"; }
dim()   { printf '\033[2m%s\033[0m'  "$*"; }

pass() { CHECK_NO=$((CHECK_NO+1)); printf '  %s  %d. %s\n' "$(green ✓)" "$CHECK_NO" "$1"; }
fail() {
  CHECK_NO=$((CHECK_NO+1)); FAILED=1
  printf '  %s  %d. %s\n' "$(red ✗)" "$CHECK_NO" "$1"
  # Indent the explanation so the diff is readable in CI output.
  while IFS= read -r line; do printf '        %s\n' "$line"; done <<< "$2"
}

printf '\nmint parity\n\n'

# --- 1. Question-set shape -------------------------------------------------
#
# ADR 0009 changed this check's shape. There is one copier.yml, so there is
# nothing to diff — the questions cannot drift because there is one set of
# them. What CAN still go wrong is someone adding a `when:` to a shared
# question, or making a language question unconditional, which reintroduces
# exactly the divergence the single-file layout removed.

# Parsed as YAML, not grepped: an early grep version of this check matched
# the word "when:" inside a comment and reported drift that wasn't there.
# PyYAML isn't in the stdlib, so this runs through uv, which mint already
# requires in order to install copier at all — no new dependency.
shape_err=$(uv run --quiet --with pyyaml python3 - <<'PY' 2>&1
import sys, yaml

class L(yaml.SafeLoader):
    pass
L.add_constructor("!include", lambda ldr, node: {"__include__": True})

EXPECTED_GATED = {"module_path", "package_name"}
RESERVED = lambda k: k.startswith("_")

def questions(path):
    out = {}
    with open(path) as fh:
        for doc in yaml.load_all(fh, Loader=L):
            if not isinstance(doc, dict):
                continue
            for k, v in doc.items():
                if RESERVED(k) or not isinstance(v, dict) or "__include__" in v:
                    continue
                out[k] = v
    return out

problems = []

shared = questions("questions-shared.yml")
bad_shared = sorted(k for k, v in shared.items() if "when" in v)
if bad_shared:
    problems.append(
        "questions-shared.yml must contain no 'when:' — every question in it is\n"
        "asked for both languages. Gated: " + ", ".join(bad_shared)
    )

root = questions("copier.yml")
gated = {k for k, v in root.items() if "when" in v}
if gated != EXPECTED_GATED:
    problems.append(
        "exactly two questions may be 'when:'-gated.\n"
        f"  expected: {sorted(EXPECTED_GATED)}\n"
        f"  found:    {sorted(gated) or '<none>'}"
    )

# A gate must depend on `language` and nothing else, or a question could be
# conditioned on something that differs between the two trees.
for k in sorted(gated & EXPECTED_GATED):
    expr = str(root[k]["when"])
    if "language" not in expr:
        problems.append(f"{k}'s `when:` must be gated on `language`; got: {expr}")

if problems:
    print("\n".join(problems))
    sys.exit(1)
PY
)
if [[ $? -eq 0 ]]; then
  pass "question-set shape — only module_path/package_name are language-gated"
else
  fail "question-set shape" "$shape_err"
fi

# --- 2 & 3. One fixture generates both, and the trees match ----------------

gen() { # gen <language> <dest>
  copier copy --defaults --trust --skip-tasks --quiet \
    --data-file scripts/fixture-answers.yml \
    -d "language=$1" . "$2" 2>"$WORK/$1.err"
}

if ! gen go "$WORK/go"; then
  fail "one fixture generates both" "generating the Go service failed:
$(cat "$WORK/go.err")"
elif ! gen python "$WORK/py"; then
  fail "one fixture generates both" "generating the Python service failed:
$(cat "$WORK/py.err")"
else
  pass "one fixture answers file generates both languages"
fi

# Normalization. Intentional differences are listed EXPLICITLY rather than
# smoothed away by a clever regex — adding to this list should require
# justifying the divergence, which a fuzzy normalizer would let you skip.
#
# Package docs are MAPPED to a common name, not filtered. Go marks a package
# with doc.go and Python with __init__.py; they mean the same thing, so they
# normalize to __pkgdoc__. Filtering both instead would have been easier and
# wrong — a directory containing only a package doc would then vanish from
# both sides, and "Go has this package, Python doesn't" would stop being
# visible to the check at all.
# The four documented divergences, and why each is a language fact rather
# than drift someone should fix:
#
#   cmd/ vs src/     entrypoint containers. Go modules put commands under
#                    cmd/<name>/; Python packaging expects src/<pkg>/.
#   main.go vs       Go's entrypoint is a main package; Python's is the
#     __main__.py    module the interpreter runs with `python -m`.
#   doc.go vs        Go's package doc can live in ANY file in the package —
#     __init__.py    internal/transport/http/ carries it in server.go — while
#                    __init__.py is mandatory for a Python package to be
#                    importable at all. They are not 1:1, so neither is
#                    mapped onto the other; the directory check below is what
#                    actually guarantees the packages correspond.
#   go.mod etc.      per-language manifests with no counterpart.
#
# Everything else must match.

norm_dirs() { # norm_dirs <dir> — the set of package directories
  ( cd "$1" && find . -type d -not -path './.git*' -not -path './bin*' \
      | sed -e 's|^\./||' -e 's|^src/widget_svc||' -e 's|^/||' \
      | grep -v -E '^(cmd|src|cmd/widget-svc|\.)?$' \
      | sort -u )
}

normalize() { # normalize <dir> — meaningful files, package markers excluded
  ( cd "$1" && find . -type f -not -path './.git/*' \
      | sed -e 's|^\./||' \
            -e 's|^src/widget_svc/||' \
            -e 's|\.go$||' -e 's|\.py$||' \
      | grep -v -E '^(go\.mod|go\.sum|pyproject\.toml|uv\.lock|\.golangci\.yml)$' \
      | grep -v -E '^(cmd/widget-svc/main|__main__|__init__)$' \
      | grep -v -E '(^|/)(doc|__init__)$' \
      | sort )
}

if [[ -d "$WORK/go" && -d "$WORK/py" ]]; then
  if diff_out=$(diff <(norm_dirs "$WORK/go") <(norm_dirs "$WORK/py")); then
    pass "package directory sets match"
  else
    fail "package directory sets" "< go-service   > python-service
$diff_out"
  fi
  if diff_out=$(diff <(normalize "$WORK/go") <(normalize "$WORK/py")); then
    pass "normalized file trees match"
  else
    fail "normalized file trees" "< go-service   > python-service
$diff_out"
  fi
else
  fail "package directory sets" "one or both services were not generated (see above)"
  fail "normalized file trees" "one or both services were not generated (see above)"
fi

# --- 4. `make help` output -------------------------------------------------
#
# The spec's hard requirement: someone should be able to cd into either
# service and run the same commands without checking which language it is.

strip_ansi() { sed -e $'s/\033\\[[0-9;]*m//g'; }

# Both must SUCCEED before they are compared. Comparing first would let two
# identically-broken outputs pass — which is not hypothetical: an unescaped
# apostrophe in service_description once broke `make help` in both languages
# at once, and this check reported them as matching, because they did.
if [[ -d "$WORK/go" && -d "$WORK/py" ]]; then
  go_help=$(make -C "$WORK/go" help 2>&1 | strip_ansi); go_rc=$?
  py_help=$(make -C "$WORK/py" help 2>&1 | strip_ansi); py_rc=$?
  if [[ $go_rc -ne 0 || $py_rc -ne 0 ]]; then
    fail "\`make help\` runs" "make help must exit 0 in both services before their output means
anything. go=$go_rc python=$py_rc

go:
$go_help

python:
$py_help"
  elif diff_out=$(diff <(echo "$go_help") <(echo "$py_help")); then
    pass "\`make help\` succeeds in both and output is identical"
  else
    fail "\`make help\` output" "< go-service   > python-service
$diff_out"
  fi
else
  fail "\`make help\` output" "one or both services were not generated (see above)"
fi

# --- 5. No generated artifacts shipped as template files (ADR 0007) --------
#
# openapi.json and llms.txt are committed IN a generated service but must
# never exist in the templates. Copier three-way-merges only files it
# renders; the moment either becomes a template file, every `copier update`
# conflicts on it forever. The property is load-bearing, so it is asserted
# rather than remembered.

stowaways=$(find templates -type f \( -name 'openapi*.json' -o -name 'llms.txt' \
              -o -name 'openapi*.json.jinja' -o -name 'llms.txt.jinja' \) 2>/dev/null || true)
if [[ -z "$stowaways" ]]; then
  pass "no openapi.json / llms.txt shipped as template files (ADR 0007)"
else
  fail "generated artifacts in templates (ADR 0007)" "these must never be template files — copier update would conflict on
them forever. Generate them with 'make agents-docs' instead:
$stowaways"
fi

# --- 6. No unrendered template delimiters in generated output --------------
#
# Added after a near-miss that says something important about what parity
# checks can and cannot do.
#
# Both Makefiles were briefly authored WITHOUT a .jinja suffix. Copier's
# default `_templates_suffix` is `.jinja`, so files lacking it are copied
# verbatim — both generated services got a Makefile containing a literal
# `[[ service_name ]]`. Check #4 compared the two and found them identical,
# because they were: identically broken. It passed.
#
# A parity check compares the two languages TO EACH OTHER. It is structurally
# incapable of catching a defect they share. That is verify-template.sh's job
# — and this check's, because it is cheap here and the trees are already
# generated.

unrendered=""
for d in "$WORK/go" "$WORK/py"; do
  [[ -d "$d" ]] || continue
  found=$(grep -rlE '\{@ +[a-zA-Z_]|\{% +[a-z]' "$d" --exclude-dir=.git 2>/dev/null || true)
  [[ -n "$found" ]] && unrendered+="${found}"$'\n'
done
if [[ -z "${unrendered// }" ]]; then
  pass "no unrendered template delimiters in generated output"
else
  fail "unrendered template delimiters" "these files reached a generated service with [[ ]] or [% %] intact,
which usually means the template file is missing its .jinja suffix:
$(echo "$unrendered" | sed "s|$WORK/||" | grep -v '^$')"
fi

# --- 8. The shared docs exist exactly once ---------------------------------
#
# architecture/logging/config/testing are canonical in templates/_common/docs/
# — the copy that ships to every generated service — and mint's own docs/
# entries are symlinks to them. They were briefly real files in both places
# and had already drifted (the service-facing config.md grew a "Local
# overrides" section its twin never got) while both claimed to be "source of
# truth".
#
# The canonical copy is the service-facing one because it has the stricter
# constraint: it cannot contain ../tasks/ or docs/decisions/ links, which
# break inside a generated service. Mint can read a service-facing document;
# a service cannot read a mint-facing one.

dup_docs=""
for f in architecture logging config testing; do
  if [[ ! -L "docs/$f.md" ]]; then
    dup_docs+="docs/$f.md is a real file; it must be a symlink to ../templates/_common/docs/$f.md"$'\n'
  elif [[ ! -r "docs/$f.md" ]]; then
    dup_docs+="docs/$f.md is a broken symlink"$'\n'
  fi
done
if [[ -z "${dup_docs// }" ]]; then
  pass "shared docs exist exactly once (mint's docs/ symlink into _common)"
else
  fail "shared docs duplicated" "these facts must live in exactly one file. A second copy drifts —
it already did once, while both copies called themselves source of truth:
$dup_docs"
fi

# --- 9. Nobody reaches for Jinja's default variable syntax -----------------
#
# This replaced a check that guarded TOML's `[[table]]` against the old
# `[[ ]]` delimiter. That collision no longer exists: the delimiter moved to
# `{@ @}` after `[[ ]]` turned out to collide with Python's
# `Callable[[str], str]` — which is simply how a callback is annotated, and
# cannot be worked around.
#
# The equivalent trap now is muscle memory. `{{ name }}` is what every Jinja
# tutorial teaches, and in a Mint template it renders as literal text: no
# error, no warning, the variable just silently fails to interpolate.
#
# Checks only the spaced form, since bare `{{` is legitimate in a Helm chart
# (Phase 3).

default_syntax=$(grep -rn '{{ [a-zA-Z_]' templates --include='*.jinja' 2>/dev/null || true)
if [[ -z "$default_syntax" ]]; then
  pass "no Jinja default {{ }} syntax in templates"
else
  fail "Jinja default {{ }} syntax in a template" "Mint's variable delimiter is {@ @}. These render as literal text with
no error — the variable simply will not interpolate:
$default_syntax"
fi

# --- 10 & 11. Configuration (chunk 03) -------------------------------------
#
# Both must SUCCEED before they are compared — the same rule check 5 learned
# the hard way. Two identically-broken `make config` runs would otherwise
# compare equal and pass.

if [[ -d "$WORK/go" && -d "$WORK/py" ]]; then
  go_cfg=$(make -C "$WORK/go" config 2>&1 | strip_ansi); go_rc=$?
  py_cfg=$(make -C "$WORK/py" config 2>&1 | strip_ansi); py_rc=$?

  if [[ $go_rc -ne 0 || $py_rc -ne 0 ]]; then
    fail "\`make config\` runs" "must exit 0 in both before its output means anything.
go=$go_rc python=$py_rc

go:
$go_cfg

python:
$py_cfg"
  elif diff_out=$(diff <(echo "$go_cfg") <(echo "$py_cfg")); then
    pass "\`make config\` succeeds in both and output is identical"
  else
    fail "\`make config\` output" "< go-service   > python-service
$diff_out"
  fi

  # The ordered source list is the one place precedence is expressed. ADR
  # 0006: pydantic_settings defaults to a FOUR-source chain and silently let
  # a .env file beat YAML, so this is the check that turns a reintroduced
  # dotenv_settings into a build failure rather than a production surprise.
  want="yaml, env"
  go_src=$(echo "$go_cfg" | sed -n 's/^sources, lowest precedence first: //p')
  py_src=$(echo "$py_cfg" | sed -n 's/^sources, lowest precedence first: //p')
  doc_ok=$(grep -c 'no third source' templates/_common/docs/config.md || true)

  if [[ "$go_src" != "$want" || "$py_src" != "$want" ]]; then
    fail "ordered config sources" "both languages must report exactly: $want
  go:     ${go_src:-<not reported>}
  python: ${py_src:-<not reported>}"
  elif [[ "$doc_ok" == "0" ]]; then
    fail "ordered config sources" "both languages report '$want', but docs/config.md no longer states
that there is no third source. The document and the code must agree."
  else
    pass "config sources are exactly [$want] in both, and docs/config.md agrees"
  fi
else
  fail "\`make config\` output" "one or both services were not generated (see above)"
  fail "ordered config sources" "one or both services were not generated (see above)"
fi

# --- summary ---------------------------------------------------------------

printf '\n'
if [[ "$FAILED" == "0" ]]; then
  printf '%s  %d checks passed\n\n' "$(green PASS)" "$CHECK_NO"
else
  printf '%s  drift detected\n' "$(red FAIL)"
  dim "  generated services kept at: $WORK"; printf '\n\n'
  CLEANUP=0
fi
exit "$FAILED"
