#!/usr/bin/env bash

import_base_directory() {
    local schema=$1
    local directory=$2
    local file
    while IFS= read -r file; do
        log "Importing $(basename "$file") into $schema"
        mysql_import "$schema" "$file"
    done < <(find "$directory" -maxdepth 1 -type f -name '*.sql' -print | LC_ALL=C sort)
}

apply_update_directory() {
    local schema=$1
    local directory=$2
    local file
    while IFS= read -r file; do
        local name
        local hash
        local ledger_hash
        name=$(basename "$file")
        hash=$(sha1sum "$file" | awk '{print toupper($1)}')
        ledger_hash=$(mysql_query "$schema" -e "
            SELECT COALESCE(MAX(UPPER(hash)), '')
            FROM updates
            WHERE name='$(sql_escape "$name")';")

        if [[ -n $ledger_hash ]]; then
            [[ $ledger_hash == "$hash" ]] ||
                die "Update ledger hash mismatch for $schema.$name: ledger=$ledger_hash file=$hash"
            continue
        fi

        log "Applying AzerothCore update $schema.$name"
        mysql_import "$schema" "$file"
        mysql_query "$schema" -e "
            INSERT INTO updates (name, hash, state, speed)
            VALUES ('$(sql_escape "$name")', '$hash', 'RELEASED', 0);"
    done < <(find "$directory" -maxdepth 1 -type f -name '*.sql' -print | LC_ALL=C sort)
}

write_schema_diff() {
    local source_schema=$1
    local target_schema=$2
    local prefix=$3
    local run_reports="$REPORTS_DIR/$RUN_ID"

    mysql "${MYSQL_ARGS[@]}" --batch --raw -e "
        SELECT
            COALESCE(s.TABLE_NAME, t.TABLE_NAME) AS table_name,
            CASE
                WHEN s.TABLE_NAME IS NULL THEN 'TARGET_ONLY'
                WHEN t.TABLE_NAME IS NULL THEN 'SOURCE_ONLY'
                ELSE 'BOTH'
            END AS table_presence,
            COALESCE(s.COLUMN_NAME, t.COLUMN_NAME) AS column_name,
            CASE
                WHEN s.COLUMN_NAME IS NULL THEN 'TARGET_ONLY'
                WHEN t.COLUMN_NAME IS NULL THEN 'SOURCE_ONLY'
                WHEN s.COLUMN_TYPE <> t.COLUMN_TYPE
                  OR s.IS_NULLABLE <> t.IS_NULLABLE
                  OR NOT (s.COLUMN_DEFAULT <=> t.COLUMN_DEFAULT)
                  OR s.EXTRA <> t.EXTRA
                  OR NOT (s.COLLATION_NAME <=> t.COLLATION_NAME)
                    THEN 'DIFFERENT'
                ELSE 'MATCH'
            END AS column_status,
            s.COLUMN_TYPE AS source_type,
            t.COLUMN_TYPE AS target_type,
            s.IS_NULLABLE AS source_nullable,
            t.IS_NULLABLE AS target_nullable,
            s.COLUMN_DEFAULT AS source_default,
            t.COLUMN_DEFAULT AS target_default,
            s.EXTRA AS source_extra,
            t.EXTRA AS target_extra
        FROM information_schema.COLUMNS s
        LEFT JOIN information_schema.COLUMNS t
          ON t.TABLE_SCHEMA='$(sql_escape "$target_schema")'
         AND t.TABLE_NAME=s.TABLE_NAME
         AND t.COLUMN_NAME=s.COLUMN_NAME
        WHERE s.TABLE_SCHEMA='$(sql_escape "$source_schema")'
        UNION ALL
        SELECT
            t.TABLE_NAME,
            CASE WHEN s.TABLE_NAME IS NULL THEN 'TARGET_ONLY' ELSE 'BOTH' END,
            t.COLUMN_NAME,
            CASE WHEN s.COLUMN_NAME IS NULL THEN 'TARGET_ONLY' ELSE 'MATCH' END,
            s.COLUMN_TYPE, t.COLUMN_TYPE,
            s.IS_NULLABLE, t.IS_NULLABLE,
            s.COLUMN_DEFAULT, t.COLUMN_DEFAULT,
            s.EXTRA, t.EXTRA
        FROM information_schema.COLUMNS t
        LEFT JOIN information_schema.COLUMNS s
          ON s.TABLE_SCHEMA='$(sql_escape "$source_schema")'
         AND s.TABLE_NAME=t.TABLE_NAME
         AND s.COLUMN_NAME=t.COLUMN_NAME
        WHERE t.TABLE_SCHEMA='$(sql_escape "$target_schema")'
          AND s.COLUMN_NAME IS NULL
        ORDER BY table_name, column_name;" > "$run_reports/${prefix}-schema-diff.tsv"
    awk -F '\t' 'NR == 1 || $4 == "DIFFERENT" { print }' \
        "$run_reports/${prefix}-schema-diff.tsv" > "$run_reports/${prefix}-type-risk.tsv"

    mysql "${MYSQL_ARGS[@]}" --batch --raw -e "
        SELECT
            COALESCE(s.TABLE_NAME, t.TABLE_NAME) AS table_name,
            CASE
                WHEN s.TABLE_NAME IS NULL THEN 'TARGET_ONLY'
                WHEN t.TABLE_NAME IS NULL THEN 'SOURCE_ONLY'
                ELSE 'BOTH'
            END AS status
        FROM (
            SELECT TABLE_NAME FROM information_schema.TABLES
            WHERE TABLE_SCHEMA='$(sql_escape "$source_schema")' AND TABLE_TYPE='BASE TABLE'
        ) s
        LEFT JOIN (
            SELECT TABLE_NAME FROM information_schema.TABLES
            WHERE TABLE_SCHEMA='$(sql_escape "$target_schema")' AND TABLE_TYPE='BASE TABLE'
        ) t USING (TABLE_NAME)
        UNION ALL
        SELECT t.TABLE_NAME, 'TARGET_ONLY'
        FROM information_schema.TABLES t
        LEFT JOIN information_schema.TABLES s
          ON s.TABLE_SCHEMA='$(sql_escape "$source_schema")'
         AND s.TABLE_NAME=t.TABLE_NAME
         AND s.TABLE_TYPE='BASE TABLE'
        WHERE t.TABLE_SCHEMA='$(sql_escape "$target_schema")'
          AND t.TABLE_TYPE='BASE TABLE'
          AND s.TABLE_NAME IS NULL
        ORDER BY table_name;" > "$run_reports/${prefix}-table-inventory.tsv"
}

perform_assemble() {
    require_phase preflight
    verify_repository_revisions

    if schema_exists "$TARGET_AUTH_SCHEMA" && [[ $(schema_table_count "$TARGET_AUTH_SCHEMA") != 0 ]]; then
        die "Target auth schema became non-empty before assembly"
    fi
    if schema_exists "$TARGET_CHARACTERS_SCHEMA" && [[ $(schema_table_count "$TARGET_CHARACTERS_SCHEMA") != 0 ]]; then
        die "Target characters schema became non-empty before assembly"
    fi

    mysql_query -e "
        CREATE DATABASE IF NOT EXISTS \`$TARGET_AUTH_SCHEMA\`
          CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        CREATE DATABASE IF NOT EXISTS \`$TARGET_CHARACTERS_SCHEMA\`
          CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

    import_base_directory "$TARGET_AUTH_SCHEMA" "$AZEROTHCORE_DIR/data/sql/base/db_auth"
    import_base_directory "$TARGET_CHARACTERS_SCHEMA" "$AZEROTHCORE_DIR/data/sql/base/db_characters"
    apply_update_directory "$TARGET_AUTH_SCHEMA" "$AZEROTHCORE_DIR/data/sql/updates/db_auth"
    apply_update_directory "$TARGET_CHARACTERS_SCHEMA" "$AZEROTHCORE_DIR/data/sql/updates/db_characters"

    local auth_tables
    local character_tables
    auth_tables=$(schema_table_count "$TARGET_AUTH_SCHEMA")
    character_tables=$(schema_table_count "$TARGET_CHARACTERS_SCHEMA")
    [[ $auth_tables == 22 ]] || die "Expected 22 target auth tables, found $auth_tables"
    [[ $character_tables == 108 ]] || die "Expected 108 target characters tables, found $character_tables"

    local auth_fingerprint
    local characters_fingerprint
    auth_fingerprint=$(schema_fingerprint "$TARGET_AUTH_SCHEMA")
    characters_fingerprint=$(schema_fingerprint "$TARGET_CHARACTERS_SCHEMA")
    mysql_query -e "
        UPDATE \`$CONTROL_SCHEMA\`.migration_run
        SET target_auth_fingerprint='$auth_fingerprint',
            target_characters_fingerprint='$characters_fingerprint'
        WHERE run_id='$(sql_escape "$RUN_ID")';"

    capture_schema_dump "$TARGET_AUTH_SCHEMA" "$REPORTS_DIR/$RUN_ID/target-auth-schema.sql"
    capture_schema_dump "$TARGET_CHARACTERS_SCHEMA" "$REPORTS_DIR/$RUN_ID/target-characters-schema.sql"
    capture_information_schema "$TARGET_AUTH_SCHEMA" "$REPORTS_DIR/$RUN_ID/target-auth-columns.tsv"
    capture_information_schema "$TARGET_CHARACTERS_SCHEMA" "$REPORTS_DIR/$RUN_ID/target-characters-columns.tsv"
    write_schema_diff "$SOURCE_AUTH_SCHEMA" "$TARGET_AUTH_SCHEMA" auth
    write_schema_diff "$SOURCE_CHARACTERS_SCHEMA" "$TARGET_CHARACTERS_SCHEMA" characters

    log "Assembled native AzerothCore schemas and generated schema reports"
}
