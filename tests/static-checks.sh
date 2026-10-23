#!/usr/bin/env bash
# shellcheck disable=SC2016

set -Eeuo pipefail
export LC_ALL=C

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRINITYCORE_DIR=${TRINITYCORE_DIR:-"$ROOT/../TrinityCore"}
AZEROTHCORE_DIR=${AZEROTHCORE_DIR:-"$ROOT/../azerothcore-wotlk"}
TRINITYCORE_DIR=$(realpath -e "$TRINITYCORE_DIR")
AZEROTHCORE_DIR=$(realpath -e "$AZEROTHCORE_DIR")
export TRINITYCORE_DIR AZEROTHCORE_DIR
export COMPATIBILITY_PROFILE=${COMPATIBILITY_PROFILE:-tc335-acwotlk-v2}
# shellcheck source=tests/test-support.sh
source "$ROOT/tests/test-support.sh"

[[ -f "$TRINITYCORE_DIR/sql/base/auth_database.sql" ]] || {
    printf 'TrinityCore SQL checkout not found: %s\n' "$TRINITYCORE_DIR" >&2
    exit 1
}
[[ -d "$AZEROTHCORE_DIR/data/sql/base/db_auth" ]] || {
    printf 'AzerothCore SQL checkout not found: %s\n' "$AZEROTHCORE_DIR" >&2
    exit 1
}

shellcheck "$ROOT"/bin/*.sh "$ROOT"/lib/*.sh "$ROOT"/tests/*.sh
python3 "$ROOT/tests/spell-state-tests.py"
python3 "$ROOT/tests/source-audit-tests.py"
python3 "$ROOT/tests/talent-cleanup-tests.py"
python3 "$ROOT/tests/cleanup-console-tests.py"
python3 "$ROOT/tests/skill-cleanup-tests.py"
python3 "$ROOT/tests/native-skill-tests.py"
python3 "$ROOT/tests/active-talent-reset-tests.py"
python3 "$ROOT/tests/spell-history-tests.py"
python3 "$ROOT/tests/disabled-history-tests.py"
python3 "$ROOT/tests/talent-relations-tests.py"
python3 "$ROOT/tests/selected-rank-history-tests.py"
python3 "$ROOT/tests/migration-evidence-tests.py"
python3 "$ROOT/tests/trained-history-tests.py"
python3 "$ROOT/tests/ordinary-history-tests.py"
python3 "$ROOT/tests/death-coil-repair-tests.py"
python3 "$ROOT/tests/talent-ownership-tests.py"
python3 "$ROOT/tests/shaman-dual-wield-tests.py"
python3 "$ROOT/tests/skill-teaching-tests.py"
python3 "$ROOT/tests/profession-activation-tests.py"
python3 "$ROOT/tests/specialization-tests.py"
python3 "$ROOT/tests/aura-alias-tests.py"
python3 "$ROOT/tests/passive-rekey-tests.py"
python3 "$ROOT/tests/inactive-passive-tests.py"
python3 "$ROOT/tests/inactive-legacy-tests.py"
python3 "$ROOT/tests/selected-passive-tests.py"
python3 "$ROOT/tests/spell-eligibility-tests.py"
python3 "$ROOT/tests/racial-eligibility-tests.py"
python3 "$ROOT/tests/pet-teaching-tests.py"

for mapping in "$ROOT"/mappings/{tc-to-ac,ac-to-tc}/{auth,characters}.csv; do
    awk -F, 'NF != 10 { print FILENAME ":" FNR ": expected 10 CSV fields, found " NF; bad=1 }
        END { exit bad }' "$mapping"
done
for objects in "$ROOT"/mappings/{tc-to-ac,ac-to-tc}/objects.csv; do
    awk -F, 'NF != 7 { print FILENAME ":" FNR ": expected 7 CSV fields, found " NF; bad=1 }
        END { exit bad }' "$objects"
done

compare_inventory() {
    local expected=$1
    local actual=$2
    local label=$3
    local difference
    difference=$(comm -3 "$expected" "$actual")
    [[ -z $difference ]] || {
        printf '%s mapping inventory mismatch:\n%s\n' "$label" "$difference" >&2
        return 1
    }
}

temporary_dir=$(mktemp -d)
trap 'rm -rf "$temporary_dir"' EXIT

rg '^CREATE TABLE' "$TRINITYCORE_DIR/sql/base/auth_database.sql" |
    sed -E 's/^CREATE TABLE `([^`]+)`.*/\1/' | sort > "$temporary_dir/tc-auth"
find "$AZEROTHCORE_DIR/data/sql/base/db_auth" -maxdepth 1 -name '*.sql' -printf '%f\n' |
    sed 's/\.sql$//' | sort > "$temporary_dir/ac-auth"

rg '^CREATE TABLE' "$TRINITYCORE_DIR/sql/base/characters_database.sql" |
    sed -E 's/^CREATE TABLE `([^`]+)`.*/\1/' | sort > "$temporary_dir/tc-characters"
find "$AZEROTHCORE_DIR/data/sql/base/db_characters" -maxdepth 1 -name '*.sql' -printf '%f\n' |
    sed 's/\.sql$//' | sort > "$temporary_dir/ac-characters"

profile="$ROOT/compatibility/$COMPATIBILITY_PROFILE"
cmp "$temporary_dir/tc-auth" "$profile/trinitycore-auth.tables"
cmp "$temporary_dir/tc-characters" "$profile/trinitycore-characters.tables"
cmp "$temporary_dir/ac-auth" "$profile/azerothcore-auth.tables"
cmp "$temporary_dir/ac-characters" "$profile/azerothcore-characters.tables"

mapping_inventory() {
    local mapping=$1 column=$2 destination=$3
    awk -F, -v column="$column" '
        NR>1 && !(column==1 && $2=="-" && $8=="BLOCKED") { print $column }
    ' "$mapping" |
        tr '+' '\n' | sed '/^-/d;/^$/d' | sort -u > "$destination"
}

for direction in tc-to-ac ac-to-tc; do
    if [[ $direction == tc-to-ac ]]; then
        source_prefix=tc
        target_prefix=ac
    else
        source_prefix=ac
        target_prefix=tc
    fi
    for kind in auth characters; do
        mapping="$ROOT/mappings/$direction/$kind.csv"
        mapping_inventory "$mapping" 1 "$temporary_dir/map-source"
        mapping_inventory "$mapping" 2 "$temporary_dir/map-target"
        compare_inventory "$temporary_dir/$source_prefix-$kind" \
            "$temporary_dir/map-source" "$direction source $kind"
        compare_inventory "$temporary_dir/$target_prefix-$kind" \
            "$temporary_dir/map-target" "$direction target $kind"
    done
done

for variable in MIGRATION_DIRECTION COMPATIBILITY_PROFILE ARCHIVE_DIR ALLOW_SOURCE_ARCHIVE \
    ALLOW_GAMEPLAY_ARCHIVE LOAD_CHUNK_SIZE CLEANUP_CHUNK_SIZE \
    LARGE_TABLE_ROWS DEFER_SECONDARY_INDEXES; do
    rg -q "^${variable}=" "$ROOT/config/migration.env.example" ||
        {
            printf 'Missing performance configuration: %s\n' "$variable" >&2
            exit 1
        }
done
! rg -q '^EXPECTED_(TRINITYCORE|AZEROTHCORE)_COMMIT=' "$ROOT/config" "$ROOT/tests" ||
    {
        printf 'Exact upstream commits must not be operator configuration.\n' >&2
        exit 1
    }
prepare_test_toolkit "$temporary_dir/toolkit"
write_test_config "$temporary_dir/migration.env" "$TRINITYCORE_DIR" "$AZEROTHCORE_DIR"
"$temporary_dir/toolkit/bin/migrate.sh" --config "$temporary_dir/migration.env" compatibility
"$ROOT/tests/compatibility-profile-tests.sh"
"$ROOT/tests/schema-dump-tests.sh"
if MIGRATOR_DISPOSABLE_MYSQL=1 REHEARSAL_MYSQL_PORT=03306 \
    "$ROOT/tests/rehearsal-tests.sh" > "$temporary_dir/port-guard.txt" 2>&1; then
    printf 'Rehearsal accepted a production-port alias\n' >&2
    exit 1
fi
rg -q 'non-production port' "$temporary_dir/port-guard.txt"
! rg -q '(^|[^A-Z_])CHUNK_SIZE=' "$ROOT/config" "$ROOT/tests" \
    --glob '*.env' --glob '*.env.example' ||
    {
        printf 'Legacy CHUNK_SIZE configuration is not allowed.\n' >&2
        exit 1
    }
rg -q 'CREATE TABLE IF NOT EXISTS .*operation_checkpoint' \
    "$ROOT/sql/00_control_schema.sql"
rg -Fq '`run_uuid` binary(16)' "$ROOT/sql/00_control_schema.sql"
rg -Fq "\"--init-command=SET SESSION time_zone='+00:00'\"" \
    "$ROOT/lib/common.sh"
! rg -q 'EXISTS .*character_inventory' "$ROOT/lib/sanitize.sh" ||
    {
        printf 'Correlated item reachability query has returned.\n' >&2
        exit 1
    }

printf 'Static checks passed.\n'
