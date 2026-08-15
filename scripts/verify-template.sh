#!/usr/bin/env bash
#
# verify-template.sh — generate, build, boot, assert, tear down.
#
# parity.sh proves the two templates agree with each other. This proves they
# produce something that actually runs. Assertions, not eyeballing.
#
# Chunk 02 scope: generate → build → boot → GET / → 200 → shutdown.
# Later chunks extend it: /healthz and /readyz (06), a log line in each tier
# and an exported span (04, 08), the widgets endpoints (07), /openapi.json
# and /llms.txt (09), and a SIGTERM drain assertion against the SPLIT port
# configuration (06/10 — that's the only config where the uvicorn signal
# race appears).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WORK="$(mktemp -d)"
PIDS=()
FAILED=0

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    [[ -n "${pid:-}" ]] && kill "$pid" 2>/dev/null
  done
  [[ "$FAILED" == "0" ]] && rm -rf "$WORK"
}
trap cleanup EXIT

red()   { printf '\033[31m%s\033[0m' "$*"; }
green() { printf '\033[32m%s\033[0m' "$*"; }

ok()   { printf '    %s %s\n' "$(green ✓)" "$1"; }
bad()  { FAILED=1; printf '    %s %s\n' "$(red ✗)" "$1"
         [[ $# -gt 1 ]] && while IFS= read -r l; do printf '        %s\n' "$l"; done <<< "$2"; }

# Ports come from the fixture so there is one source of truth for them.
PORT=$(awk '/^port:/ {print $2}' scripts/fixture-answers.yml)

wait_for_port() { # wait_for_port <port> <seconds>
  local deadline=$((SECONDS + $2))
  while (( SECONDS < deadline )); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$1/" 2>/dev/null; then return 0; fi
    sleep 0.2
  done
  return 1
}

verify_one() { # verify_one <language>
  local lang="$1" dir="$WORK/$lang"
  printf '\n  %s\n' "$lang"

  # Full generation path, tasks included — `go mod tidy` / `uv sync` running
  # here is part of what's being verified. A failing task aborts generation
  # entirely, so this doubles as a check that _tasks is correct.
  if ! copier copy --defaults --trust --quiet \
        --data-file scripts/fixture-answers.yml \
        -d "language=$lang" . "$dir" >"$WORK/$lang.gen" 2>&1; then
    bad "generate" "$(cat "$WORK/$lang.gen")"
    return
  fi
  ok "generate"

  if [[ ! -f "$dir/.copier-answers.yml" ]]; then
    bad "answers file written" "no .copier-answers.yml — generation rolled back?"
    return
  fi
  if ! grep -q '^_commit:' "$dir/.copier-answers.yml"; then
    bad "mint mark resolvable" "no _commit in .copier-answers.yml — the mint mark cannot render.
This is the ADR 0009 Finding 4 failure: copier.yml must be at the git repo root."
  else
    ok "mint mark resolvable (_commit present)"
  fi

  # ADR 0009: _common/ reaches the tree by symlink, but preserve_symlinks
  # defaults to false, so the GENERATED service must hold real files.
  if [[ -d "$dir/docs" ]]; then
    if find "$dir/docs" -type l | grep -q .; then
      bad "docs/ materialized" "generated docs/ contains symlinks; preserve_symlinks should have
resolved them to real files"
    else
      ok "docs/ materialized as real files"
    fi
  fi

  if ! make -C "$dir" build >"$WORK/$lang.build" 2>&1; then
    bad "make build" "$(tail -20 "$WORK/$lang.build")"
    return
  fi
  ok "make build"

  make -C "$dir" run >"$WORK/$lang.run" 2>&1 &
  PIDS+=($!)
  if wait_for_port "$PORT" 30; then
    ok "boots and listens on $PORT"
    code=$(curl -fsS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null)
    if [[ "$code" == "200" ]]; then ok "GET / → 200"
    else bad "GET / → 200" "got: ${code:-<no response>}"; fi
  else
    bad "boots and listens on $PORT" "$(tail -20 "$WORK/$lang.run")"
  fi

  # Tear down before the next language — both use the same fixture port.
  local pid="${PIDS[-1]}"
  kill "$pid" 2>/dev/null
  pkill -P "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  sleep 0.5
}

printf '\nmint verify\n'
verify_one go
verify_one python

printf '\n'
if [[ "$FAILED" == "0" ]]; then
  printf '%s  both templates generate, build, boot and answer\n\n' "$(green PASS)"
else
  printf '%s  see above; generated services kept at: %s\n\n' "$(red FAIL)" "$WORK"
fi
exit "$FAILED"
