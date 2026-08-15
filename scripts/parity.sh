#!/usr/bin/env bash
#
# parity.sh — fail when a cross-language CONTRACT breaks, or when the
# templates themselves are malformed.
#
# Scope is set by ADR 0017: parity is required only where something OUTSIDE
# the service consumes the thing. Everywhere else each language does what is
# idiomatic for it. The question to ask of any proposed check is: if these
# two differed, what outside the service would break? If the answer is
# "nothing, but a diff would fail", the diff is the problem.
#
# CONTRACTS — identical, because an external consumer breaks otherwise:
#   1  `make help` — the developer/agent command surface
#   2  config precedence and source order — runbooks, shared ConfigMaps
#   +  metric names and label keys        (chunk 08)
#   +  log field names                    (chunk 04)
#
# TEMPLATE HYGIENE — not parity; the templates being well-formed at all:
#   3  question-set shape
#   4  one fixture generates both languages
#   5  no generated artifacts shipped as template files (ADR 0007)
#   6  no unrendered template delimiters in output
#   7  no Jinja default {{ }} syntax
#   8  the shared docs exist exactly once
#
# DELIBERATELY NOT CHECKED (ADR 0017): internal directory and file layout,
# error message wording, byte-level formatting, JSON key order and
# whitespace, duration and number formatting, internal type shapes.
#
# Several of these checks exist because something slipped past an earlier
# one — and two of them once passed green while comparing two
# identically-broken outputs. Hence the rule now baked in below: assert each
# side SUCCEEDS before comparing them. Sameness means nothing until then.

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
strip_ansi() { sed -e $'s/\033\\[[0-9;]*m//g'; }

section() { printf '\n  %s\n' "$(dim "$1")"; }
pass() { CHECK_NO=$((CHECK_NO+1)); printf '  %s  %d. %s\n' "$(green ✓)" "$CHECK_NO" "$1"; }
fail() {
  CHECK_NO=$((CHECK_NO+1)); FAILED=1
  printf '  %s  %d. %s\n' "$(red ✗)" "$CHECK_NO" "$1"
  while IFS= read -r line; do printf '        %s\n' "$line"; done <<< "$2"
}

printf '\nmint parity\n'

# ===========================================================================
# Generate both services first — most checks need them.
# ===========================================================================

gen() { # gen <language> <dest>
  copier copy --defaults --trust --skip-tasks --quiet \
    --data-file scripts/fixture-answers.yml \
    -d "language=$1" . "$2" 2>"$WORK/$1.err"
}

GENERATED=0
if ! gen go "$WORK/go"; then
  GEN_ERR="generating the Go service failed:
$(cat "$WORK/go.err")"
elif ! gen python "$WORK/py"; then
  GEN_ERR="generating the Python service failed:
$(cat "$WORK/py.err")"
else
  GENERATED=1
fi

# ===========================================================================
section "contracts — an external consumer breaks if these differ"
# ===========================================================================

# --- 1. `make help` --------------------------------------------------------
#
# The command surface is the parity that the spec's goal was actually about:
# someone should be able to cd into either service and run the same commands
# without checking which language it is.
#
# Both must SUCCEED before being compared. This check twice passed green on
# identically-broken output — once when both Makefiles shipped unrendered,
# once when an apostrophe in service_description broke `printf` in both.

if [[ "$GENERATED" == "1" ]]; then
  go_help=$(make -C "$WORK/go" help 2>&1 | strip_ansi); go_rc=$?
  py_help=$(make -C "$WORK/py" help 2>&1 | strip_ansi); py_rc=$?
  if [[ $go_rc -ne 0 || $py_rc -ne 0 ]]; then
    fail "\`make help\` runs" "must exit 0 in both before its output means anything.
go=$go_rc python=$py_rc

go:
$go_help

python:
$py_help"
  elif diff_out=$(diff <(echo "$go_help") <(echo "$py_help")); then
    pass "\`make help\` succeeds in both and the target surface is identical"
  else
    fail "\`make help\` target surface" "< go-service   > python-service
$diff_out"
  fi
else
  fail "\`make help\` target surface" "$GEN_ERR"
fi

# --- 2. Config precedence and source order ---------------------------------
#
# The ordered source list is the one place precedence is expressed, and it is
# a contract: runbooks and a ConfigMap envFrom-ed by several services depend
# on it. ADR 0006 — pydantic_settings defaults to a FOUR-source chain and
# silently let a .env file beat YAML, so this is what turns a reintroduced
# dotenv_settings into a build failure rather than a production surprise.
#
# `make config` OUTPUT is no longer diffed (ADR 0017): the rendering is
# formatting, and formatting is idiomatic. That it SUCCEEDS is still checked,
# because a broken --print-config is a real defect.

if [[ "$GENERATED" == "1" ]]; then
  go_cfg=$(make -C "$WORK/go" config 2>&1 | strip_ansi); go_rc=$?
  py_cfg=$(make -C "$WORK/py" config 2>&1 | strip_ansi); py_rc=$?
  want="yaml, env"
  go_src=$(echo "$go_cfg" | sed -n 's/^sources, lowest precedence first: //p')
  py_src=$(echo "$py_cfg" | sed -n 's/^sources, lowest precedence first: //p')

  if [[ $go_rc -ne 0 || $py_rc -ne 0 ]]; then
    fail "\`make config\` runs" "must exit 0 in both. go=$go_rc python=$py_rc

go:
$go_cfg

python:
$py_cfg"
  elif [[ "$go_src" != "$want" || "$py_src" != "$want" ]]; then
    fail "config source order" "both languages must report exactly: $want
  go:     ${go_src:-<not reported>}
  python: ${py_src:-<not reported>}"
  elif ! grep -q 'no third source' templates/_common/docs/config.md; then
    fail "config source order" "both languages report '$want', but docs/config.md no longer states
that there is no third source. The document and the code must agree."
  else
    pass "config sources are exactly [$want] in both, and docs/config.md agrees"
  fi
else
  fail "config source order" "$GEN_ERR"
fi

# ===========================================================================
section "template hygiene — the templates being well-formed at all"
# ===========================================================================

# --- 3. Question-set shape -------------------------------------------------
#
# There is one copier.yml, so the questions cannot drift — there is one set
# of them (ADR 0009). What can still go wrong is a `when:` on a shared
# question, or a language question made unconditional.
#
# Parsed as YAML, not grepped: an early grep version matched the word
# "when:" inside a comment and reported drift that wasn't there. PyYAML
# isn't in the stdlib, so this runs through uv, which mint already requires
# in order to install copier at all.

shape_err=$(uv run --quiet --with pyyaml python3 - <<'PY' 2>&1
import sys, yaml

class L(yaml.SafeLoader):
    pass
L.add_constructor("!include", lambda ldr, node: {"__include__": True})

EXPECTED_GATED = {"module_path", "package_name"}

def questions(path):
    out = {}
    with open(path) as fh:
        for doc in yaml.load_all(fh, Loader=L):
            if not isinstance(doc, dict):
                continue
            for k, v in doc.items():
                if k.startswith("_") or not isinstance(v, dict) or "__include__" in v:
                    continue
                out[k] = v
    return out

problems = []

bad_shared = sorted(k for k, v in questions("questions-shared.yml").items() if "when" in v)
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

# --- 4. One fixture generates both -----------------------------------------

if [[ "$GENERATED" == "1" ]]; then
  pass "one fixture answers file generates both languages"
else
  fail "one fixture generates both" "$GEN_ERR"
fi

# --- 5. No generated artifacts shipped as template files (ADR 0007) --------
#
# openapi.json and llms.txt are committed IN a generated service but must
# never exist in the templates. Copier three-way-merges only files it
# renders; the moment either becomes a template file, every `copier update`
# conflicts on it forever.

stowaways=$(find templates -type f \( -name 'openapi*.json' -o -name 'llms.txt' \
              -o -name 'openapi*.json.jinja' -o -name 'llms.txt.jinja' \) 2>/dev/null || true)
if [[ -z "$stowaways" ]]; then
  pass "no openapi.json / llms.txt shipped as template files (ADR 0007)"
else
  fail "generated artifacts in templates (ADR 0007)" "these must never be template files — copier update would conflict on
them forever. Generate them with 'make agents-docs' instead:
$stowaways"
fi

# --- 6. No unrendered delimiters in generated output -----------------------
#
# Catches a template file missing its .jinja suffix — Copier's
# _templates_suffix defaults to .jinja and unsuffixed files are copied
# verbatim, which once shipped both Makefiles with a literal {@ service_name @}.
#
# Requires a space after `{@`, which is how every Mint template writes a
# variable.

# Scan only what the template produced. The contract checks above run
# `make config`, which creates .venv — and coverage ships HTML templates full
# of Jinja-ish syntax, which is somebody else's code and not our output.
unrendered=""
for d in "$WORK/go" "$WORK/py"; do
  [[ -d "$d" ]] || continue
  found=$(grep -rlE '\{@ +[a-zA-Z_]|\{% +[a-z]' "$d" \
            --exclude-dir=.git --exclude-dir=.venv --exclude-dir=bin \
            --exclude-dir=node_modules --exclude-dir=.mypy_cache \
            --exclude-dir=.ruff_cache --exclude-dir=.pytest_cache \
            2>/dev/null || true)
  [[ -n "$found" ]] && unrendered+="${found}"$'\n'
done
if [[ -z "${unrendered// }" ]]; then
  pass "no unrendered template delimiters in generated output"
else
  fail "unrendered template delimiters" "these reached a generated service with {@ @} or {% %} intact, which
usually means the template file is missing its .jinja suffix:
$(echo "$unrendered" | sed "s|$WORK/||" | grep -v '^$')"
fi

# --- 7. Nobody reaches for Jinja's default variable syntax -----------------
#
# `{{ name }}` is what every Jinja tutorial teaches, and in a Mint template
# it renders as literal text — no error, no warning, the variable simply
# fails to interpolate. Bare `{{` is legitimate in a Helm chart (Phase 3),
# so only the spaced variable form is checked.

default_syntax=$(grep -rn '{{ [a-zA-Z_]' templates --include='*.jinja' 2>/dev/null || true)
if [[ -z "$default_syntax" ]]; then
  pass "no Jinja default {{ }} syntax in templates"
else
  fail "Jinja default {{ }} syntax in a template" "Mint's variable delimiter is {@ @}. These render as literal text with
no error — the variable will not interpolate:
$default_syntax"
fi

# --- 8. The shared docs exist exactly once ---------------------------------
#
# architecture/logging/config/testing are canonical in templates/_common/docs/
# and mint's own docs/ entries are symlinks. They were briefly real files in
# both places and had already drifted while both claimed to be source of
# truth.

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
  fail "shared docs duplicated" "these facts must live in exactly one file. A second copy drifts — it
already did once, while both copies called themselves source of truth:
$dup_docs"
fi

# --- summary ---------------------------------------------------------------

printf '\n'
if [[ "$FAILED" == "0" ]]; then
  printf '%s  %d checks passed\n\n' "$(green PASS)" "$CHECK_NO"
else
  printf '%s  contract broken or template malformed\n' "$(red FAIL)"
  dim "  generated services kept at: $WORK"; printf '\n\n'
  CLEANUP=0
fi
exit "$FAILED"
