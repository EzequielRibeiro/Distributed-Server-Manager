#!/usr/bin/env bash
# Never call this on a real DSM installation. Calls the ACTUAL update.sh main()
# on a tiny fake install after replacing all external/service-facing hooks.
set -Eeuo pipefail
[[ $# -eq 3 ]] || exit 2
ROOT="$1"; UPDATER="$2"; MODE="$3"
[[ "$MODE" =~ ^(success|fail_after_apply|no_drain_success|no_drain_fail_after_apply|no_drain_drift|no_drain_unknown_file|no_drain_no_env)$ ]] || exit 2
[[ -d "$ROOT" && ! -L "$ROOT" && -f "$ROOT/fixture-owner" ]] || exit 2
[[ "$(cat "$ROOT/fixture-owner")" == DSM928_DISPOSABLE_FIXTURE_V1 ]] || exit 2
ROOT="$(realpath -e -- "$ROOT")"
case "$ROOT" in /tmp/*) ;; *) exit 2 ;; esac
[[ -f "$UPDATER" && ! -L "$UPDATER" && "$(basename "$UPDATER")" == update.sh ]] || exit 2
UPDATER="$(realpath -e -- "$UPDATER")"
# GitHub-hosted runners check out the same reviewed source under /home/runner/work.
# This grants READ access to the checked-out updater, never to its install root.
case "$UPDATER" in
  /tmp/*) ;;
  /home/runner/work/*)
    [[ -f "$(dirname "$UPDATER")/tests/update_game_uptime_main_path_test.py" ]] || exit 2
    ;;
  *) exit 2 ;;
esac
[[ ! -e /tmp/dsm928-unsafe-marker-should-not-exist ]] || exit 2
# Reject paths where an attacker tries to make the sandbox point into /opt.
for path in "$ROOT/installed" "$ROOT/new-payload"; do
  [[ -d "$path" && ! -L "$path" ]] || exit 2
  [[ "$(realpath -e -- "$path")" == "$ROOT/"* ]] || exit 2
done
source "$UPDATER"  # source guard skips main(), registers ERR trap

INSTALL_DIR="$ROOT/installed"
CONFIG_FILE="$INSTALL_DIR/config/dsm.conf"
LOG_DIR="$INSTALL_DIR/logs"
INSTALL_LOG="$LOG_DIR/update.log"
STAGING_DIR="$ROOT/staging"
BACKUP_DIR="$ROOT/backups"
SYSTEMD_DIR="$ROOT/fake-systemd"
CAP_LINK="$ROOT/fake-cap-link"
DSM_USER=""
DSM_GROUP=""
SYSTEMD_ENABLED=0
ACTIVE_GAME_UNITS=()
RESTORE_SERVICES=()
mkdir -p "$BACKUP_DIR" "$SYSTEMD_DIR"

# New #928 entrypoint is reached through the REAL update.sh main(), but it
# runs only the Python disposable transaction and actual file functions.
# No production-facing function is stubbed or invoked in this branch.
if [[ "$MODE" == no_drain_* ]]; then
    [[ ! -e "$ROOT/steps" ]] || exit 2
    if [[ "$MODE" != no_drain_no_env ]]; then
        export CAPIVARA_DSM928_DISPOSABLE_MAIN=1
    else
        unset CAPIVARA_DSM928_DISPOSABLE_MAIN
    fi
    export GITHUB_ACTIONS=true RUNNER_ENVIRONMENT=github-hosted
    case "$MODE" in
        no_drain_fail_after_apply) export DSM928_DISPOSABLE_MODE=fail_after_apply ;;
        *) export DSM928_DISPOSABLE_MODE=success ;;
    esac
    main --dsm928-disposable-no-drain-main "$ROOT/new-payload"
    exit $?
fi

# Anything that would interact with production services or credentials is stubbed.
# File functions, version enforcement, actual main() ordering, and rollback are REAL.
require_root() { :; }
initialize_logging() { :; }
load_configuration() { :; }
validate_runtime_account() { :; }
check_internet() { :; }
run_process_guard() { printf 'guard:%s\n' "${1:-strict}" >> "$ROOT/steps"; }
capture_game_instance_state() { printf 'capture-games\n' >> "$ROOT/steps"; }
capture_service_state() { printf 'capture-services\n' >> "$ROOT/steps"; }
stop_services() { printf 'stop-controller\n' >> "$ROOT/steps"; }
stop_game_instances() { printf 'stop-games\n' >> "$ROOT/steps"; }
restart_services() { printf 'start-controller\n' >> "$ROOT/steps"; }
restart_game_instances() { printf 'start-games\n' >> "$ROOT/steps"; }
create_database_backup() { printf 'backup-database-stub\n' >> "$ROOT/steps"; }
restore_database_backup() { printf 'restore-database-stub\n' >> "$ROOT/steps"; }
fix_permissions() { :; }
install_command() { :; }
update_systemd() { :; }
reconcile_hybrid_runtime_substrate() { :; }
validate_runtime_readiness() { :; }
check_services() { :; }
prune_update_backups() { :; }
collect_failure_diagnostics() { :; }
# Exercise real read_versions, SEMVER, check_disk, snapshot, staging/swap,
# config migration and validate_final_installation. Database migration is the
# fault injection point because only sqlite-fixture.txt exists here.
migrate_database() {
    printf 'migrate-database-stub\n' >> "$ROOT/steps"
    if [[ "$MODE" == fail_after_apply ]]; then return 92; fi
}
# Prevent any external process management even if a rollback changes route.
systemctl() {
    if [[ "${1:-}" == daemon-reload && $# == 1 ]]; then
        printf 'stub-daemon-reload\n' >> "$ROOT/steps"
        return 0
    fi
    printf 'UNEXPECTED-SYSTEMCTL\n' >> "$ROOT/steps"
    return 98
}

# Actual main() with --yes, not a synthetic manually ordered list of functions.
main --yes "$ROOT/new-payload"
