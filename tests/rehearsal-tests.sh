#!/usr/bin/env bash
# The selected server must be disposable; no production endpoint is accepted.
set -Eeuo pipefail
export LC_ALL=C
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export COMPATIBILITY_PROFILE=${COMPATIBILITY_PROFILE:-tc335-acwotlk-v2}
TRINITYCORE_DIR=$(realpath -e "${TRINITYCORE_DIR:-$ROOT/../TrinityCore}")
AZEROTHCORE_DIR=$(realpath -e "${AZEROTHCORE_DIR:-$ROOT/../azerothcore-wotlk}")
export TRINITYCORE_DIR AZEROTHCORE_DIR
export REHEARSAL_MYSQL_PORT=${REHEARSAL_MYSQL_PORT:-33317}
if [[ ${MIGRATOR_DISPOSABLE_MYSQL:-} == 1 && $REHEARSAL_MYSQL_PORT =~ ^[0-9]{1,5}$ ]] &&
    (( 10#$REHEARSAL_MYSQL_PORT >= 1 && 10#$REHEARSAL_MYSQL_PORT <= 65535 &&
       10#$REHEARSAL_MYSQL_PORT != 3306 )); then
    REHEARSAL_MYSQL_PORT=$((10#$REHEARSAL_MYSQL_PORT))
else
    printf 'Set MIGRATOR_DISPOSABLE_MYSQL=1 for an isolated localhost MySQL on a non-production port\n' >&2
    exit 1
fi
# shellcheck source=tests/test-support.sh
source "$ROOT/tests/test-support.sh"
python3 "$ROOT/tests/talent-runtime-tests.py" "$AZEROTHCORE_DIR"
python3 "$ROOT/tests/research-load-tests.py" "$TRINITYCORE_DIR" "$AZEROTHCORE_DIR"
python3 "$ROOT/tests/runeforging-script-tests.py" "$TRINITYCORE_DIR"
python3 "$ROOT/tests/nurturing-instinct-tests.py" "$TRINITYCORE_DIR" "$AZEROTHCORE_DIR"
python3 "$ROOT/tests/skill-reward-tests.py" "$TRINITYCORE_DIR" "$AZEROTHCORE_DIR"
python3 "$ROOT/tests/reviewed-script-tests.py" "$TRINITYCORE_DIR" "$AZEROTHCORE_DIR"
python3 "$ROOT/tests/temporary-rank-tests.py" "$TRINITYCORE_DIR" "$AZEROTHCORE_DIR"
python3 "$ROOT/tests/spell-metadata-tests.py"
python3 "$ROOT/tests/source-audit-mysql-tests.py"
python3 "$ROOT/tests/talent-cleanup-mysql-tests.py"
python3 "$ROOT/tests/native-talent-reset-tests.py" "$TRINITYCORE_DIR"
python3 "$ROOT/tests/character-talent-reset-mysql-tests.py"
python3 "$ROOT/tests/active-talent-reset-mysql-tests.py"
python3 "$ROOT/tests/cleanup-console-mysql-tests.py"
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
prepare_test_toolkit "$TEST_ROOT/toolkit"
python3 "$ROOT/tests/rehearsal-tests.py" "$ROOT" "$TEST_ROOT"
