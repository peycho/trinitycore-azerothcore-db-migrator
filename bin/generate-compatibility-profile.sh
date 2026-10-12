#!/usr/bin/env bash
# Generates an unapproved review candidate. It never edits the checked-in
# compatibility directory and never grants production approval.
# shellcheck disable=SC1091,SC2016

set -Eeuo pipefail
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$MIGRATION_ROOT/lib/common.sh"
source "$MIGRATION_ROOT/lib/compatibility.sh"

usage() {
    printf 'Usage: %s TRINITYCORE_DIR AZEROTHCORE_DIR PROFILE_ID OUTPUT_DIR\n' "$0" >&2
}

[[ $# == 4 ]] || {
    usage
    exit 2
}

TRINITYCORE_DIR=$(realpath -e "$1")
AZEROTHCORE_DIR=$(realpath -e "$2")
candidate_id=$3
output_parent=$(realpath -m "$4")
[[ $candidate_id =~ ^[A-Za-z0-9._-]+$ ]] || die "PROFILE_ID contains unsafe characters"
[[ $output_parent != "$MIGRATION_ROOT" && $output_parent != "$MIGRATION_ROOT"/* ]] ||
    die "Candidate output must be outside the repository"
[[ -d $TRINITYCORE_DIR/sql && -d $AZEROTHCORE_DIR/data/sql ]] ||
    die "Both core SQL trees are required"

candidate_dir="$output_parent/$candidate_id"
[[ ! -e $candidate_dir ]] || die "Candidate output already exists: $candidate_dir"
mkdir -p "$candidate_dir"
chmod 0700 "$candidate_dir"

write_path_manifest "$TRINITYCORE_DIR" "$candidate_dir/trinitycore-sql.sha256" sql \
    sql/base/auth_database.sql sql/base/characters_database.sql \
    sql/updates/auth/3.3.5 sql/updates/characters/3.3.5
write_path_manifest "$AZEROTHCORE_DIR" "$candidate_dir/azerothcore-sql.sha256" sql \
    data/sql/base/db_auth data/sql/base/db_characters \
    data/sql/updates/db_auth data/sql/updates/db_characters
write_trinitycore_semantic_manifest "$candidate_dir/trinitycore-semantic.sha256"
write_azerothcore_semantic_manifest "$candidate_dir/azerothcore-semantic.sha256"

rg '^CREATE TABLE' "$TRINITYCORE_DIR/sql/base/auth_database.sql" |
    sed -E 's/^CREATE TABLE `([^`]+)`.*/\1/' | LC_ALL=C sort > "$candidate_dir/trinitycore-auth.tables"
rg '^CREATE TABLE' "$TRINITYCORE_DIR/sql/base/characters_database.sql" |
    sed -E 's/^CREATE TABLE `([^`]+)`.*/\1/' | LC_ALL=C sort > "$candidate_dir/trinitycore-characters.tables"
find "$AZEROTHCORE_DIR/data/sql/base/db_auth" -maxdepth 1 -type f -name '*.sql' -printf '%f\n' |
    sed 's/\.sql$//' | LC_ALL=C sort > "$candidate_dir/azerothcore-auth.tables"
find "$AZEROTHCORE_DIR/data/sql/base/db_characters" -maxdepth 1 -type f -name '*.sql' -printf '%f\n' |
    sed 's/\.sql$//' | LC_ALL=C sort > "$candidate_dir/azerothcore-characters.tables"

tc_revision=$(git -C "$TRINITYCORE_DIR" rev-parse HEAD)
ac_revision=$(git -C "$AZEROTHCORE_DIR" rev-parse HEAD)
profile_file="$candidate_dir/profile.env"
{
    printf 'PROFILE_FORMAT=2\n'
    printf 'PROFILE_ID=%s\n' "$candidate_id"
    printf 'PROFILE_APPROVAL=UNREVIEWED\n'
    printf 'REVIEWED_TRINITYCORE_REVISION=%s\n' "$tc_revision"
    printf 'REVIEWED_AZEROTHCORE_REVISION=%s\n' "$ac_revision"
    printf 'TRINITYCORE_SQL_MANIFEST=trinitycore-sql.sha256\n'
    printf 'TRINITYCORE_SEMANTIC_MANIFEST=trinitycore-semantic.sha256\n'
    printf 'AZEROTHCORE_SQL_MANIFEST=azerothcore-sql.sha256\n'
    printf 'AZEROTHCORE_SEMANTIC_MANIFEST=azerothcore-semantic.sha256\n'
    printf 'TRINITYCORE_AUTH_TABLES=trinitycore-auth.tables\n'
    printf 'TRINITYCORE_CHARACTERS_TABLES=trinitycore-characters.tables\n'
    printf 'AZEROTHCORE_AUTH_TABLES=azerothcore-auth.tables\n'
    printf 'AZEROTHCORE_CHARACTERS_TABLES=azerothcore-characters.tables\n'
} > "$profile_file"
chmod 0600 "$candidate_dir"/*
log "Generated unapproved candidate profile at $candidate_dir"
