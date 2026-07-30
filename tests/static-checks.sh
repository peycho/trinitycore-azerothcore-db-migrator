#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$(cd "$ROOT/.." && pwd)"

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

rg '^CREATE TABLE' "$WORKSPACE/TrinityCore/sql/base/auth_database.sql" |
    sed -E 's/^CREATE TABLE `([^`]+)`.*/\1/' | sort > "$temporary_dir/tc-auth"
cut -d, -f1 "$ROOT/mappings/auth.csv" | tail -n +2 | tr '+' '\n' |
    sed '/^-/d;/^$/d' | sort -u > "$temporary_dir/map-tc-auth"
find "$WORKSPACE/azerothcore-wotlk/data/sql/base/db_auth" -maxdepth 1 -name '*.sql' -printf '%f\n' |
    sed 's/\.sql$//' | sort > "$temporary_dir/ac-auth"
cut -d, -f2 "$ROOT/mappings/auth.csv" | tail -n +2 |
    sed '/^-/d;/^$/d' | sort -u > "$temporary_dir/map-ac-auth"

rg '^CREATE TABLE' "$WORKSPACE/TrinityCore/sql/base/characters_database.sql" |
    sed -E 's/^CREATE TABLE `([^`]+)`.*/\1/' | sort > "$temporary_dir/tc-characters"
cut -d, -f1 "$ROOT/mappings/characters.csv" | tail -n +2 | tr '+' '\n' |
    sed '/^-/d;/^$/d' | sort -u > "$temporary_dir/map-tc-characters"
find "$WORKSPACE/azerothcore-wotlk/data/sql/base/db_characters" -maxdepth 1 -name '*.sql' -printf '%f\n' |
    sed 's/\.sql$//' | sort > "$temporary_dir/ac-characters"
cut -d, -f2 "$ROOT/mappings/characters.csv" | tail -n +2 |
    sed '/^-/d;/^$/d' | sort -u > "$temporary_dir/map-ac-characters"

compare_inventory "$temporary_dir/tc-auth" "$temporary_dir/map-tc-auth" "TrinityCore auth"
compare_inventory "$temporary_dir/ac-auth" "$temporary_dir/map-ac-auth" "AzerothCore auth"
compare_inventory "$temporary_dir/tc-characters" "$temporary_dir/map-tc-characters" "TrinityCore characters"
compare_inventory "$temporary_dir/ac-characters" "$temporary_dir/map-ac-characters" "AzerothCore characters"

printf 'Static checks passed.\n'
