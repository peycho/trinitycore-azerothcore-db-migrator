#!/usr/bin/env bash

set -Eeuo pipefail

MIGRATION_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORTS_DIR="$MIGRATION_ROOT/reports"
VAR_DIR="$MIGRATION_ROOT/var"

log() {
    printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

die() {
    log "ERROR: $*"
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

validate_identifier() {
    local value=$1
    local label=$2
    [[ $value =~ ^[A-Za-z0-9_]+$ ]] || die "$label is not a safe MySQL identifier: $value"
}

absolute_path() {
    local path=$1
    if [[ $path = /* ]]; then
        printf '%s\n' "$path"
    else
        printf '%s\n' "$(cd "$MIGRATION_ROOT" && realpath -m "$path")"
    fi
}

load_configuration() {
    local config_file=$1
    [[ -r $config_file ]] || die "Configuration is not readable: $config_file"

    # shellcheck disable=SC1090
    source "$config_file"

    local required=(
        MYSQL_HOST MYSQL_PORT MYSQL_USER SOURCE_AUTH_SCHEMA
        SOURCE_CHARACTERS_SCHEMA TARGET_AUTH_SCHEMA TARGET_CHARACTERS_SCHEMA
        CONTROL_SCHEMA REALM_ID TRINITYCORE_DIR AZEROTHCORE_DIR
        EXPECTED_TRINITYCORE_COMMIT EXPECTED_AZEROTHCORE_COMMIT CHUNK_SIZE
    )
    local name
    for name in "${required[@]}"; do
        [[ -n ${!name:-} ]] || die "Missing required configuration: $name"
    done

    MYSQL_DEFAULTS_FILE=${MYSQL_DEFAULTS_FILE:-}
    MYSQL_SOCKET=${MYSQL_SOCKET:-}
    SOURCE_WORLD_SCHEMA=${SOURCE_WORLD_SCHEMA:-}
    REQUIRE_QUIESCENT=${REQUIRE_QUIESCENT:-1}
    ALLOW_SOURCE_ARCHIVE=${ALLOW_SOURCE_ARCHIVE:-1}
    MIGRATION_RUN_ID=${MIGRATION_RUN_ID:-}

    validate_identifier "$SOURCE_AUTH_SCHEMA" SOURCE_AUTH_SCHEMA
    validate_identifier "$SOURCE_CHARACTERS_SCHEMA" SOURCE_CHARACTERS_SCHEMA
    validate_identifier "$TARGET_AUTH_SCHEMA" TARGET_AUTH_SCHEMA
    validate_identifier "$TARGET_CHARACTERS_SCHEMA" TARGET_CHARACTERS_SCHEMA
    validate_identifier "$CONTROL_SCHEMA" CONTROL_SCHEMA
    [[ $REALM_ID =~ ^[0-9]+$ ]] || die "REALM_ID must be a non-negative integer"
    if [[ -n $SOURCE_WORLD_SCHEMA ]]; then
        validate_identifier "$SOURCE_WORLD_SCHEMA" SOURCE_WORLD_SCHEMA
    fi
    [[ $CHUNK_SIZE =~ ^[1-9][0-9]*$ ]] || die "CHUNK_SIZE must be a positive integer"
    [[ $REQUIRE_QUIESCENT =~ ^[01]$ ]] || die "REQUIRE_QUIESCENT must be 0 or 1"
    [[ $ALLOW_SOURCE_ARCHIVE =~ ^[01]$ ]] || die "ALLOW_SOURCE_ARCHIVE must be 0 or 1"

    TRINITYCORE_DIR=$(absolute_path "$TRINITYCORE_DIR")
    AZEROTHCORE_DIR=$(absolute_path "$AZEROTHCORE_DIR")
    [[ -d $TRINITYCORE_DIR/sql ]] || die "TrinityCore SQL tree not found: $TRINITYCORE_DIR"
    [[ -d $AZEROTHCORE_DIR/data/sql ]] || die "AzerothCore SQL tree not found: $AZEROTHCORE_DIR"

    mkdir -p "$REPORTS_DIR" "$VAR_DIR"
    TOOLKIT_HASH=$(
        find "$MIGRATION_ROOT/bin" "$MIGRATION_ROOT/lib" "$MIGRATION_ROOT/sql" \
            "$MIGRATION_ROOT/mappings" -type f -print |
            LC_ALL=C sort |
            xargs sha256sum |
            sha256sum |
            awk '{print $1}'
    )
    CONFIG_HASH=$(
        printf '%s\n' \
            "$MYSQL_HOST" "$MYSQL_PORT" "$MYSQL_SOCKET" \
            "$SOURCE_AUTH_SCHEMA" "$SOURCE_CHARACTERS_SCHEMA" "$SOURCE_WORLD_SCHEMA" \
            "$TARGET_AUTH_SCHEMA" "$TARGET_CHARACTERS_SCHEMA" "$CONTROL_SCHEMA" \
            "$REALM_ID" "$EXPECTED_TRINITYCORE_COMMIT" "$EXPECTED_AZEROTHCORE_COMMIT" \
            "$CHUNK_SIZE" "$TOOLKIT_HASH" |
            sha256sum | awk '{print $1}'
    )

    build_mysql_arguments
}

build_mysql_arguments() {
    MYSQL_ARGS=()
    MYSQLDUMP_ARGS=()
    if [[ -n $MYSQL_DEFAULTS_FILE ]]; then
        [[ -r $MYSQL_DEFAULTS_FILE ]] || die "MYSQL_DEFAULTS_FILE is not readable"
        MYSQL_ARGS+=("--defaults-extra-file=$MYSQL_DEFAULTS_FILE")
        MYSQLDUMP_ARGS+=("--defaults-extra-file=$MYSQL_DEFAULTS_FILE")
    fi
    if [[ -n $MYSQL_SOCKET ]]; then
        MYSQL_ARGS+=("--socket=$MYSQL_SOCKET")
        MYSQLDUMP_ARGS+=("--socket=$MYSQL_SOCKET")
    else
        MYSQL_ARGS+=("--host=$MYSQL_HOST" "--port=$MYSQL_PORT" "--protocol=TCP")
        MYSQLDUMP_ARGS+=("--host=$MYSQL_HOST" "--port=$MYSQL_PORT" "--protocol=TCP")
    fi
    MYSQL_ARGS+=("--user=$MYSQL_USER" "--default-character-set=utf8mb4")
    MYSQLDUMP_ARGS+=("--user=$MYSQL_USER" "--no-tablespaces")
}

mysql_query() {
    mysql "${MYSQL_ARGS[@]}" --batch --raw --skip-column-names "$@"
}

mysql_table() {
    mysql "${MYSQL_ARGS[@]}" --table "$@"
}

mysql_import() {
    local schema=$1
    local file=$2
    mysql "${MYSQL_ARGS[@]}" --database="$schema" < "$file"
}

sql_escape() {
    local value=$1
    value=${value//\\/\\\\}
    value=${value//\'/\'\'}
    printf '%s' "$value"
}

render_sql() {
    local source=$1
    local destination=$2
    sed \
        -e "s/{{CONTROL_SCHEMA}}/$CONTROL_SCHEMA/g" \
        -e "s/{{SOURCE_AUTH_SCHEMA}}/$SOURCE_AUTH_SCHEMA/g" \
        -e "s/{{SOURCE_CHARACTERS_SCHEMA}}/$SOURCE_CHARACTERS_SCHEMA/g" \
        -e "s/{{SOURCE_WORLD_SCHEMA}}/$SOURCE_WORLD_SCHEMA/g" \
        -e "s/{{TARGET_AUTH_SCHEMA}}/$TARGET_AUTH_SCHEMA/g" \
        -e "s/{{TARGET_CHARACTERS_SCHEMA}}/$TARGET_CHARACTERS_SCHEMA/g" \
        "$source" > "$destination"
}

verify_repository_revisions() {
    local tc_revision
    local ac_revision
    tc_revision=$(git -C "$TRINITYCORE_DIR" rev-parse --short=10 HEAD)
    ac_revision=$(git -C "$AZEROTHCORE_DIR" rev-parse --short=9 HEAD)
    [[ $tc_revision == "$EXPECTED_TRINITYCORE_COMMIT" ]] ||
        die "TrinityCore revision is $tc_revision, expected $EXPECTED_TRINITYCORE_COMMIT"
    [[ $ac_revision == "$EXPECTED_AZEROTHCORE_COMMIT" ]] ||
        die "AzerothCore revision is $ac_revision, expected $EXPECTED_AZEROTHCORE_COMMIT"
    [[ -z $(git -C "$TRINITYCORE_DIR" status --porcelain -- sql) ]] ||
        die "TrinityCore SQL tree has uncommitted or untracked changes"
    [[ -z $(git -C "$AZEROTHCORE_DIR" status --porcelain -- data/sql) ]] ||
        die "AzerothCore SQL tree has uncommitted or untracked changes"
}

schema_exists() {
    local schema=$1
    [[ $(mysql_query -e "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='$(sql_escape "$schema")'") == 1 ]]
}

table_exists() {
    local schema=$1
    local table=$2
    [[ $(mysql_query -e "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$(sql_escape "$schema")' AND TABLE_NAME='$(sql_escape "$table")'") == 1 ]]
}

schema_table_count() {
    local schema=$1
    mysql_query -e "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$(sql_escape "$schema")' AND TABLE_TYPE='BASE TABLE'"
}

schema_fingerprint() {
    local schema=$1
    local dump_file
    dump_file=$(mktemp)
    mysqldump "${MYSQLDUMP_ARGS[@]}" \
        --no-data --skip-comments --skip-dump-date --compact \
        --routines --triggers --events --set-gtid-purged=OFF "$schema" > "$dump_file"
    sed -E -i 's/ AUTO_INCREMENT=[0-9]+//g' "$dump_file"
    sha256sum "$dump_file" | awk '{print $1}'
    rm -f "$dump_file"
}

state_file() {
    printf '%s/run-%s.id\n' "$VAR_DIR" "$CONFIG_HASH"
}

create_run_id() {
    if [[ -n $MIGRATION_RUN_ID ]]; then
        RUN_ID=$MIGRATION_RUN_ID
    elif [[ -s $(state_file) ]]; then
        RUN_ID=$(<"$(state_file)")
    else
        RUN_ID=$(cat /proc/sys/kernel/random/uuid)
        printf '%s\n' "$RUN_ID" > "$(state_file)"
    fi
    [[ $RUN_ID =~ ^[0-9a-fA-F-]{36}$ ]] || die "Invalid migration run ID: $RUN_ID"
}

initialize_control_schema() {
    local rendered
    rendered=$(mktemp)
    render_sql "$MIGRATION_ROOT/sql/00_control_schema.sql" "$rendered"
    mysql "${MYSQL_ARGS[@]}" < "$rendered"
    rm -f "$rendered"
}

verify_run_configuration() {
    local existing
    existing=$(mysql_query -e "
        SELECT COALESCE(MAX(config_hash),'')
        FROM \`$CONTROL_SCHEMA\`.migration_run
        WHERE run_id='$(sql_escape "$RUN_ID")';")
    [[ -z $existing || $existing == "$CONFIG_HASH" ]] ||
        die "Run $RUN_ID was created by a different configuration or toolkit revision"
}

phase_status() {
    local phase=$1
    mysql_query -e "
        SELECT COALESCE(MAX(status), '')
        FROM \`$CONTROL_SCHEMA\`.phase_checkpoint
        WHERE run_id='$(sql_escape "$RUN_ID")' AND phase_name='$(sql_escape "$phase")'"
}

start_phase() {
    local phase=$1
    mysql_query -e "
        INSERT INTO \`$CONTROL_SCHEMA\`.phase_checkpoint
            (run_id, phase_name, status, started_at, finished_at, detail)
        VALUES ('$(sql_escape "$RUN_ID")', '$(sql_escape "$phase")', 'RUNNING', UTC_TIMESTAMP(), NULL, NULL)
        ON DUPLICATE KEY UPDATE
            status=IF(status='COMPLETE','COMPLETE','RUNNING'),
            started_at=IF(status='COMPLETE',started_at,UTC_TIMESTAMP()),
            finished_at=IF(status='COMPLETE',finished_at,NULL),
            detail=IF(status='COMPLETE',detail,NULL)"
}

complete_phase() {
    local phase=$1
    local detail=${2:-}
    mysql_query -e "
        UPDATE \`$CONTROL_SCHEMA\`.phase_checkpoint
        SET status='COMPLETE', finished_at=UTC_TIMESTAMP(), detail='$(sql_escape "$detail")'
        WHERE run_id='$(sql_escape "$RUN_ID")' AND phase_name='$(sql_escape "$phase")'"
}

fail_phase() {
    local phase=$1
    local detail=$2
    mysql_query -e "
        UPDATE \`$CONTROL_SCHEMA\`.phase_checkpoint
        SET status='FAILED', finished_at=UTC_TIMESTAMP(), detail='$(sql_escape "$detail")'
        WHERE run_id='$(sql_escape "$RUN_ID")' AND phase_name='$(sql_escape "$phase")'" >/dev/null 2>&1 || true
}

require_phase() {
    local phase=$1
    [[ $(phase_status "$phase") == COMPLETE ]] || die "Required phase is not complete: $phase"
}

with_phase() {
    local phase=$1
    shift
    if [[ $(phase_status "$phase") == COMPLETE ]]; then
        log "Phase already complete: $phase"
        return 0
    fi
    start_phase "$phase"
    if "$@"; then
        complete_phase "$phase"
    else
        local status=$?
        fail_phase "$phase" "Command failed with status $status"
        return "$status"
    fi
}
