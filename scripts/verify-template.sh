#!/usr/bin/env bash
#
# Generate a service from the template, then build it, test it, boot it and ask
# it questions. Tears everything down afterwards.
#
#   ./scripts/verify-template.sh
#
# Two scenarios run, because the interesting failures live at the answers that
# are not the defaults:
#
#   1. defaults              — widgets and orders included, MINT_ prefix, :8080
#   2. an empty service      — no examples, a different prefix, different ports
#
# Exits non-zero on the first failure.

set -uo pipefail

cd "$(dirname "$0")/.."
ROOT=$PWD

COPIER=(uvx copier@9.17.1)

TMP=$(mktemp -d)
trap 'kill ${SVC_PID-} 2>/dev/null; wait ${SVC_PID-} 2>/dev/null; rm -rf "$TMP"' EXIT

failures=0

banner() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() {
	printf '  \033[31m✗\033[0m %s\n' "$1"
	[[ $# -gt 1 ]] && printf '      %s\n' "${@:2}"
	failures=$((failures + 1))
}

# assert_file <dir> <relative path>
assert_file() {
	if [[ -f "$1/$2" ]]; then ok "$2 exists"; else fail "$2 is missing"; fi
}

# refute_file <dir> <relative path>
refute_file() {
	if [[ -f "$1/$2" ]]; then fail "$2 should not have been generated"; else ok "$2 absent"; fi
}

# contains <label> <haystack> <needle>
contains() {
	if [[ "$2" == *"$3"* ]]; then ok "$1"; else fail "$1" "wanted $3 in: ${2:0:400}"; fi
}

# verify <scenario> <dst> <port> <admin port> <env prefix> <service name> <examples?>
verify() {
	local scenario=$1 dst=$2 port=$3 admin=$4 prefix=$5 name=$6 examples=$7

	banner "$scenario — generate"
	if ! "${COPIER[@]}" copy --trust --defaults --quiet "${GEN_ARGS[@]}" "$ROOT" "$dst"; then
		fail "copier copy failed"
		return
	fi
	ok "generated into $dst"

	assert_file "$dst" ".copier-answers.yml"
	assert_file "$dst" "cmd/$name/main.go"
	assert_file "$dst" "internal/transport/http/helpers_test.go"

	if [[ $examples == yes ]]; then
		assert_file "$dst" "internal/domain/widget.go"
		assert_file "$dst" "internal/transport/http/order.go"
	else
		refute_file "$dst" "internal/domain/widget.go"
		refute_file "$dst" "internal/transport/http/order.go"
		refute_file "$dst" "internal/service/service_test.go"
	fi

	if grep -rn '{@\|{%' "$dst" --include='*.go' --include='*.yml' --include='*.yaml' \
		--include='Makefile' --include='*.md' >/dev/null 2>&1; then
		fail "unrendered template syntax survived generation" \
			"$(grep -rn '{@\|{%' "$dst" --include='*.go' --include='*.md' | head -3)"
	else
		ok "no unrendered {@ @} or {% %} left behind"
	fi

	banner "$scenario — build, test, lint"
	(cd "$dst" && go build ./... 2>&1) && ok "go build" || fail "go build"
	(cd "$dst" && go test ./... 2>&1 | tail -20) && ok "go test" || fail "go test"
	(cd "$dst" && make lint >"$TMP/lint.log" 2>&1) && ok "make lint" ||
		fail "make lint" "$(tail -5 "$TMP/lint.log")"

	banner "$scenario — boot and answer"
	(cd "$dst" && go build -o "$TMP/svc-$name" "./cmd/$name") || {
		fail "building the binary"
		return
	}

	env "${prefix}_SERVER__PORT=$port" "${prefix}_SERVER__ADMIN_PORT=$admin" \
		"${prefix}_LOGGING__FORMAT=json" "$TMP/svc-$name" >"$TMP/$name.log" 2>&1 &
	SVC_PID=$!

	local up=no
	for _ in $(seq 1 40); do
		if curl -sf "http://localhost:$admin/healthz" >/dev/null 2>&1; then
			up=yes
			break
		fi
		sleep 0.25
	done

	if [[ $up != yes ]]; then
		fail "service did not come up on the ports it was asked for" "$(tail -10 "$TMP/$name.log")"
		kill $SVC_PID 2>/dev/null
		wait $SVC_PID 2>/dev/null
		unset SVC_PID
		return
	fi
	ok "listening on :$port and :$admin, configured through ${prefix}_"

	contains "healthz" "$(curl -sS "http://localhost:$admin/healthz")" '"status":"ok"'
	contains "openapi title" "$(curl -sS "http://localhost:$port/openapi.json")" "\"title\":\"$name\""
	contains "unrouted request is problem+json" \
		"$(curl -sS "http://localhost:$port/nope")" '"status":404'

	local logline
	logline=$(head -1 "$TMP/$name.log")
	contains "logs carry the service name" "$logline" "\"service\":\"$name\""

	if [[ $examples == yes ]]; then
		contains "POST /widgets" \
			"$(curl -sS -X POST "http://localhost:$port/widgets" \
				-H 'content-type: application/json' -d '{"name":"sprocket","color":"red"}')" \
			'"name":"sprocket"'
	else
		contains "no /widgets route" "$(curl -sS "http://localhost:$port/widgets")" '"status":404'
	fi

	kill $SVC_PID 2>/dev/null
	wait $SVC_PID 2>/dev/null
	unset SVC_PID
}

GEN_ARGS=(
	--data language=go
	--data service_name=parts-svc
	--data service_description="The parts service."
	--data service_owner=platform
	--data repo_url=github.com/example/parts-svc
)
verify "defaults" "$TMP/parts-svc" 18080 19080 MINT parts-svc yes

GEN_ARGS=(
	--data language=go
	--data service_name=empty-svc
	--data service_description="A service with no resources yet."
	--data service_owner=platform
	--data repo_url=github.com/example/empty-svc
	--data include_examples=false
	--data env_prefix=ACME
	--data port=18100
	--data admin_port=19100
)
verify "no examples, custom prefix and ports" "$TMP/empty-svc" 18100 19100 ACME empty-svc no

banner "result"
if ((failures)); then
	printf '  \033[31m%d check(s) failed\033[0m\n\n' "$failures"
	exit 1
fi
printf '  \033[32mtemplate verified\033[0m\n\n'
