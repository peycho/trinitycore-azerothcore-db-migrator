#!/usr/bin/env bash
# shellcheck disable=SC2016

mapping_file_for() {
    printf '%s/mappings/%s.csv\n' "$MIGRATION_ROOT" "$1"
}

schemas_for_kind() {
    local kind=$1
    if [[ $kind == auth ]]; then
        SOURCE_SCHEMA=$SOURCE_AUTH_SCHEMA
        TARGET_SCHEMA=$TARGET_AUTH_SCHEMA
    else
        SOURCE_SCHEMA=$SOURCE_CHARACTERS_SCHEMA
        TARGET_SCHEMA=$TARGET_CHARACTERS_SCHEMA
    fi
}

record_reject() {
    local source_table=$1 source_key=$2 reason=$3 detail=$4
    mysql_query -e "
        INSERT INTO \`$CONTROL_SCHEMA\`.migration_reject
            (run_id,database_kind,source_table,source_key,reason_code,reason_detail)
        VALUES
            ('$(sql_escape "$RUN_ID")','$(sql_escape "$LOAD_KIND")',
             '$(sql_escape "$source_table")','$(sql_escape "$source_key")',
             '$(sql_escape "$reason")','$(sql_escape "$detail")');"
}

assert_schema_unchanged() {
    local kind=$1
    local schema=$2
    local current
    local stored
    current=$(schema_fingerprint "$schema")
    stored=$(mysql_query -e "
        SELECT $(if [[ $kind == auth ]]; then
            printf 'source_auth_fingerprint'
        else
            printf 'source_characters_fingerprint'
        fi)
        FROM \`$CONTROL_SCHEMA\`.migration_run
        WHERE run_id='$(sql_escape "$RUN_ID")';")
    [[ $current == "$stored" ]] || die "Source $kind schema changed after preflight"
}

assert_source_counts_unchanged() {
    local kind=$1
    local schema=$2
    local table expected actual
    while IFS=$'\t' read -r table expected; do
        actual=$(mysql_query -e "SELECT COUNT(*) FROM \`$schema\`.\`$table\`;")
        [[ $actual == "$expected" ]] ||
            die "Source data changed after preflight: $schema.$table expected=$expected actual=$actual"
    done < <(mysql_query -e "
        SELECT table_name,row_count
        FROM \`$CONTROL_SCHEMA\`.source_table_snapshot
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
        ORDER BY table_name;")
}

mapping_inventory_check() {
    local kind=$1
    local mapping_file
    mapping_file=$(mapping_file_for "$kind")
    [[ -r $mapping_file ]] || die "Mapping registry not found: $mapping_file"

    declare -A mapped_source=()
    declare -A mapped_target=()
    local source_table target_table rest
    while IFS=, read -r source_table target_table rest; do
        [[ $source_table == source_table ]] && continue
        if [[ -n $source_table && $source_table != "-" ]]; then
            local source_part
            IFS=+ read -ra source_parts <<< "$source_table"
            for source_part in "${source_parts[@]}"; do
                mapped_source["$source_part"]=1
            done
        fi
        [[ -n $target_table && $target_table != "-" ]] && mapped_target["$target_table"]=1
    done < "$mapping_file"

    local table
    while IFS= read -r table; do
        [[ -n ${mapped_source[$table]:-} ]] ||
            die "Source $kind table is absent from mapping registry: $table"
    done < <(mysql_query -e "
        SELECT TABLE_NAME FROM information_schema.TABLES
        WHERE TABLE_SCHEMA='$(sql_escape "$SOURCE_SCHEMA")'
          AND TABLE_TYPE='BASE TABLE'
        ORDER BY TABLE_NAME")
    while IFS= read -r table; do
        [[ -n ${mapped_target[$table]:-} ]] ||
            die "Target $kind table is absent from mapping registry: $table"
    done < <(mysql_query -e "
        SELECT TABLE_NAME FROM information_schema.TABLES
        WHERE TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
          AND TABLE_TYPE='BASE TABLE'
        ORDER BY TABLE_NAME")
}

integer_bounds() {
    local column_type=$1
    case "$column_type" in
        "tinyint unsigned"*) printf '0 255\n' ;;
        tinyint*) printf '%s\n' '-128 127' ;;
        "smallint unsigned"*) printf '0 65535\n' ;;
        smallint*) printf '%s\n' '-32768 32767' ;;
        "mediumint unsigned"*) printf '0 16777215\n' ;;
        mediumint*) printf '%s\n' '-8388608 8388607' ;;
        "int unsigned"*) printf '0 4294967295\n' ;;
        int*) printf '%s\n' '-2147483648 2147483647' ;;
        "bigint unsigned"*) printf '0 18446744073709551615\n' ;;
        bigint*) printf '%s\n' '-9223372036854775808 9223372036854775807' ;;
        *) return 1 ;;
    esac
}

validate_common_values() {
    local source_table=$1
    local target_table=$2
    local null_conversion_columns=${3:-}
    local metadata
    metadata=$(mysql_query -e "
        SELECT
            t.COLUMN_NAME,
            s.DATA_TYPE,
            t.DATA_TYPE,
            s.COLUMN_TYPE,
            t.COLUMN_TYPE,
            COALESCE(t.CHARACTER_MAXIMUM_LENGTH, 0),
            s.IS_NULLABLE,
            t.IS_NULLABLE
        FROM information_schema.COLUMNS t
        JOIN information_schema.COLUMNS s
          ON s.TABLE_SCHEMA='$(sql_escape "$SOURCE_SCHEMA")'
         AND s.TABLE_NAME='$(sql_escape "$source_table")'
         AND s.COLUMN_NAME=t.COLUMN_NAME
        WHERE t.TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
          AND t.TABLE_NAME='$(sql_escape "$target_table")'
          AND t.EXTRA NOT LIKE '%GENERATED%'
        ORDER BY t.ORDINAL_POSITION;")

    local column source_type target_type _source_column_type target_column_type
    local target_length source_nullable target_nullable
    while IFS=$'\t' read -r column source_type target_type _source_column_type target_column_type \
        target_length source_nullable target_nullable; do
        [[ -n $column ]] || continue
        [[ $column != *'`'* ]] || die "Unsupported backtick in column name: $source_table.$column"

        if [[ $source_nullable == YES && $target_nullable == NO &&
              ,$null_conversion_columns, != *",$column,"* ]]; then
            local nulls
            nulls=$(mysql_query -e "
                SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\`
                WHERE \`$column\` IS NULL;")
            [[ $nulls == 0 ]] ||
                {
                    record_reject "$source_table" "*" NULL_NOT_ALLOWED \
                        "$column has $nulls NULL value(s), but target is NOT NULL"
                    die "$source_table.$column has $nulls NULL value(s), but target is NOT NULL"
                }
        fi

        case "$target_type" in
            char|varchar|binary|varbinary)
                local too_long
                local length_function=CHAR_LENGTH
                [[ $target_type == binary || $target_type == varbinary ]] &&
                    length_function=OCTET_LENGTH
                too_long=$(mysql_query -e "
                    SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\`
                    WHERE \`$column\` IS NOT NULL
                      AND $length_function(\`$column\`) > $target_length;")
            [[ $too_long == 0 ]] ||
                    {
                        record_reject "$source_table" "*" VALUE_TOO_LONG \
                            "$column has $too_long value(s) too long for $target_column_type"
                        die "$source_table.$column has $too_long value(s) too long for $target_column_type"
                    }
                ;;
        esac

        case "$source_type:$target_type" in
            tinyint:tinyint|tinyint:smallint|tinyint:mediumint|tinyint:int|tinyint:bigint|\
            smallint:tinyint|smallint:smallint|smallint:mediumint|smallint:int|smallint:bigint|\
            mediumint:tinyint|mediumint:smallint|mediumint:mediumint|mediumint:int|mediumint:bigint|\
            int:tinyint|int:smallint|int:mediumint|int:int|int:bigint|\
            bigint:tinyint|bigint:smallint|bigint:mediumint|bigint:int|bigint:bigint)
                local minimum maximum out_of_range
                read -r minimum maximum < <(integer_bounds "$target_column_type")
                out_of_range=$(mysql_query -e "
                    SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\`
                    WHERE \`$column\` IS NOT NULL
                      AND (\`$column\` < $minimum OR \`$column\` > $maximum);")
                [[ $out_of_range == 0 ]] ||
                    {
                        record_reject "$source_table" "*" INTEGER_OUT_OF_RANGE \
                            "$column has $out_of_range value(s) outside $target_column_type"
                        die "$source_table.$column has $out_of_range value(s) outside $target_column_type"
                    }
                ;;
        esac
    done <<< "$metadata"
}

build_common_spec() {
    local source_table=$1
    local target_table=$2

    local missing_required
    missing_required=$(mysql_query -e "
        SELECT COUNT(*)
        FROM information_schema.COLUMNS t
        LEFT JOIN information_schema.COLUMNS s
          ON s.TABLE_SCHEMA='$(sql_escape "$SOURCE_SCHEMA")'
         AND s.TABLE_NAME='$(sql_escape "$source_table")'
         AND s.COLUMN_NAME=t.COLUMN_NAME
        WHERE t.TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
          AND t.TABLE_NAME='$(sql_escape "$target_table")'
          AND s.COLUMN_NAME IS NULL
          AND t.IS_NULLABLE='NO'
          AND t.COLUMN_DEFAULT IS NULL
          AND t.EXTRA NOT LIKE '%auto_increment%'
          AND t.EXTRA NOT LIKE '%GENERATED%';")
    [[ $missing_required == 0 ]] ||
        die "$source_table -> $target_table omits $missing_required required target column(s)"

    validate_common_values "$source_table" "$target_table"

    mysql_query -e "SET SESSION group_concat_max_len=1048576;
        SELECT
            GROUP_CONCAT(CONCAT('\`', REPLACE(t.COLUMN_NAME, '\`', '\`\`'), '\`')
                         ORDER BY t.ORDINAL_POSITION SEPARATOR ','),
            GROUP_CONCAT(CONCAT('s.\`', REPLACE(t.COLUMN_NAME, '\`', '\`\`'), '\`')
                         ORDER BY t.ORDINAL_POSITION SEPARATOR ',')
        FROM information_schema.COLUMNS t
        JOIN information_schema.COLUMNS s
          ON s.TABLE_SCHEMA='$(sql_escape "$SOURCE_SCHEMA")'
         AND s.TABLE_NAME='$(sql_escape "$source_table")'
         AND s.COLUMN_NAME=t.COLUMN_NAME
        WHERE t.TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
          AND t.TABLE_NAME='$(sql_escape "$target_table")'
          AND t.EXTRA NOT LIKE '%GENERATED%';"
}

build_named_transform_spec() {
    local transform=$1
    case "$transform" in
        ACCOUNT)
            printf '%s\t%s\n' \
                '`id`,`username`,`salt`,`verifier`,`session_key`,`totp_secret`,`email`,`reg_mail`,`joindate`,`last_ip`,`last_attempt_ip`,`failed_logins`,`locked`,`lock_country`,`last_login`,`online`,`expansion`,`Flags`,`mutetime`,`mutereason`,`muteby`,`locale`,`os`,`recruiter`,`totaltime`' \
                's.`id`,s.`username`,s.`salt`,s.`verifier`,s.`session_key_auth`,s.`totp_secret`,s.`email`,s.`reg_mail`,s.`joindate`,s.`last_ip`,s.`last_attempt_ip`,s.`failed_logins`,s.`locked`,s.`lock_country`,s.`last_login`,0,s.`expansion`,0,s.`mutetime`,s.`mutereason`,s.`muteby`,s.`locale`,s.`os`,s.`recruiter`,0'
            ;;
        ACCOUNT_ACCESS)
            printf '%s\t%s\n' \
                '`id`,`gmlevel`,`RealmID`,`comment`' \
                's.`AccountID`,s.`SecurityLevel`,s.`RealmID`,s.`Comment`'
            ;;
        CHARACTERS)
            mysql_query -e "SET SESSION group_concat_max_len=1048576;
                SELECT
                    GROUP_CONCAT(CONCAT('\`', REPLACE(t.COLUMN_NAME, '\`', '\`\`'), '\`')
                                 ORDER BY t.ORDINAL_POSITION SEPARATOR ','),
                    GROUP_CONCAT(
                        CASE t.COLUMN_NAME
                            WHEN 'online' THEN '0'
                            WHEN 'name' THEN 'COALESCE(s.\`name\`,'''')'
                            WHEN 'order' THEN 'NULL'
                            WHEN 'creation_date' THEN 'UTC_TIMESTAMP()'
                            WHEN 'innTriggerId' THEN '0'
                            WHEN 'extraBonusTalentCount' THEN '0'
                            ELSE CONCAT('s.\`', REPLACE(t.COLUMN_NAME, '\`', '\`\`'), '\`')
                        END
                        ORDER BY t.ORDINAL_POSITION SEPARATOR ',')
                FROM information_schema.COLUMNS t
                LEFT JOIN information_schema.COLUMNS s
                  ON s.TABLE_SCHEMA='$(sql_escape "$SOURCE_SCHEMA")'
                 AND s.TABLE_NAME='characters'
                 AND s.COLUMN_NAME=t.COLUMN_NAME
                WHERE t.TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
                  AND t.TABLE_NAME='characters'
                  AND (s.COLUMN_NAME IS NOT NULL OR t.COLUMN_NAME IN
                      ('order','creation_date','innTriggerId','extraBonusTalentCount'))
                  AND t.EXTRA NOT LIKE '%GENERATED%';"
            ;;
        CHARACTER_INSTANCE)
            printf '%s\t%s\n' \
                '`guid`,`instance`,`permanent`,`extended`' \
                's.`guid`,s.`instance`,s.`permanent`,IF(s.`extendState`=2,1,0)'
            ;;
        CHARACTER_ENTRY_POINT)
            printf '%s\t%s\n' \
                '`guid`,`joinX`,`joinY`,`joinZ`,`joinO`,`joinMapId`,`taxiPath0`,`taxiPath1`,`mountSpell`' \
                's.`guid`,s.`joinX`,s.`joinY`,s.`joinZ`,s.`joinO`,s.`joinMapId`,s.`taxiStart`,s.`taxiEnd`,s.`mountSpell`'
            ;;
        CHARACTER_SPELL_COOLDOWN)
            printf '%s\t%s\n' \
                '`guid`,`spell`,`category`,`item`,`time`,`needSend`' \
                's.`guid`,s.`spell`,s.`categoryId`,s.`item`,GREATEST(s.`time`,s.`categoryEnd`),1'
            ;;
        CHARACTER_SPELL)
            printf '%s\t%s\n' \
                '`guid`,`spell`,`specMask`' \
                's.`guid`,s.`spell`,3'
            ;;
        CHARACTER_ARENA_STATS)
            printf '%s\t%s\n' \
                '`guid`,`slot`,`matchMakerRating`,`maxMMR`' \
                's.`guid`,s.`slot`,s.`matchMakerRating`,s.`matchMakerRating`'
            ;;
        GM_SURVEY)
            printf '%s\t%s\n' \
                '`surveyId`,`guid`,`mainSurvey`,`comment`,`createTime`,`maxMMR`' \
                's.`surveyId`,s.`guid`,s.`mainSurvey`,s.`comment`,s.`createTime`,0'
            ;;
        PET_SPELL_COOLDOWN)
            printf '%s\t%s\n' \
                '`guid`,`spell`,`category`,`time`' \
                's.`guid`,s.`spell`,s.`categoryId`,GREATEST(s.`time`,s.`categoryEnd`)'
            ;;
        PETITION)
            printf '%s\t%s\n' \
                '`ownerguid`,`petitionguid`,`petition_id`,`name`,`type`' \
                's.`ownerguid`,s.`petitionguid`,s.`petitionguid`,s.`name`,s.`type`'
            ;;
        PETITION_SIGN)
            printf '%s\t%s\n' \
                '`ownerguid`,`petitionguid`,`petition_id`,`playerguid`,`player_account`,`type`' \
                's.`ownerguid`,s.`petitionguid`,s.`petitionguid`,s.`playerguid`,s.`player_account`,s.`type`'
            ;;
        *)
            die "Unknown named transform: $transform"
            ;;
    esac
}

single_numeric_primary_key() {
    local table=$1
    mysql_query -e "
        SELECT COALESCE(MAX(CASE WHEN key_count=1 AND DATA_TYPE IN
            ('tinyint','smallint','mediumint','int','bigint') THEN COLUMN_NAME ELSE '' END), '')
        FROM (
            SELECT k.TABLE_SCHEMA, k.TABLE_NAME, k.COLUMN_NAME, c.DATA_TYPE,
                   COUNT(*) OVER (PARTITION BY k.TABLE_SCHEMA, k.TABLE_NAME) AS key_count
            FROM information_schema.KEY_COLUMN_USAGE k
            JOIN information_schema.COLUMNS c
              ON c.TABLE_SCHEMA=k.TABLE_SCHEMA
             AND c.TABLE_NAME=k.TABLE_NAME
             AND c.COLUMN_NAME=k.COLUMN_NAME
            WHERE k.TABLE_SCHEMA='$(sql_escape "$SOURCE_SCHEMA")'
              AND k.TABLE_NAME='$(sql_escape "$table")'
              AND k.CONSTRAINT_NAME='PRIMARY'
        ) x;"
}

checkpoint_complete() {
    local kind=$1 table=$2 start=$3 end=$4 hash=$5
    [[ $(mysql_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.chunk_checkpoint
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND target_table='$(sql_escape "$table")'
          AND chunk_start=$start AND chunk_end=$end
          AND script_hash='$hash' AND status='COMPLETE';") == 1 ]]
}

prepare_target_for_copy() {
    local kind=$1
    local target_table=$2
    local checkpoints
    checkpoints=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.chunk_checkpoint
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND target_table='$(sql_escape "$target_table")';")
    if [[ $checkpoints == 0 ]]; then
        mysql_query -e "DELETE FROM \`$TARGET_SCHEMA\`.\`$target_table\`;"
    fi
}

record_checkpoint() {
    local kind=$1 source_table=$2 target_table=$3 start=$4 end=$5 hash=$6 source_rows=$7 target_rows=$8
    mysql_query -e "
        INSERT INTO \`$CONTROL_SCHEMA\`.chunk_checkpoint
            (run_id,database_kind,source_table,target_table,chunk_start,chunk_end,
             script_hash,source_rows,target_rows,status)
        VALUES
            ('$(sql_escape "$RUN_ID")','$(sql_escape "$kind")',
             '$(sql_escape "$source_table")','$(sql_escape "$target_table")',
             $start,$end,'$hash',$source_rows,$target_rows,'COMPLETE') AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash, source_rows=new.source_rows,
            target_rows=new.target_rows, status='COMPLETE',
            finished_at=UTC_TIMESTAMP();"
}

load_statement_chunks() {
    local kind=$1 source_table=$2 target_table=$3 target_columns=$4 expressions=$5
    local primary_key
    primary_key=$(single_numeric_primary_key "$source_table")
    local base_statement="INSERT INTO \`$TARGET_SCHEMA\`.\`$target_table\` ($target_columns) SELECT $expressions FROM \`$SOURCE_SCHEMA\`.\`$source_table\` s"
    printf '%s;\n' "$base_statement" \
        > "$REPORTS_DIR/$RUN_ID/generated-$kind-$target_table.sql"
    local script_hash
    script_hash=$(printf '%s' "$base_statement" | sha256sum | awk '{print $1}')
    prepare_target_for_copy "$kind" "$target_table"

    local minimum=0 maximum=0
    if [[ -n $primary_key ]]; then
        read -r minimum maximum < <(
            mysql_query -e "SELECT COALESCE(MIN(\`$primary_key\`),0), COALESCE(MAX(\`$primary_key\`),0)
                FROM \`$SOURCE_SCHEMA\`.\`$source_table\`;"
        )
    fi

    local chunk_start=$minimum
    while :; do
        local chunk_end where_clause
        if [[ -n $primary_key ]]; then
            chunk_end=$((chunk_start + CHUNK_SIZE - 1))
            (( chunk_end > maximum )) && chunk_end=$maximum
            where_clause=" WHERE s.\`$primary_key\` BETWEEN $chunk_start AND $chunk_end"
        else
            chunk_start=0
            chunk_end=0
            where_clause=
        fi

        if checkpoint_complete "$kind" "$target_table" "$chunk_start" "$chunk_end" "$script_hash"; then
            log "Skipping completed chunk $target_table [$chunk_start,$chunk_end]"
        else
            local source_rows target_before target_after inserted
            source_rows=$(mysql_query -e "
                SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\` s$where_clause;")
            if [[ -n $primary_key ]]; then
                target_before=$(mysql_query -e "
                    SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`
                    WHERE \`$primary_key\` BETWEEN $chunk_start AND $chunk_end;")
            else
                target_before=$(mysql_query -e "
                    SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`;")
            fi
            [[ $target_before == 0 ]] ||
                die "Target chunk is not empty before load: $target_table [$chunk_start,$chunk_end]"

            mysql_query -e "
                SET SESSION time_zone='+00:00';
                SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';
                START TRANSACTION;
                $base_statement$where_clause;
                COMMIT;"

            if [[ -n $primary_key ]]; then
                target_after=$(mysql_query -e "
                    SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`
                    WHERE \`$primary_key\` BETWEEN $chunk_start AND $chunk_end;")
            else
                target_after=$(mysql_query -e "
                    SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`;")
            fi
            inserted=$((target_after - target_before))
            [[ $inserted == "$source_rows" ]] ||
                die "Row-count mismatch for $target_table: source=$source_rows inserted=$inserted"
            record_checkpoint "$kind" "$source_table" "$target_table" \
                "$chunk_start" "$chunk_end" "$script_hash" "$source_rows" "$inserted"
        fi

        [[ -z $primary_key || $chunk_end -ge $maximum ]] && break
        chunk_start=$(mysql_query -e "
            SELECT COALESCE(MIN(\`$primary_key\`),$((maximum + 1)))
            FROM \`$SOURCE_SCHEMA\`.\`$source_table\`
            WHERE \`$primary_key\` > $chunk_end;")
        (( chunk_start > maximum )) && break
    done
}

load_rbac_account_permissions() {
    local target_table=rbac_account_permissions
    local statement="
        INSERT INTO \`$TARGET_SCHEMA\`.\`rbac_account_permissions\`
            (accountId,permissionId,granted,realmId)
        SELECT ap.accountId,tp.id,ap.granted,ap.realmId
        FROM \`$SOURCE_SCHEMA\`.\`rbac_account_permissions\` ap
        JOIN \`$SOURCE_SCHEMA\`.\`rbac_permissions\` sp
          ON sp.id=ap.permissionId
        JOIN \`$TARGET_SCHEMA\`.\`rbac_permissions\` tp
          ON BINARY tp.name=BINARY sp.name"
    local hash
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    if checkpoint_complete auth "$target_table" 0 0 "$hash"; then
        log "Skipping completed transform: $target_table"
        return
    fi

    local unmatched invalid_realms invalid_grants missing_accounts collisions
    unmatched=$(mysql_query -e "
        SELECT COUNT(*)
        FROM \`$SOURCE_SCHEMA\`.rbac_account_permissions ap
        LEFT JOIN \`$SOURCE_SCHEMA\`.rbac_permissions sp
          ON sp.id=ap.permissionId
        WHERE sp.id IS NULL
           OR (
                SELECT COUNT(*)
                FROM \`$TARGET_SCHEMA\`.rbac_permissions tp
                WHERE BINARY tp.name=BINARY sp.name
              ) <> 1;")
    if [[ $unmatched != 0 ]]; then
        record_reject rbac_account_permissions "*" RBAC_PERMISSION_NOT_UNIQUE \
            "$unmatched row(s) lack exactly one target permission with the same name"
        die "rbac_account_permissions has $unmatched permission mapping failure(s)"
    fi

    invalid_realms=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.rbac_account_permissions
        WHERE realmId NOT IN (-1,$REALM_ID);")
    if [[ $invalid_realms != 0 ]]; then
        record_reject rbac_account_permissions "*" RBAC_REALM_SCOPE \
            "$invalid_realms row(s) target a realm other than -1 or $REALM_ID"
        die "rbac_account_permissions has $invalid_realms unsupported realm scope(s)"
    fi

    invalid_grants=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.rbac_account_permissions
        WHERE granted NOT IN (0,1);")
    if [[ $invalid_grants != 0 ]]; then
        record_reject rbac_account_permissions "*" RBAC_GRANTED_VALUE \
            "$invalid_grants row(s) have granted outside zero or one"
        die "rbac_account_permissions has $invalid_grants invalid granted value(s)"
    fi

    missing_accounts=$(mysql_query -e "
        SELECT COUNT(*)
        FROM \`$SOURCE_SCHEMA\`.rbac_account_permissions ap
        LEFT JOIN \`$TARGET_SCHEMA\`.account a ON a.id=ap.accountId
        WHERE a.id IS NULL;")
    if [[ $missing_accounts != 0 ]]; then
        record_reject rbac_account_permissions "*" RBAC_ACCOUNT_MISSING \
            "$missing_accounts row(s) reference an account absent from the target"
        die "rbac_account_permissions has $missing_accounts missing target account(s)"
    fi

    collisions=$(mysql_query -e "
        SELECT COUNT(*) FROM (
            SELECT ap.accountId,tp.id,ap.realmId
            FROM \`$SOURCE_SCHEMA\`.rbac_account_permissions ap
            JOIN \`$SOURCE_SCHEMA\`.rbac_permissions sp ON sp.id=ap.permissionId
            JOIN \`$TARGET_SCHEMA\`.rbac_permissions tp
              ON BINARY tp.name=BINARY sp.name
            GROUP BY ap.accountId,tp.id,ap.realmId
            HAVING COUNT(*) > 1
        ) duplicate_mappings;")
    if [[ $collisions != 0 ]]; then
        record_reject rbac_account_permissions "*" RBAC_MAPPING_COLLISION \
            "$collisions target key collision(s) result from name mapping"
        die "rbac_account_permissions has $collisions target mapping collision(s)"
    fi

    printf '%s;\n' "$statement" \
        > "$REPORTS_DIR/$RUN_ID/generated-auth-rbac_account_permissions.sql"
    prepare_target_for_copy auth "$target_table"
    local expected actual
    expected=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.rbac_account_permissions;")
    mysql_query -e "
        SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';
        START TRANSACTION;
        $statement;
        COMMIT;"
    actual=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.rbac_account_permissions;")
    [[ $actual == "$expected" ]] ||
        die "RBAC account permission count mismatch: expected=$expected actual=$actual"
    record_checkpoint auth rbac_account_permissions "$target_table" 0 0 \
        "$hash" "$expected" "$actual"
}

load_item_loot_storage() {
    local target_table=item_loot_storage
    local statement="
        INSERT INTO \`$TARGET_SCHEMA\`.\`item_loot_storage\`
            (containerGUID,itemid,count,item_index,randomPropertyId,randomSuffix,
             follow_loot_rules,freeforall,is_blocked,is_counted,is_underthreshold,
             needs_quest,conditionLootId)
        SELECT container_id,item_id,item_count,item_index,rnd_prop,
               CAST(rnd_suffix AS UNSIGNED),follow_rules,ffa,blocked,counted,
               under_threshold,needs_quest,0
        FROM \`$SOURCE_SCHEMA\`.\`item_loot_items\`
        UNION ALL
        SELECT container_id,0,money,0,0,0,0,0,0,0,0,0,0
        FROM \`$SOURCE_SCHEMA\`.\`item_loot_money\`
        WHERE money > 0"
    local hash
    local unsafe_loot
    unsafe_loot=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.item_loot_items
        WHERE item_count < 0 OR rnd_suffix < 0;")
    if [[ $unsafe_loot != 0 ]]; then
        record_reject item_loot_items "*" UNSIGNED_CONVERSION \
            "$unsafe_loot row(s) contain negative item_count or rnd_suffix"
        die "item_loot_items contains $unsafe_loot unsafe unsigned conversion(s)"
    fi
    printf '%s;\n' "$statement" \
        > "$REPORTS_DIR/$RUN_ID/generated-characters-item_loot_storage.sql"
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    if checkpoint_complete characters "$target_table" 0 0 "$hash"; then
        log "Skipping completed transform: $target_table"
        return
    fi
    prepare_target_for_copy characters "$target_table"
    [[ $(mysql_query -e "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`;") == 0 ]] ||
        die "Target table is not empty: $target_table"
    local expected
    expected=$(mysql_query -e "
        SELECT
          (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`item_loot_items\`) +
          (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`item_loot_money\` WHERE money > 0);")
    mysql_query -e "
        SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';
        START TRANSACTION;
        $statement;
        COMMIT;"
    local actual
    actual=$(mysql_query -e "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`;")
    [[ $actual == "$expected" ]] || die "item_loot_storage count mismatch: expected=$expected actual=$actual"
    record_checkpoint characters item_loot_items+item_loot_money "$target_table" 0 0 "$hash" "$expected" "$actual"
}

load_character_talents() {
    local target_table=character_talent
    local statement="
        INSERT INTO \`$TARGET_SCHEMA\`.\`character_talent\` (guid,spell,specMask)
        SELECT guid,spell,BIT_OR(CAST(1 AS UNSIGNED) << talentGroup)
        FROM \`$SOURCE_SCHEMA\`.\`character_talent\`
        GROUP BY guid,spell"
    local hash expected actual
    local invalid_groups
    invalid_groups=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.character_talent
        WHERE talentGroup > 1;")
    if [[ $invalid_groups != 0 ]]; then
        record_reject character_talent "*" INVALID_TALENT_GROUP \
            "$invalid_groups row(s) have talentGroup outside 0..1"
        die "character_talent contains $invalid_groups invalid talent group(s)"
    fi
    printf '%s;\n' "$statement" \
        > "$REPORTS_DIR/$RUN_ID/generated-characters-character_talent.sql"
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    if checkpoint_complete characters "$target_table" 0 0 "$hash"; then
        log "Skipping completed transform: $target_table"
        return
    fi
    prepare_target_for_copy characters "$target_table"
    expected=$(mysql_query -e "
        SELECT COUNT(*) FROM (
            SELECT guid,spell FROM \`$SOURCE_SCHEMA\`.character_talent GROUP BY guid,spell
        ) x;")
    mysql_query -e "
        SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';
        START TRANSACTION;
        $statement;
        COMMIT;"
    actual=$(mysql_query -e "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`;")
    [[ $actual == "$expected" ]] ||
        die "character_talent count mismatch: expected=$expected actual=$actual"
    record_checkpoint characters character_talent "$target_table" 0 0 "$hash" "$expected" "$actual"
}

load_channels_and_bans() {
    local statement="
        INSERT INTO \`$TARGET_SCHEMA\`.channels
            (channelId,name,team,announce,ownership,password,lastUsed)
        SELECT ROW_NUMBER() OVER (ORDER BY team,BINARY name),name,team,announce,
               ownership,password,lastUsed
        FROM \`$SOURCE_SCHEMA\`.channels;
        INSERT INTO \`$TARGET_SCHEMA\`.channels_bans (channelId,playerGUID,banTime)
        SELECT DISTINCT t.channelId,
               CAST(MOD(CAST(j.token AS DECIMAL(20,0)),4294967296) AS UNSIGNED),
               4294967295
        FROM \`$SOURCE_SCHEMA\`.channels s
        JOIN \`$TARGET_SCHEMA\`.channels t
          ON BINARY t.name=BINARY s.name AND t.team=s.team
        JOIN JSON_TABLE(
            CONCAT('[\"',REPLACE(TRIM(s.bannedList),' ','\",\"'),'\"]'),
            '\$[*]' COLUMNS(token VARCHAR(32) PATH '\$')
        ) j
        WHERE TRIM(s.bannedList) <> ''
          AND j.token REGEXP '^[0-9]+$'"
    local hash expected actual
    printf '%s;\n' "$statement" \
        > "$REPORTS_DIR/$RUN_ID/generated-characters-channels.sql"
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    if checkpoint_complete characters channels 0 0 "$hash"; then
        log "Skipping completed transform: channels and channels_bans"
        return
    fi
    prepare_target_for_copy characters channels
    mysql_query -e "DELETE FROM \`$TARGET_SCHEMA\`.channels_bans;"
    expected=$(mysql_query -e "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.channels;")
    mysql_query -e "
        SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';
        START TRANSACTION;
        $statement;
        COMMIT;"
    actual=$(mysql_query -e "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.channels;")
    [[ $actual == "$expected" ]] ||
        die "channels count mismatch: expected=$expected actual=$actual"
    record_checkpoint characters channels channels 0 0 "$hash" "$expected" "$actual"
}

handle_noncopy_mapping() {
    local kind=$1 source_table=$2 target_table=$3 disposition=$4 approval=$5 validation=$6
    case "$disposition" in
        TARGET_SEED)
            log "Retaining AzerothCore seed table: $target_table"
            ;;
        TARGET_EMPTY)
            [[ $(mysql_query -e "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`;") == 0 ]] ||
                die "Target-empty table contains seed rows unexpectedly: $target_table"
            ;;
        DERIVED)
            log "Target table populated by an earlier approved transform: $target_table"
            ;;
        SOURCE_ARCHIVE)
            local rows
            rows=$(mysql_query -e "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\`;")
            if [[ $rows != 0 ]]; then
                [[ $approval == APPROVED && $ALLOW_SOURCE_ARCHIVE == 1 ]] ||
                    die "$source_table has $rows row(s) and is not approved for archival"
                log "WARNING: $source_table has $rows source-only row(s); disposition: $validation"
            fi
            ;;
        BLOCKED)
            local blocked_rows
            blocked_rows=$(mysql_query -e "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\`;")
            [[ $blocked_rows == 0 ]] ||
                die "Blocked mapping $source_table has $blocked_rows row(s): $validation"
            ;;
        *)
            die "Unsupported mapping disposition: $disposition"
            ;;
    esac
}

perform_load() {
    local kind=$1
    LOAD_KIND=$kind
    require_phase assemble
    [[ $kind == auth ]] || require_phase load-auth
    schemas_for_kind "$kind"
    assert_schema_unchanged "$kind" "$SOURCE_SCHEMA"
    assert_source_counts_unchanged "$kind" "$SOURCE_SCHEMA"
    mapping_inventory_check "$kind"

    local mapping_file
    mapping_file=$(mapping_file_for "$kind")
    local source_table target_table _source_columns _target_columns expression
    local _default_policy _dependency_group disposition validation approval
    while IFS=, read -r source_table target_table _source_columns _target_columns expression \
        _default_policy _dependency_group disposition validation approval; do
        [[ $source_table == source_table ]] && continue
        [[ $source_table == "-" ]] || validate_identifier "${source_table//+/_}" source_table
        [[ $target_table == "-" ]] || validate_identifier "$target_table" target_table

        case "$disposition" in
            COPY)
                local spec
                spec=$(build_common_spec "$source_table" "$target_table")
                local generated_targets generated_expressions
                IFS=$'\t' read -r generated_targets generated_expressions <<< "$spec"
                [[ -n $generated_targets && -n $generated_expressions ]] ||
                    die "No common columns for $source_table -> $target_table"
                load_statement_chunks "$kind" "$source_table" "$target_table" \
                    "$generated_targets" "$generated_expressions"
                ;;
            TRANSFORM)
                if [[ $expression == ITEM_LOOT_STORAGE ]]; then
                    load_item_loot_storage
                elif [[ $expression == CHARACTER_TALENTS ]]; then
                    load_character_talents
                elif [[ $expression == CHANNELS ]]; then
                    load_channels_and_bans
                elif [[ $expression == RBAC_ACCOUNT_PERMISSIONS ]]; then
                    load_rbac_account_permissions
                else
                    local transform_spec transformed_targets transformed_expressions
                    transform_spec=$(build_named_transform_spec "$expression")
                    IFS=$'\t' read -r transformed_targets transformed_expressions <<< "$transform_spec"
                    if [[ $expression == CHARACTERS ]]; then
                        validate_common_values characters characters name
                        local null_names invalid_names
                        null_names=$(mysql_query -e "
                            SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.characters WHERE name IS NULL;")
                        invalid_names=$(mysql_query -e "
                            SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.characters
                            WHERE
                                (
                                    name IS NULL
                                    AND (
                                        deleteDate IS NULL
                                        OR deleteInfos_Name IS NULL
                                        OR deleteInfos_Account IS NULL
                                        OR account <> 0
                                    )
                                )
                                OR (name = '' AND deleteDate IS NULL)
                                OR (
                                    name IS NOT NULL
                                    AND name <> ''
                                    AND (
                                        deleteDate IS NOT NULL
                                        OR account = 0
                                    )
                                );")
                        if [[ $invalid_names != 0 ]]; then
                            record_reject characters "*" NULL_CHARACTER_NAME \
                                "$invalid_names active or malformed row(s) have no character name"
                            die "characters contains $invalid_names active or malformed unnamed row(s)"
                        fi
                        if [[ $null_names != 0 ]]; then
                            log "Converting $null_names TrinityCore soft-deleted character name(s) from NULL to empty string"
                        fi
                    elif [[ $expression == ACCOUNT ]]; then
                        local long_os
                        long_os=$(mysql_query -e "
                            SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.account
                            WHERE CHAR_LENGTH(os) > 3;")
                        if [[ $long_os != 0 ]]; then
                            record_reject account "*" OS_VALUE_TOO_LONG \
                                "$long_os account row(s) have os longer than 3 characters"
                            die "account.os has $long_os value(s) longer than 3 characters"
                        fi
                    fi
                    load_statement_chunks "$kind" "$source_table" "$target_table" \
                        "$transformed_targets" "$transformed_expressions"
                fi
                ;;
            TARGET_SEED|TARGET_EMPTY|DERIVED|SOURCE_ARCHIVE|BLOCKED)
                handle_noncopy_mapping "$kind" "$source_table" "$target_table" \
                    "$disposition" "$approval" "$validation"
                ;;
            *)
                die "Unknown disposition in $mapping_file: $disposition"
                ;;
        esac
    done < "$mapping_file"

    if [[ $kind == characters ]]; then
        mysql_query -e "
            INSERT INTO \`$TARGET_AUTH_SCHEMA\`.realmcharacters (realmid, acctid, numchars)
            SELECT new.realmid,new.acctid,new.numchars
            FROM (
                SELECT $REALM_ID AS realmid,a.id AS acctid,LEAST(COUNT(c.guid),255) AS numchars
                FROM \`$TARGET_AUTH_SCHEMA\`.account a
                LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.account=a.id
                GROUP BY a.id
            ) AS new
            ON DUPLICATE KEY UPDATE numchars=new.numchars;"
    fi

    log "Completed approved $kind mappings"
}
