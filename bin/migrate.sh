#!/usr/bin/env bash
# shellcheck disable=SC1091

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$MIGRATION_ROOT/lib/common.sh"
source "$MIGRATION_ROOT/lib/compatibility.sh"
source "$MIGRATION_ROOT/lib/preflight.sh"
source "$MIGRATION_ROOT/lib/assemble.sh"
source "$MIGRATION_ROOT/lib/archive.sh"
source "$MIGRATION_ROOT/lib/load.sh"
source "$MIGRATION_ROOT/lib/sanitize.sh"
source "$MIGRATION_ROOT/lib/validate.sh"
source "$MIGRATION_ROOT/lib/representations.sh"
source "$MIGRATION_ROOT/lib/spells.sh"

usage() {
    cat <<'EOF'
Usage:
  migrate.sh --config FILE COMMAND

Commands:
  compatibility    Verify protected repository content without using MySQL
  preflight        Verify compatibility/server/source state and capture schemas
  assemble         Build fresh native target-core schemas
  archive-unsupported
                   Archive approved source-only data and enforce its gate
  load-auth        Migrate approved auth mappings
  load-characters  Migrate approved character mappings
  sanitize-target  Remove approved source-existing orphan data from targets
  validate         Run structural and domain integrity checks
  status           Show phase and chunk checkpoints
  report           Regenerate the final migration report
EOF
}

CONFIG_PATH=
if [[ ${1:-} == --config ]]; then
    [[ $# -ge 3 ]] || {
        usage
        exit 2
    }
    CONFIG_PATH=$2
    shift 2
fi

COMMAND=${1:-}
[[ -n $CONFIG_PATH && -n $COMMAND ]] || {
    usage
    exit 2
}

trap cleanup_compatibility_state EXIT
load_configuration "$CONFIG_PATH"

if [[ $COMMAND == compatibility ]]; then
    compatibility_report="$REPORTS_DIR/compatibility/$(date -u +'%Y%m%dT%H%M%SZ')-$$.tsv"
    verify_repository_compatibility "$compatibility_report"
    log "Wrote $compatibility_report"
    exit 0
fi

create_run_id
verify_repository_compatibility "$REPORTS_DIR/$RUN_ID/compatibility-report.tsv"
initialize_control_schema
verify_run_configuration
verify_spell_snapshot_if_present

case "$COMMAND" in
    preflight)
        with_phase preflight perform_preflight
        ;;
    assemble)
        with_phase assemble perform_assemble
        ;;
    archive-unsupported)
        with_phase archive-unsupported perform_archive_unsupported
        ;;
    load-auth)
        with_phase load-auth perform_load auth
        ;;
    load-characters)
        with_phase load-characters perform_load characters
        ;;
    sanitize-target)
        with_phase sanitize-target perform_sanitize_target
        ;;
    validate)
        with_phase validate perform_validation
        ;;
    status)
        show_status
        ;;
    report)
        write_final_report
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage
        die "Unknown command: $COMMAND"
        ;;
esac
