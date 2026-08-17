#!/usr/bin/env bash
#
# Boot both services and diff what they return, request by request.
#
# This is not a test suite — it is the thing you run to see with your own eyes
# that a client cannot tell the two apart. A real conformance test is a
# deliberate later step; until then, this is how a change gets checked.
#
#   ./scripts/compare.sh
#
# Exits non-zero if any compared response differs.

set -uo pipefail

cd "$(dirname "$0")/.."

# The two reference services live under foundry/. The Copier templates minted
# from them live in the go-service-template/py-service-template repos and are
# not what this script compares.
GO_SVC=foundry/go-service
PY_SVC=foundry/py-service

GO_PORT=18080
GO_ADMIN=19080
PY_PORT=18081
PY_ADMIN=19081

# A process left over from an earlier run makes one service fail to bind, and
# the symptom is a handful of unrelated "differences" further down — traceparent
# missing, the access log unparseable. Fail here instead, where it is obvious.
for port in $GO_PORT $GO_ADMIN $PY_PORT $PY_ADMIN; do
	if lsof -ti "tcp:$port" >/dev/null 2>&1; then
		printf 'port %s is already in use; compare.sh needs %s %s %s %s free\n' \
			"$port" "$GO_PORT" "$GO_ADMIN" "$PY_PORT" "$PY_ADMIN" >&2
		lsof -i "tcp:$port" >&2
		exit 1
	fi
done

TMP=$(mktemp -d)
trap 'kill ${GO_PID-} ${PY_PID-} 2>/dev/null; wait ${GO_PID-} ${PY_PID-} 2>/dev/null; rm -rf "$TMP"' EXIT

failures=0

banner() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# Compare one request against both services.
#   compare <label> <curl args...>   — %s is replaced by the base URL
compare() {
	local label=$1
	shift

	local go_out py_out
	go_out=$(curl -sS "${@/\%s/http://localhost:$GO_PORT}" 2>&1)
	py_out=$(curl -sS "${@/\%s/http://localhost:$PY_PORT}" 2>&1)

	if [[ "$go_out" == "$py_out" ]]; then
		printf '  \033[32m✓\033[0m %s\n' "$label"
	else
		printf '  \033[31m✗\033[0m %s\n' "$label"
		diff <(echo "$go_out") <(echo "$py_out") | sed 's/^/      /'
		failures=$((failures + 1))
	fi
}

# Compare an admin-port request.
compare_admin() {
	local label=$1
	shift

	local go_out py_out
	go_out=$(curl -sS "${@/\%s/http://localhost:$GO_ADMIN}" 2>&1)
	py_out=$(curl -sS "${@/\%s/http://localhost:$PY_ADMIN}" 2>&1)

	if [[ "$go_out" == "$py_out" ]]; then
		printf '  \033[32m✓\033[0m %s\n' "$label"
	else
		printf '  \033[31m✗\033[0m %s\n' "$label"
		diff <(echo "$go_out") <(echo "$py_out") | sed 's/^/      /'
		failures=$((failures + 1))
	fi
}

banner "starting both services"

(cd "$GO_SVC" && go build -o "$TMP/widget-svc" ./cmd/widget-svc) || exit 1
MINT_SERVER__PORT=$GO_PORT MINT_SERVER__ADMIN_PORT=$GO_ADMIN MINT_LOGGING__FORMAT=json \
	"$TMP/widget-svc" >"$TMP/go.log" 2>&1 &
GO_PID=$!

# Sync first and then exec the venv interpreter, rather than `uv run` inside a
# subshell. Both of those put a process between $! and the server: the kill in
# the trap reaps the wrapper, the server keeps the ports, and the next run of
# this script reports differences that are really one leaked process.
(cd "$PY_SVC" && uv sync --quiet) || exit 1
(
	cd "$PY_SVC" || exit 1
	exec env MINT_SERVER__PORT=$PY_PORT MINT_SERVER__ADMIN_PORT=$PY_ADMIN \
		MINT_LOGGING__FORMAT=json .venv/bin/python -m widget_svc
) >"$TMP/py.log" 2>&1 &
PY_PID=$!

for _ in $(seq 1 40); do
	if curl -sf "http://localhost:$GO_ADMIN/healthz" >/dev/null 2>&1 &&
		curl -sf "http://localhost:$PY_ADMIN/healthz" >/dev/null 2>&1; then
		break
	fi
	sleep 0.5
done

if ! curl -sf "http://localhost:$GO_ADMIN/healthz" >/dev/null 2>&1; then
	echo "go service did not come up:"
	cat "$TMP/go.log"
	exit 1
fi
if ! curl -sf "http://localhost:$PY_ADMIN/healthz" >/dev/null 2>&1; then
	echo "python service did not come up:"
	cat "$TMP/py.log"
	exit 1
fi

banner "health (admin port)"
compare_admin "GET /healthz" %s/healthz
compare_admin "GET /readyz" %s/readyz
compare_admin "GET /nope is problem+json" %s/nope

banner "widgets"
# IDs and timestamps differ by construction, so compare the shape rather than
# the bytes: create one widget on each, then compare everything that is not
# generated.
for base in "http://localhost:$GO_PORT" "http://localhost:$PY_PORT"; do
	curl -sS -X POST "$base/widgets" -H 'content-type: application/json' \
		-d '{"name":"sprocket","color":"red"}' >/dev/null
done

compare "GET /widgets (keys and values, minus generated fields)" \
	-o /dev/null -w '%{http_code} %{content_type}\n' %s/widgets

go_list=$(curl -sS "http://localhost:$GO_PORT/widgets" |
	python3 -c 'import json,sys; print(json.dumps([{k:v for k,v in w.items() if k not in ("id","created_at")} for w in json.load(sys.stdin)], sort_keys=True))')
py_list=$(curl -sS "http://localhost:$PY_PORT/widgets" |
	python3 -c 'import json,sys; print(json.dumps([{k:v for k,v in w.items() if k not in ("id","created_at")} for w in json.load(sys.stdin)], sort_keys=True))')
if [[ "$go_list" == "$py_list" ]]; then
	printf '  \033[32m✓\033[0m GET /widgets body shape\n'
else
	printf '  \033[31m✗\033[0m GET /widgets body shape\n'
	diff <(echo "$go_list") <(echo "$py_list") | sed 's/^/      /'
	failures=$((failures + 1))
fi

# created_at format must match to the character.
for base in "http://localhost:$GO_PORT" "http://localhost:$PY_PORT"; do
	stamp=$(curl -sS "$base/widgets" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["created_at"])')
	if [[ ! "$stamp" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?Z$ ]]; then
		printf '  \033[31m✗\033[0m created_at format on %s: %s\n' "$base" "$stamp"
		failures=$((failures + 1))
	fi
done
printf '  \033[32m✓\033[0m created_at is RFC 3339 on both\n'

banner "errors"
compare "GET /widgets/nope (404 problem+json)" %s/widgets/nope
compare "GET /nothing-here (unrouted 404)" %s/nothing-here
compare "POST /widgets duplicate (409)" \
	-X POST %s/widgets -H 'content-type: application/json' \
	-d '{"name":"sprocket","color":"red"}'
compare "POST /widgets bad shape (422 status and envelope)" \
	-o /dev/null -w '%{http_code} %{content_type}\n' \
	-X POST %s/widgets -H 'content-type: application/json' \
	-d '{"name":"","color":"puce"}'

banner "discovery"
# Status and media type, with any charset parameter stripped. Go's docs handler
# sends "text/html" and FastAPI's sends "text/html; charset=utf-8"; /docs is a
# human-facing UI page rather than an API response, and HTML5 defaults to UTF-8
# regardless, so that parameter is not treated as a difference.
go_docs=$(curl -sS -o /dev/null -w '%{http_code} %{content_type}' "http://localhost:$GO_PORT/docs" | cut -d';' -f1)
py_docs=$(curl -sS -o /dev/null -w '%{http_code} %{content_type}' "http://localhost:$PY_PORT/docs" | cut -d';' -f1)
if [[ "$go_docs" == "$py_docs" ]]; then
	printf '  \033[32m✓\033[0m GET /docs serves Swagger UI (%s)\n' "$go_docs"
else
	printf '  \033[31m✗\033[0m GET /docs\n'
	diff <(echo "$go_docs") <(echo "$py_docs") | sed 's/^/      /'
	failures=$((failures + 1))
fi

go_paths=$(curl -sS "http://localhost:$GO_PORT/openapi.json" |
	python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["openapi"][:3], json.dumps({p: sorted(m) for p,m in d["paths"].items()}, sort_keys=True))')
py_paths=$(curl -sS "http://localhost:$PY_PORT/openapi.json" |
	python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["openapi"][:3], json.dumps({p: sorted(m) for p,m in d["paths"].items()}, sort_keys=True))')
if [[ "$go_paths" == "$py_paths" ]]; then
	printf '  \033[32m✓\033[0m /openapi.json version and path/method set\n'
else
	printf '  \033[31m✗\033[0m /openapi.json version and path/method set\n'
	diff <(echo "$go_paths") <(echo "$py_paths") | sed 's/^/      /'
	failures=$((failures + 1))
fi

banner "metrics"
# scripts/metric-families.py exits non-zero if an owned family is missing, so
# this cannot pass by finding nothing on both sides.
go_metrics=$(curl -sS "http://localhost:$GO_ADMIN/metrics" | python3 scripts/metric-families.py)
go_ok=$?
py_metrics=$(curl -sS "http://localhost:$PY_ADMIN/metrics" | python3 scripts/metric-families.py)
py_ok=$?

if ((go_ok != 0)) || ((py_ok != 0)); then
	printf '  \033[31m✗\033[0m /metrics could not be parsed (go=%d python=%d)\n' "$go_ok" "$py_ok"
	failures=$((failures + 1))
elif [[ "$go_metrics" == "$py_metrics" ]]; then
	printf '  \033[32m✓\033[0m metric families and label keys\n'
	echo "$go_metrics" | sed 's/^/      /'
else
	printf '  \033[31m✗\033[0m metric families and label keys\n'
	diff <(echo "$go_metrics") <(echo "$py_metrics") | sed 's/^/      /'
	failures=$((failures + 1))
fi

banner "tracing"
# A caller's trace must continue through both services rather than a new one
# starting, or a distributed trace breaks at every service boundary.
TRACEPARENT_ID="4bf92f3577b34da6a3ce929d0e0e4736"
for base in "http://localhost:$GO_PORT" "http://localhost:$PY_PORT"; do
	curl -sS "$base/widgets" \
		-H "traceparent: 00-$TRACEPARENT_ID-00f067aa0ba902b7-01" >/dev/null
done
sleep 0.5

read -r -d '' FIND_TRACE <<'PYEOF'
import json, sys
wanted = sys.argv[2]
for line in open(sys.argv[1]):
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("msg") == "request" and event.get("trace_id") == wanted:
        print("continued")
        break
else:
    print("NOT FOUND")
PYEOF

go_trace=$(python3 -c "$FIND_TRACE" "$TMP/go.log" "$TRACEPARENT_ID")
py_trace=$(python3 -c "$FIND_TRACE" "$TMP/py.log" "$TRACEPARENT_ID")
if [[ "$go_trace" == "continued" && "$py_trace" == "continued" ]]; then
	printf '  \033[32m✓\033[0m inbound traceparent is continued (go=%s python=%s)\n' "$go_trace" "$py_trace"
else
	printf '  \033[31m✗\033[0m inbound traceparent (go=%s python=%s)\n' "$go_trace" "$py_trace"
	failures=$((failures + 1))
fi

banner "logs"
go_keys=$(python3 -c '
import json, sys
for line in open(sys.argv[1]):
    event = json.loads(line)
    if event.get("msg") == "request":
        print(" ".join(sorted(event)))
        break
' "$TMP/go.log")
py_keys=$(python3 -c '
import json, sys
for line in open(sys.argv[1]):
    event = json.loads(line)
    if event.get("msg") == "request":
        print(" ".join(sorted(event)))
        break
' "$TMP/py.log")
if [[ "$go_keys" == "$py_keys" ]]; then
	printf '  \033[32m✓\033[0m access log field names: %s\n' "$go_keys"
else
	printf '  \033[31m✗\033[0m access log field names\n'
	diff <(echo "$go_keys") <(echo "$py_keys") | sed 's/^/      /'
	failures=$((failures + 1))
fi

banner "make help"
go_targets=$(make -C "$GO_SVC" help | grep -oE '^  [a-z-]+' | tr -d ' ' | sort)
py_targets=$(make -C "$PY_SVC" help | grep -oE '^  [a-z-]+' | tr -d ' ' | sort)
if [[ "$go_targets" == "$py_targets" ]]; then
	printf '  \033[32m✓\033[0m the two Makefiles expose the same targets\n'
else
	printf '  \033[31m✗\033[0m Makefile targets differ\n'
	diff <(echo "$go_targets") <(echo "$py_targets") | sed 's/^/      /'
	failures=$((failures + 1))
fi

banner "config"
go_config=$(cd "$GO_SVC" && make --no-print-directory config | sed 's/#.*//' | sed 's/[[:space:]]*$//')
py_config=$(cd "$PY_SVC" && make --no-print-directory config | sed 's/#.*//' | sed 's/[[:space:]]*$//')
if [[ "$go_config" == "$py_config" ]]; then
	printf '  \033[32m✓\033[0m effective config is identical\n'
else
	printf '  \033[31m✗\033[0m effective config differs\n'
	diff <(echo "$go_config") <(echo "$py_config") | sed 's/^/      /'
	failures=$((failures + 1))
fi

banner "shutdown"
# Both are running the SPLIT-port configuration, which is the only one where
# two servers can race on the signal handlers. A collapsed listener cannot show
# that bug, so testing only that path would pass while shipping it.
kill -TERM "$GO_PID" "$PY_PID" 2>/dev/null
sleep 3
for entry in "go:$GO_PID" "python:$PY_PID"; do
	name=${entry%%:*}
	pid=${entry##*:}
	if kill -0 "$pid" 2>/dev/null; then
		printf '  \033[31m✗\033[0m %s did not exit on SIGTERM\n' "$name"
		failures=$((failures + 1))
	else
		printf '  \033[32m✓\033[0m %s drained and exited\n' "$name"
	fi
done
unset GO_PID PY_PID

printf '\n'
if ((failures == 0)); then
	printf '\033[32mno differences\033[0m\n\n'
	exit 0
fi
printf '\033[31m%d difference(s)\033[0m\n\n' "$failures"
exit 1
