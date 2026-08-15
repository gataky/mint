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
#   3  normalized directory trees
#   4  `make help` output
#   5  no generated artifacts shipped as template files (ADR 0007)

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
normalize() { # normalize <dir>
  ( cd "$1" && find . -type f -not -path './.git/*' \
      | sed -e 's|^\./||' \
            -e 's|^src/widget_svc/||' \
            -e 's|\.go$||' -e 's|\.py$||' \
      | grep -v -E '^(go\.mod|go\.sum|pyproject\.toml|uv\.lock|\.golangci\.yml)$' \
      | grep -v -E '^(cmd/widget-svc/main|__main__|__init__)$' \
      | grep -v -E '/__init__$' \
      | sort )
}

if [[ -d "$WORK/go" && -d "$WORK/py" ]]; then
  if diff_out=$(diff <(normalize "$WORK/go") <(normalize "$WORK/py")); then
    pass "normalized directory trees match"
  else
    fail "normalized directory trees" "< go-service   > python-service
$diff_out"
  fi
else
  fail "normalized directory trees" "one or both services were not generated (see above)"
fi

# --- 4. `make help` output -------------------------------------------------
#
# The spec's hard requirement: someone should be able to cd into either
# service and run the same commands without checking which language it is.

strip_ansi() { sed -e $'s/\033\\[[0-9;]*m//g'; }

if [[ -d "$WORK/go" && -d "$WORK/py" ]]; then
  go_help=$(make -C "$WORK/go" help 2>&1 | strip_ansi)
  py_help=$(make -C "$WORK/py" help 2>&1 | strip_ansi)
  if diff_out=$(diff <(echo "$go_help") <(echo "$py_help")); then
    pass "\`make help\` output is identical"
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
