#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRINITYCORE_DIR=${TRINITYCORE_DIR:-"$ROOT/../TrinityCore"}
AZEROTHCORE_DIR=${AZEROTHCORE_DIR:-"$ROOT/../azerothcore-wotlk"}

[[ -f "$TRINITYCORE_DIR/sql/base/auth_database.sql" ]] || {
    printf 'TrinityCore SQL checkout not found: %s\n' "$TRINITYCORE_DIR" >&2
    exit 1
}
[[ -d "$AZEROTHCORE_DIR/data/sql/base/db_auth" ]] || {
    printf 'AzerothCore SQL checkout not found: %s\n' "$AZEROTHCORE_DIR" >&2
    exit 1
}

shellcheck "$ROOT/bin/migrate.sh" "$ROOT"/lib/*.sh

for mapping in "$ROOT"/mappings/auth.csv "$ROOT"/mappings/characters.csv; do
    awk -F, 'NF != 10 { print FILENAME ":" FNR ": expected 10 CSV fields, found " NF; bad=1 }
        END { exit bad }' "$mapping"
done
awk -F, 'NF != 7 { print FILENAME ":" FNR ": expected 7 CSV fields, found " NF; bad=1 }
    END { exit bad }' "$ROOT/mappings/objects.csv"

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
awk -F, 'NR > 1 && !($2 == "-" && $8 == "BLOCKED") { print $1 }' \
    "$ROOT/mappings/auth.csv" | tr '+' '\n' |
    sed '/^-/d;/^$/d' | sort -u > "$temporary_dir/map-tc-auth"
find "$AZEROTHCORE_DIR/data/sql/base/db_auth" -maxdepth 1 -name '*.sql' -printf '%f\n' |
    sed 's/\.sql$//' | sort > "$temporary_dir/ac-auth"
cut -d, -f2 "$ROOT/mappings/auth.csv" | tail -n +2 |
    sed '/^-/d;/^$/d' | sort -u > "$temporary_dir/map-ac-auth"

rg '^CREATE TABLE' "$TRINITYCORE_DIR/sql/base/characters_database.sql" |
    sed -E 's/^CREATE TABLE `([^`]+)`.*/\1/' | sort > "$temporary_dir/tc-characters"
awk -F, 'NR > 1 && !($2 == "-" && $8 == "BLOCKED") { print $1 }' \
    "$ROOT/mappings/characters.csv" | tr '+' '\n' |
    sed '/^-/d;/^$/d' | sort -u > "$temporary_dir/map-tc-characters"
find "$AZEROTHCORE_DIR/data/sql/base/db_characters" -maxdepth 1 -name '*.sql' -printf '%f\n' |
    sed 's/\.sql$//' | sort > "$temporary_dir/ac-characters"
cut -d, -f2 "$ROOT/mappings/characters.csv" | tail -n +2 |
    sed '/^-/d;/^$/d' | sort -u > "$temporary_dir/map-ac-characters"

compare_inventory "$temporary_dir/tc-auth" "$temporary_dir/map-tc-auth" "TrinityCore auth"
compare_inventory "$temporary_dir/ac-auth" "$temporary_dir/map-ac-auth" "AzerothCore auth"
compare_inventory "$temporary_dir/tc-characters" "$temporary_dir/map-tc-characters" "TrinityCore characters"
compare_inventory "$temporary_dir/ac-characters" "$temporary_dir/map-ac-characters" "AzerothCore characters"

for variable in LOAD_CHUNK_SIZE CLEANUP_CHUNK_SIZE LARGE_TABLE_ROWS DEFER_SECONDARY_INDEXES; do
    rg -q "^${variable}=" "$ROOT/config/migration.env.example" ||
        {
            printf 'Missing performance configuration: %s\n' "$variable" >&2
            exit 1
        }
done
! rg -q '(^|[^A-Z_])CHUNK_SIZE=' "$ROOT/config" "$ROOT/tests" \
    --glob '*.env' --glob '*.env.example' ||
    {
        printf 'Legacy CHUNK_SIZE configuration is not allowed.\n' >&2
        exit 1
    }
rg -q 'CREATE TABLE IF NOT EXISTS .*operation_checkpoint' \
    "$ROOT/sql/00_control_schema.sql"
rg -Fq '`run_uuid` binary(16)' "$ROOT/sql/00_control_schema.sql"
! rg -q 'EXISTS .*character_inventory' "$ROOT/lib/sanitize.sh" ||
    {
        printf 'Correlated item reachability query has returned.\n' >&2
        exit 1
    }

printf 'Static checks passed.\n'
