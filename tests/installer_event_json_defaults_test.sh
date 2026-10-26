#!/usr/bin/env bash
# Regression tests for JSON defaults in installer/events.sh.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT}/installer/events.sh"

assert_json_object() {
    local label="$1" input="$2"
    if ! jq -e 'type == "object"' >/dev/null <<<"$input"; then
        echo "FAIL: $label is not a JSON object" >&2
        exit 1
    fi
}

# The previous ${1:-{}} expansion appended an extra brace to supplied JSON.
install_event_validate_data '{"version":"25460313"}'
install_event_validate_data '{}'
install_event_validate_data

if install_event_validate_data '{"broken":' >/dev/null 2>&1; then
    echo "FAIL: invalid JSON was accepted" >&2
    exit 1
fi
if install_event_validate_data '[]' >/dev/null 2>&1; then
    echo "FAIL: array payload was accepted" >&2
    exit 1
fi

# Stub only the external publication dependencies: no database writes.
install_event_engine_available() { return 0; }
install_event_node_id() { printf 'test-node\n'; }
install_operation_from_event() {
    local type="$1" game="$2" provider="$3" node="$4" payload="$5"
    [[ "$game" == dayz && "$provider" == steam && "$node" == test-node ]] || return 1
    assert_json_object "$type" "$payload"
    jq -e --arg type "$type" '.provider == "steam" and .game_id == "dayz"' >/dev/null <<<"$payload"
}
export DSM_ROOT="$ROOT"
unset DSM_DATABASE_DRIVER
# Avoid DB publishing even when the source tree has a config file.
# Instead, invoke the validation/enrichment path with a temporary DSM root.
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/database"
: > "$tmp/database/universal_events_cli.py"
DSM_ROOT="$tmp"

for event in INSTALL_STARTED INSTALL_COMPLETED INSTALL_FAILED UPDATE_STARTED UPDATE_COMPLETED UPDATE_FAILED ROLLBACK_STARTED ROLLBACK_COMPLETED ROLLBACK_FAILED INSTALL_VALIDATION_FAILED; do
    install_event_emit "$event" dayz steam '{"version":"25460313"}'
done
install_event_emit INSTALL_STARTED dayz steam

echo "PASS: installer event JSON defaults and event types"
