#!/usr/bin/env bash

capture_schema_dump() {
    local schema=$1
    local destination=$2
    mysqldump "${MYSQLDUMP_ARGS[@]}" \
        --no-data --routines --triggers --events \
        --hex-blob --set-gtid-purged=OFF --skip-dump-date \
        "$schema" > "$destination"
}

capture_server_metadata() {
    local destination=$1
    mysql "${MYSQL_ARGS[@]}" --batch --raw -e "
        SELECT 'version', @@version
        UNION ALL SELECT 'version_comment', @@version_comment
        UNION ALL SELECT 'sql_mode', @@sql_mode
        UNION ALL SELECT 'time_zone', @@time_zone
        UNION ALL SELECT 'system_time_zone', @@system_time_zone
        UNION ALL SELECT 'lower_case_table_names', @@lower_case_table_names
        UNION ALL SELECT 'character_set_server', @@character_set_server
        UNION ALL SELECT 'collation_server', @@collation_server;" > "$destination"
}

capture_information_schema() {
    local schema=$1
    local destination=$2
    mysql "${MYSQL_ARGS[@]}" --batch --raw -e "
        SELECT
            TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION, COLUMN_NAME,
            COLUMN_TYPE, IS_NULLABLE, COALESCE(COLUMN_DEFAULT, '<NULL>'),
            EXTRA, GENERATION_EXPRESSION, CHARACTER_SET_NAME, COLLATION_NAME,
            COLUMN_KEY
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA='$(sql_escape "$schema")'
        ORDER BY TABLE_NAME, ORDINAL_POSITION;" > "$destination"
}

capture_source_counts() {
    local kind=$1
    local schema=$2
    local destination=$3
    printf 'table_name\trow_count\n' > "$destination"
    local table rows existing
    while IFS= read -r table; do
        rows=$(mysql_query -e "SELECT COUNT(*) FROM \`$schema\`.\`$table\`;")
        printf '%s\t%s\n' "$table" "$rows" >> "$destination"
        existing=$(mysql_query -e "
            SELECT COALESCE(MAX(row_count),-1)
            FROM \`$CONTROL_SCHEMA\`.source_table_snapshot
            WHERE run_id='$(sql_escape "$RUN_ID")'
              AND database_kind='$(sql_escape "$kind")'
              AND table_name='$(sql_escape "$table")';")
        [[ $existing == -1 || $existing == "$rows" ]] ||
            die "Source row count changed during preflight for $schema.$table"
        if [[ $existing == -1 ]]; then
            mysql_query -e "
                INSERT INTO \`$CONTROL_SCHEMA\`.source_table_snapshot
                    (run_id,database_kind,table_name,row_count)
                VALUES
                    ('$(sql_escape "$RUN_ID")','$(sql_escape "$kind")',
                     '$(sql_escape "$table")',$rows);"
        fi
    done < <(mysql_query -e "
        SELECT TABLE_NAME FROM information_schema.TABLES
        WHERE TABLE_SCHEMA='$(sql_escape "$schema")'
          AND TABLE_TYPE='BASE TABLE'
        ORDER BY TABLE_NAME;")
}

capture_source_orphan_audit() {
    local destination=$1
    local loot_query
    if [[ $MIGRATION_DIRECTION == tc-to-ac ]]; then
        loot_query="
            SELECT container_id AS container_guid
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_items
            UNION ALL
            SELECT container_id
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_money
            WHERE money>0"
    else
        loot_query="
            SELECT containerGUID AS container_guid
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_storage"
    fi
    {
        printf 'metric\trows_found\tpolicy\n'
        mysql_query -e "
            SELECT 'character_without_account',COUNT(*),'DROP_CHARACTER_AND_LINKED_TARGET_DATA'
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.characters c
            LEFT JOIN \`$SOURCE_AUTH_SCHEMA\`.account a ON a.id=c.account
            WHERE c.account<>0 AND a.id IS NULL
            UNION ALL
            SELECT 'inventory_without_character',COUNT(*),'DROP_DANGLING_RELATION'
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_inventory i
            LEFT JOIN \`$SOURCE_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.guid
            WHERE c.guid IS NULL
            UNION ALL
            SELECT 'inventory_without_item',COUNT(*),'DROP_DANGLING_RELATION'
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_inventory i
            LEFT JOIN \`$SOURCE_CHARACTERS_SCHEMA\`.item_instance x ON x.guid=i.item
            WHERE x.guid IS NULL
            UNION ALL
            SELECT 'inventory_without_bag',COUNT(*),'DROP_DANGLING_RELATION'
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_inventory i
            LEFT JOIN \`$SOURCE_CHARACTERS_SCHEMA\`.item_instance b ON b.guid=i.bag
            WHERE i.bag<>0 AND b.guid IS NULL
            UNION ALL
            SELECT 'item_without_owner',COUNT(*),'DROP_ONLY_IF_UNREACHABLE_IN_TARGET'
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_instance i
            LEFT JOIN \`$SOURCE_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.owner_guid
            WHERE i.owner_guid<>0 AND c.guid IS NULL
            UNION ALL
            SELECT 'mail_item_without_mail',COUNT(*),'DROP_DANGLING_RELATION'
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.mail_items mi
            LEFT JOIN \`$SOURCE_CHARACTERS_SCHEMA\`.mail m ON m.id=mi.mail_id
            WHERE m.id IS NULL
            UNION ALL
            SELECT 'mail_item_without_item',COUNT(*),'DROP_DANGLING_RELATION'
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.mail_items mi
            LEFT JOIN \`$SOURCE_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=mi.item_guid
            WHERE i.guid IS NULL
            UNION ALL
            SELECT 'item_loot_without_container',COUNT(*),'DROP_DANGLING_RELATION'
            FROM (
                $loot_query
            ) l
            LEFT JOIN \`$SOURCE_CHARACTERS_SCHEMA\`.item_instance i
              ON i.guid=l.container_guid
            WHERE i.guid IS NULL
            UNION ALL
            SELECT 'realmcharacters_without_account',COUNT(*),'REBUILD_FOR_CONFIGURED_REALM'
            FROM \`$SOURCE_AUTH_SCHEMA\`.realmcharacters rc
            LEFT JOIN \`$SOURCE_AUTH_SCHEMA\`.account a ON a.id=rc.acctid
            WHERE a.id IS NULL;"
    } > "$destination"
}

check_quiescence() {
    [[ $REQUIRE_QUIESCENT == 1 ]] || {
        log "Quiescence enforcement disabled for this rehearsal"
        return
    }

    local active_connections
    active_connections=$(mysql_query -e "
        SELECT COUNT(*)
        FROM information_schema.PROCESSLIST
        WHERE DB IN (
            '$(sql_escape "$SOURCE_AUTH_SCHEMA")',
            '$(sql_escape "$SOURCE_CHARACTERS_SCHEMA")'
        )
          AND ID <> CONNECTION_ID();")
    [[ $active_connections == 0 ]] ||
        die "Source schemas still have $active_connections connected session(s); stop the source core first"
}

check_non_table_objects() {
    local kind=$1
    local schema=$2
    local registry="$MIGRATION_ROOT/mappings/$MIGRATION_DIRECTION/objects.csv"
    local object_type object_name matched
    while IFS=$'\t' read -r object_type object_name; do
        [[ -n $object_name ]] || continue
        matched=$(awk -F, -v k="$kind" -v t="$object_type" -v n="$object_name" '
            $1 == k && $2 == t && $3 == n && $7 == "APPROVED" { count++ }
            END { print count + 0 }
        ' "$registry")
        [[ $matched == 1 ]] ||
            die "$schema contains unmapped $object_type $object_name; add an approved object mapping"
    done < <(mysql_query -e "
        SELECT 'VIEW',TABLE_NAME FROM information_schema.TABLES
        WHERE TABLE_SCHEMA='$(sql_escape "$schema")' AND TABLE_TYPE='VIEW'
        UNION ALL
        SELECT 'ROUTINE',ROUTINE_NAME FROM information_schema.ROUTINES
        WHERE ROUTINE_SCHEMA='$(sql_escape "$schema")'
        UNION ALL
        SELECT 'TRIGGER',TRIGGER_NAME FROM information_schema.TRIGGERS
        WHERE TRIGGER_SCHEMA='$(sql_escape "$schema")'
        UNION ALL
        SELECT 'EVENT',EVENT_NAME FROM information_schema.EVENTS
        WHERE EVENT_SCHEMA='$(sql_escape "$schema")'
        ORDER BY 1,2;")
}

perform_preflight() {
    require_command mysql
    require_command mysqldump
    require_command sha256sum
    require_command sha1sum
    require_command git
    verify_repository_revisions

    local mysql_version
    mysql_version=$(mysql_query -e "SELECT @@version")
    [[ $mysql_version == 8.* ]] || die "MySQL 8.x is required; server reports $mysql_version"

    schema_exists "$SOURCE_AUTH_SCHEMA" || die "Source auth schema does not exist: $SOURCE_AUTH_SCHEMA"
    schema_exists "$SOURCE_CHARACTERS_SCHEMA" ||
        die "Source characters schema does not exist: $SOURCE_CHARACTERS_SCHEMA"
    check_non_table_objects auth "$SOURCE_AUTH_SCHEMA"
    check_non_table_objects characters "$SOURCE_CHARACTERS_SCHEMA"
    [[ $(mysql_query -e "
        SELECT COUNT(*) FROM \`$SOURCE_AUTH_SCHEMA\`.realmlist WHERE id=$REALM_ID;") == 1 ]] ||
        die "REALM_ID=$REALM_ID is not present in $SOURCE_AUTH_SCHEMA.realmlist"

    [[ $SOURCE_AUTH_SCHEMA != "$TARGET_AUTH_SCHEMA" ]] || die "Source and target auth schemas must differ"
    [[ $SOURCE_CHARACTERS_SCHEMA != "$TARGET_CHARACTERS_SCHEMA" ]] ||
        die "Source and target characters schemas must differ"
    [[ $TARGET_AUTH_SCHEMA != "$TARGET_CHARACTERS_SCHEMA" ]] ||
        die "Target auth and characters schemas must differ"

    if schema_exists "$TARGET_AUTH_SCHEMA"; then
        [[ $(schema_table_count "$TARGET_AUTH_SCHEMA") == 0 ]] ||
            die "Target auth schema is not empty: $TARGET_AUTH_SCHEMA"
    fi
    if schema_exists "$TARGET_CHARACTERS_SCHEMA"; then
        [[ $(schema_table_count "$TARGET_CHARACTERS_SCHEMA") == 0 ]] ||
            die "Target characters schema is not empty: $TARGET_CHARACTERS_SCHEMA"
    fi

    check_quiescence

    local run_reports="$REPORTS_DIR/$RUN_ID"
    mkdir -p "$run_reports"
    capture_server_metadata "$run_reports/server-metadata.tsv"
    capture_schema_dump "$SOURCE_AUTH_SCHEMA" "$run_reports/source-auth-schema.sql"
    capture_schema_dump "$SOURCE_CHARACTERS_SCHEMA" "$run_reports/source-characters-schema.sql"
    capture_information_schema "$SOURCE_AUTH_SCHEMA" "$run_reports/source-auth-columns.tsv"
    capture_information_schema "$SOURCE_CHARACTERS_SCHEMA" "$run_reports/source-characters-columns.tsv"

    local auth_fingerprint
    local characters_fingerprint
    auth_fingerprint=$(schema_fingerprint "$SOURCE_AUTH_SCHEMA")
    characters_fingerprint=$(schema_fingerprint "$SOURCE_CHARACTERS_SCHEMA")

    local existing_config
    existing_config=$(mysql_query -e "
        SELECT COALESCE(MAX(config_hash), '')
        FROM \`$CONTROL_SCHEMA\`.migration_run
        WHERE run_id='$(sql_escape "$RUN_ID")'")
    if [[ -n $existing_config && $existing_config != "$CONFIG_HASH" ]]; then
        die "Run $RUN_ID belongs to a different configuration"
    fi

    mysql_query -e "
        INSERT INTO \`$CONTROL_SCHEMA\`.migration_run (
            run_id, migration_direction, config_hash, source_auth_fingerprint,
            source_characters_fingerprint, trinitycore_revision,
            azerothcore_revision, status
        ) VALUES (
            '$(sql_escape "$RUN_ID")', '$MIGRATION_DIRECTION', '$CONFIG_HASH',
            '$auth_fingerprint', '$characters_fingerprint',
            '$(sql_escape "$EXPECTED_TRINITYCORE_COMMIT")',
            '$(sql_escape "$EXPECTED_AZEROTHCORE_COMMIT")', 'RUNNING'
        ) AS new
        ON DUPLICATE KEY UPDATE
            source_auth_fingerprint =
                IF(migration_run.source_auth_fingerprint=new.source_auth_fingerprint,
                   migration_run.source_auth_fingerprint, NULL),
            source_characters_fingerprint =
                IF(migration_run.source_characters_fingerprint=new.source_characters_fingerprint,
                   migration_run.source_characters_fingerprint, NULL),
            updated_at=UTC_TIMESTAMP();"

    local stored_auth
    local stored_characters
    read -r stored_auth stored_characters < <(
        mysql_query -e "
            SELECT COALESCE(source_auth_fingerprint, ''),
                   COALESCE(source_characters_fingerprint, '')
            FROM \`$CONTROL_SCHEMA\`.migration_run
            WHERE run_id='$(sql_escape "$RUN_ID")'"
    )
    [[ -n $stored_auth && -n $stored_characters ]] ||
        die "Source schema drift detected for existing run $RUN_ID; start a new run"

    capture_source_counts auth "$SOURCE_AUTH_SCHEMA" "$run_reports/source-auth-row-counts.tsv"
    capture_source_counts characters "$SOURCE_CHARACTERS_SCHEMA" \
        "$run_reports/source-characters-row-counts.tsv"
    capture_source_orphan_audit "$run_reports/source-orphan-audit.tsv"

    log "Preflight captured source schemas for run $RUN_ID"
}
