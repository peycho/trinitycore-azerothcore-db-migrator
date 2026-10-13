#!/usr/bin/env bash
# shellcheck disable=SC2016

mapping_file_for() {
    printf '%s/mappings/%s/%s.csv\n' "$MIGRATION_ROOT" "$MIGRATION_DIRECTION" "$1"
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
        if [[ -n $target_table && $target_table != "-" ]]; then
            local target_part
            IFS=+ read -ra target_parts <<< "$target_table"
            for target_part in "${target_parts[@]}"; do
                mapped_target["$target_part"]=1
            done
        fi
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
        UPTIME)
            printf '%s\t%s\n' \
                '`realmid`,`starttime`,`uptime`,`maxplayers`,`revision`,`EndTime`,`ShutdownType`,`ExitCode`,`ShutdownReason`' \
                $'s.`realmid`,s.`starttime`,s.`uptime`,s.`maxplayers`,s.`revision`,s.`starttime`+s.`uptime`,0,NULL,\'\''
            ;;
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
        ACCOUNT_REVERSE)
            printf '%s\t%s\n' \
                '`id`,`username`,`salt`,`verifier`,`session_key_auth`,`session_key_bnet`,`totp_secret`,`email`,`reg_mail`,`joindate`,`last_ip`,`last_attempt_ip`,`failed_logins`,`locked`,`lock_country`,`last_login`,`online`,`expansion`,`mutetime`,`mutereason`,`muteby`,`locale`,`os`,`timezone_offset`,`recruiter`' \
                's.`id`,s.`username`,s.`salt`,s.`verifier`,s.`session_key`,NULL,s.`totp_secret`,s.`email`,s.`reg_mail`,s.`joindate`,s.`last_ip`,s.`last_attempt_ip`,s.`failed_logins`,s.`locked`,s.`lock_country`,s.`last_login`,0,s.`expansion`,s.`mutetime`,s.`mutereason`,s.`muteby`,s.`locale`,s.`os`,0,s.`recruiter`'
            ;;
        ACCOUNT_ACCESS_REVERSE)
            printf '%s\t%s\n' \
                '`AccountID`,`SecurityLevel`,`RealmID`,`Comment`' \
                's.`id`,s.`gmlevel`,s.`RealmID`,s.`comment`'
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
        CHARACTERS_REVERSE)
            mysql_query -e "SET SESSION group_concat_max_len=1048576;
                SELECT
                    GROUP_CONCAT(CONCAT('\`', REPLACE(t.COLUMN_NAME, '\`', '\`\`'), '\`')
                                 ORDER BY t.ORDINAL_POSITION SEPARATOR ','),
                    GROUP_CONCAT(
                        CASE t.COLUMN_NAME
                            WHEN 'online' THEN '0'
                            WHEN 'name' THEN 'NULLIF(s.\`name\`,'''')'
                            ELSE CONCAT('s.\`', REPLACE(t.COLUMN_NAME, '\`', '\`\`'), '\`')
                        END
                        ORDER BY t.ORDINAL_POSITION SEPARATOR ',')
                FROM information_schema.COLUMNS t
                JOIN information_schema.COLUMNS s
                  ON s.TABLE_SCHEMA='$(sql_escape "$SOURCE_SCHEMA")'
                 AND s.TABLE_NAME='characters'
                 AND s.COLUMN_NAME=t.COLUMN_NAME
                WHERE t.TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
                  AND t.TABLE_NAME='characters'
                  AND t.EXTRA NOT LIKE '%GENERATED%';"
            ;;
        CHARACTER_INSTANCE)
            printf '%s\t%s\n' \
                '`guid`,`instance`,`permanent`,`extended`' \
                's.`guid`,s.`instance`,s.`permanent`,IF(s.`extendState`=2,1,0)'
            ;;
        CHARACTER_INSTANCE_REVERSE)
            printf '%s\t%s\n' \
                '`guid`,`instance`,`permanent`,`extendState`' \
                's.`guid`,s.`instance`,s.`permanent`,IF(s.`extended`=1,2,1)'
            ;;
        CHARACTER_ENTRY_POINT)
            printf '%s\t%s\n' \
                '`guid`,`joinX`,`joinY`,`joinZ`,`joinO`,`joinMapId`,`taxiPath0`,`taxiPath1`,`mountSpell`' \
                's.`guid`,s.`joinX`,s.`joinY`,s.`joinZ`,s.`joinO`,s.`joinMapId`,s.`taxiStart`,s.`taxiEnd`,s.`mountSpell`'
            ;;
        CHARACTER_ENTRY_POINT_REVERSE)
            printf '%s\t%s\n' \
                '`guid`,`instanceId`,`team`,`joinX`,`joinY`,`joinZ`,`joinO`,`joinMapId`,`taxiStart`,`taxiEnd`,`mountSpell`' \
                's.`guid`,0,0,s.`joinX`,s.`joinY`,s.`joinZ`,s.`joinO`,s.`joinMapId`,s.`taxiPath0`,s.`taxiPath1`,s.`mountSpell`'
            ;;
        CHARACTER_SPELL_COOLDOWN)
            printf '%s\t%s\n' \
                '`guid`,`spell`,`category`,`item`,`time`,`needSend`' \
                's.`guid`,s.`spell`,s.`categoryId`,s.`item`,GREATEST(s.`time`,s.`categoryEnd`),1'
            ;;
        CHARACTER_SPELL_COOLDOWN_REVERSE)
            printf '%s\t%s\n' \
                '`guid`,`spell`,`item`,`time`,`categoryId`,`categoryEnd`' \
                's.`guid`,s.`spell`,s.`item`,s.`time`,COALESCE(s.`category`,0),IF(COALESCE(s.`category`,0)=0,0,s.`time`)'
            ;;
        CHARACTER_SPELL)
            printf '%s\t%s\n' \
                '`guid`,`spell`,`specMask`' \
                's.`guid`,s.`spell`,3'
            ;;
        CHARACTER_SPELL_REVERSE)
            printf '%s\t%s\n' \
                '`guid`,`spell`,`active`,`disabled`' \
                's.`guid`,s.`spell`,1,0'
            ;;
        CHARACTER_ARENA_STATS)
            printf '%s\t%s\n' \
                '`guid`,`slot`,`matchMakerRating`,`maxMMR`' \
                's.`guid`,s.`slot`,s.`matchMakerRating`,s.`matchMakerRating`'
            ;;
        CHARACTER_ARENA_STATS_REVERSE)
            printf '%s\t%s\n' \
                '`guid`,`slot`,`matchMakerRating`' \
                's.`guid`,s.`slot`,s.`matchMakerRating`'
            ;;
        GM_SURVEY)
            printf '%s\t%s\n' \
                '`surveyId`,`guid`,`mainSurvey`,`comment`,`createTime`,`maxMMR`' \
                's.`surveyId`,s.`guid`,s.`mainSurvey`,s.`comment`,s.`createTime`,0'
            ;;
        GM_SURVEY_REVERSE)
            printf '%s\t%s\n' \
                '`surveyId`,`guid`,`mainSurvey`,`comment`,`createTime`' \
                's.`surveyId`,s.`guid`,s.`mainSurvey`,s.`comment`,s.`createTime`'
            ;;
        PET_SPELL_COOLDOWN)
            printf '%s\t%s\n' \
                '`guid`,`spell`,`category`,`time`' \
                's.`guid`,s.`spell`,s.`categoryId`,GREATEST(s.`time`,s.`categoryEnd`)'
            ;;
        PET_SPELL_COOLDOWN_REVERSE)
            printf '%s\t%s\n' \
                '`guid`,`spell`,`time`,`categoryId`,`categoryEnd`' \
                's.`guid`,s.`spell`,s.`time`,COALESCE(s.`category`,0),IF(COALESCE(s.`category`,0)=0,0,s.`time`)'
            ;;
        PETITION)
            printf '%s\t%s\n' \
                '`ownerguid`,`petitionguid`,`petition_id`,`name`,`type`' \
                's.`ownerguid`,s.`petitionguid`,s.`petitionguid`,s.`name`,s.`type`'
            ;;
        PETITION_REVERSE)
            printf '%s\t%s\n' \
                '`ownerguid`,`petitionguid`,`name`,`type`' \
                's.`ownerguid`,s.`petitionguid`,s.`name`,s.`type`'
            ;;
        PETITION_SIGN)
            printf '%s\t%s\n' \
                '`ownerguid`,`petitionguid`,`petition_id`,`playerguid`,`player_account`,`type`' \
                's.`ownerguid`,s.`petitionguid`,s.`petitionguid`,s.`playerguid`,s.`player_account`,s.`type`'
            ;;
        PETITION_SIGN_REVERSE)
            printf '%s\t%s\n' \
                '`ownerguid`,`petitionguid`,`playerguid`,`player_account`,`type`' \
                's.`ownerguid`,s.`petitionguid`,s.`playerguid`,s.`player_account`,s.`type`'
            ;;
        *)
            die "Unknown named transform: $transform"
            ;;
    esac
}

leading_numeric_primary_key() {
    local table=$1
    mysql_query -e "
        SELECT COALESCE(MAX(CASE
            WHEN k.ORDINAL_POSITION=1
             AND c.DATA_TYPE IN ('tinyint','smallint','mediumint','int','bigint')
            THEN k.COLUMN_NAME ELSE '' END),'')
        FROM information_schema.KEY_COLUMN_USAGE k
        JOIN information_schema.COLUMNS c
          ON c.TABLE_SCHEMA=k.TABLE_SCHEMA
         AND c.TABLE_NAME=k.TABLE_NAME
         AND c.COLUMN_NAME=k.COLUMN_NAME
        WHERE k.TABLE_SCHEMA='$(sql_escape "$SOURCE_SCHEMA")'
          AND k.TABLE_NAME='$(sql_escape "$table")'
          AND k.CONSTRAINT_NAME='PRIMARY';"
}

source_snapshot_count() {
    local kind=$1 table=$2
    mysql_query -e "
        SELECT row_count
        FROM \`$CONTROL_SCHEMA\`.source_table_snapshot
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND table_name='$(sql_escape "$table")';"
}

defer_secondary_indexes() {
    local kind=$1 target_table=$2 source_rows=$3
    [[ $DEFER_SECONDARY_INDEXES == 1 && $source_rows -ge $LARGE_TABLE_ROWS ]] || return

    local foreign_keys
    foreign_keys=$(mysql_query -e "
        SELECT COUNT(*)
        FROM information_schema.REFERENTIAL_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
          AND TABLE_NAME='$(sql_escape "$target_table")';")
    [[ $foreign_keys == 0 ]] || {
        log "Keeping secondary indexes for $target_table because it owns foreign keys"
        return
    }

    local existing
    existing=$(mysql_query -e "
        SELECT COUNT(*)
        FROM \`$CONTROL_SCHEMA\`.deferred_index
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND table_name='$(sql_escape "$target_table")';")
    if [[ $existing == 0 ]]; then
        local create_ddl line index_name index_ddl ddl_hash index_order=0 eligible
        create_ddl=$(mysql_query -e "SHOW CREATE TABLE \`$TARGET_SCHEMA\`.\`$target_table\`;")
        while IFS= read -r line; do
            index_name=$(sed -nE 's/^  KEY `([^`]+)`.*/\1/p' <<< "$line")
            [[ -n $index_name ]] || continue
            eligible=$(mysql_query -e "
                SELECT COUNT(*)
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
                  AND TABLE_NAME='$(sql_escape "$target_table")'
                  AND INDEX_NAME='$(sql_escape "$index_name")'
                  AND NON_UNIQUE=1 AND INDEX_TYPE='BTREE';")
            (( eligible > 0 )) || continue
            index_order=$((index_order + 1))
            line=${line%,}
            index_ddl="ADD ${line#"  "}"
            ddl_hash=$(printf '%s' "$index_ddl" | sha256sum | awk '{print $1}')
            mysql_query -e "
                INSERT INTO \`$CONTROL_SCHEMA\`.deferred_index
                    (run_id,database_kind,table_name,index_name,index_order,
                     index_ddl,ddl_hash,status)
                VALUES
                    ('$(sql_escape "$RUN_ID")','$(sql_escape "$kind")',
                     '$(sql_escape "$target_table")','$(sql_escape "$index_name")',
                     $index_order,'$(sql_escape "$index_ddl")','$ddl_hash',
                     'DISCOVERED');"
        done <<< "$create_ddl"
    fi

    local known_name known_status present
    while IFS=$'\t' read -r known_name known_status; do
        present=$(mysql_query -e "
            SELECT COUNT(*) FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
              AND TABLE_NAME='$(sql_escape "$target_table")'
              AND INDEX_NAME='$(sql_escape "$known_name")';")
        if [[ $known_status == DISCOVERED && $present == 0 ]]; then
            mysql_query -e "
                UPDATE \`$CONTROL_SCHEMA\`.deferred_index
                SET status='DROPPED',started_at=COALESCE(started_at,UTC_TIMESTAMP()),
                    detail='reconciled after interrupted drop'
                WHERE run_id='$(sql_escape "$RUN_ID")'
                  AND database_kind='$(sql_escape "$kind")'
                  AND table_name='$(sql_escape "$target_table")'
                  AND index_name='$(sql_escape "$known_name")';"
        fi
    done < <(mysql_query -e "
        SELECT index_name,status
        FROM \`$CONTROL_SCHEMA\`.deferred_index
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND table_name='$(sql_escape "$target_table")';")

    local drop_clauses
    drop_clauses=$(mysql_query -e "
        SELECT GROUP_CONCAT(
                 CONCAT('DROP INDEX \`',REPLACE(index_name,'\`','\`\`'),'\`')
                 ORDER BY index_name SEPARATOR ','
               )
        FROM \`$CONTROL_SCHEMA\`.deferred_index
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND table_name='$(sql_escape "$target_table")'
          AND status='DISCOVERED';")
    [[ -n $drop_clauses && $drop_clauses != NULL ]] || return

    log "Deferring non-unique secondary indexes for $target_table"
    mysql_query -e "
        ALTER TABLE \`$TARGET_SCHEMA\`.\`$target_table\` $drop_clauses;
        UPDATE \`$CONTROL_SCHEMA\`.deferred_index
        SET status='DROPPED',started_at=UTC_TIMESTAMP(),detail=NULL
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND table_name='$(sql_escape "$target_table")'
          AND status='DISCOVERED';"
}

restore_secondary_indexes() {
    local kind=$1 target_table=$2
    local hash_mismatches
    hash_mismatches=$(mysql_query -e "
        SELECT COUNT(*)
        FROM \`$CONTROL_SCHEMA\`.deferred_index
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND table_name='$(sql_escape "$target_table")'
          AND SHA2(index_ddl,256)<>ddl_hash;")
    [[ $hash_mismatches == 0 ]] ||
        die "Deferred index registry hash mismatch for $kind.$target_table"
    local known_name present
    while IFS= read -r known_name; do
        present=$(mysql_query -e "
            SELECT COUNT(*) FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
              AND TABLE_NAME='$(sql_escape "$target_table")'
              AND INDEX_NAME='$(sql_escape "$known_name")';")
        if [[ $present != 0 ]]; then
            mysql_query -e "
                UPDATE \`$CONTROL_SCHEMA\`.deferred_index
                SET status='RESTORED',finished_at=COALESCE(finished_at,UTC_TIMESTAMP()),
                    detail=COALESCE(detail,'reconciled after interrupted rebuild')
                WHERE run_id='$(sql_escape "$RUN_ID")'
                  AND database_kind='$(sql_escape "$kind")'
                  AND table_name='$(sql_escape "$target_table")'
                  AND index_name='$(sql_escape "$known_name")'
                  AND status IN ('DROPPED','FAILED');"
        fi
    done < <(mysql_query -e "
        SELECT index_name
        FROM \`$CONTROL_SCHEMA\`.deferred_index
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND table_name='$(sql_escape "$target_table")'
          AND status IN ('DROPPED','FAILED');")

    local add_clauses
    add_clauses=$(mysql_query -e "
        SET SESSION group_concat_max_len=1048576;
        SELECT GROUP_CONCAT(index_ddl ORDER BY index_order SEPARATOR ',')
        FROM \`$CONTROL_SCHEMA\`.deferred_index
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND table_name='$(sql_escape "$target_table")'
          AND status='DROPPED';")
    [[ -n $add_clauses && $add_clauses != NULL ]] || return

    local started finished
    started=$(date +%s)
    log "Rebuilding deferred secondary indexes for $target_table"
    if mysql_query -e "ALTER TABLE \`$TARGET_SCHEMA\`.\`$target_table\` $add_clauses;"; then
        finished=$(date +%s)
        mysql_query -e "
            UPDATE \`$CONTROL_SCHEMA\`.deferred_index
            SET status='RESTORED',finished_at=UTC_TIMESTAMP(),
                detail='elapsed_seconds=$((finished-started))'
            WHERE run_id='$(sql_escape "$RUN_ID")'
              AND database_kind='$(sql_escape "$kind")'
              AND table_name='$(sql_escape "$target_table")'
              AND status='DROPPED';"
    else
        mysql_query -e "
            UPDATE \`$CONTROL_SCHEMA\`.deferred_index
            SET status='FAILED',finished_at=UTC_TIMESTAMP(),
                detail='index rebuild failed'
            WHERE run_id='$(sql_escape "$RUN_ID")'
              AND database_kind='$(sql_escape "$kind")'
              AND table_name='$(sql_escape "$target_table")'
              AND status='DROPPED';"
        die "Failed to rebuild indexes for $target_table"
    fi
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

execute_transform_atomic() {
    local kind=$1 source_table=$2 target_table=$3 hash=$4 expected=$5
    local cleanup_sql=$6 statement=$7
    local actual
    defer_secondary_indexes "$kind" "$target_table" "$expected"
    mark_operation_running "load-$kind" load-transform "$kind" "$target_table" \
        0 0 "$hash" "$expected"
    if ! actual=$(mysql_query -e "
        SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';
        START TRANSACTION;
        $cleanup_sql
        $statement;
        SELECT COUNT(*) INTO @target_rows
        FROM \`$TARGET_SCHEMA\`.\`$target_table\`;
        SET @checkpoint_status=IF(@target_rows=$expected,'COMPLETE','FAILED');
        INSERT INTO \`$CONTROL_SCHEMA\`.chunk_checkpoint
            (run_id,database_kind,source_table,target_table,chunk_start,chunk_end,
             script_hash,source_rows,target_rows,status)
        VALUES
            ('$(sql_escape "$RUN_ID")','$(sql_escape "$kind")',
             '$(sql_escape "$source_table")','$(sql_escape "$target_table")',
             0,0,'$hash',$expected,@target_rows,@checkpoint_status) AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash,source_rows=new.source_rows,
            target_rows=new.target_rows,status=new.status,
            finished_at=UTC_TIMESTAMP();
        INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
            (run_id,phase_name,operation_name,database_kind,table_name,
             chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
             status,started_at,finished_at,detail)
        VALUES
            ('$(sql_escape "$RUN_ID")','load-$kind','load-transform',
             '$(sql_escape "$kind")','$(sql_escape "$target_table")',
             0,0,'$hash',$expected,@target_rows,@checkpoint_status,
             UTC_TIMESTAMP(),UTC_TIMESTAMP(),'atomic transform and checkpoint') AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash,planned_rows=new.planned_rows,
            affected_rows=new.affected_rows,status=new.status,
            finished_at=new.finished_at,detail=new.detail;
        COMMIT;
        SELECT @target_rows;"); then
        die "Atomic transform failed: $kind.$target_table"
    fi
    [[ $actual == "$expected" ]] ||
        die "$target_table count mismatch: expected=$expected actual=$actual"
    restore_secondary_indexes "$kind" "$target_table"
    log "Loaded transform $target_table: $actual row(s)"
}

execute_multi_transform_atomic() {
    local kind=$1 source_label=$2 target_label=$3 hash=$4 expected=$5
    local cleanup_sql=$6 statement=$7 count_sql=$8
    if checkpoint_complete "$kind" "$target_label" 0 0 "$hash"; then
        log "Skipping completed transform: $target_label"
        return
    fi
    local actual
    mark_operation_running "load-$kind" load-transform "$kind" "$target_label" \
        0 0 "$hash" "$expected"
    actual=$(mysql_query -e "
        SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';
        START TRANSACTION;
        $cleanup_sql
        $statement;
        SELECT ($count_sql) INTO @target_rows;
        SET @checkpoint_status=IF(@target_rows=$expected,'COMPLETE','FAILED');
        INSERT INTO \`$CONTROL_SCHEMA\`.chunk_checkpoint
            (run_id,database_kind,source_table,target_table,chunk_start,chunk_end,
             script_hash,source_rows,target_rows,status)
        VALUES
            ('$(sql_escape "$RUN_ID")','$(sql_escape "$kind")',
             '$(sql_escape "$source_label")','$(sql_escape "$target_label")',
             0,0,'$hash',$expected,@target_rows,@checkpoint_status) AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash,source_rows=new.source_rows,
            target_rows=new.target_rows,status=new.status,
            finished_at=UTC_TIMESTAMP();
        INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
            (run_id,phase_name,operation_name,database_kind,table_name,
             chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
             status,started_at,finished_at,detail)
        VALUES
            ('$(sql_escape "$RUN_ID")','load-$kind','load-transform',
             '$(sql_escape "$kind")','$(sql_escape "$target_label")',
             0,0,'$hash',$expected,@target_rows,@checkpoint_status,
             UTC_TIMESTAMP(),UTC_TIMESTAMP(),'atomic multi-table transform') AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash,planned_rows=new.planned_rows,
            affected_rows=new.affected_rows,status=new.status,
            finished_at=new.finished_at,detail=new.detail;
        COMMIT;
        SELECT @target_rows;")
    [[ $actual == "$expected" ]] ||
        die "$target_label count mismatch: expected=$expected actual=$actual"
    log "Loaded transform $target_label: $actual row(s)"
}

load_statement_chunks() {
    local kind=$1 source_table=$2 target_table=$3 target_columns=$4 expressions=$5
    local primary_key
    local expected_rows
    expected_rows=$(source_snapshot_count "$kind" "$source_table")
    [[ -n $expected_rows ]] || die "Missing source snapshot count for $kind.$source_table"
    primary_key=$(leading_numeric_primary_key "$source_table")
    if (( expected_rows < LARGE_TABLE_ROWS )); then
        primary_key=
    elif [[ -n $primary_key ]] && ! mysql_query -e "
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA='$(sql_escape "$TARGET_SCHEMA")'
          AND TABLE_NAME='$(sql_escape "$target_table")'
          AND COLUMN_NAME='$(sql_escape "$primary_key")';" | grep -q 1; then
        primary_key=
    fi
    local base_statement="INSERT INTO \`$TARGET_SCHEMA\`.\`$target_table\` ($target_columns) SELECT $expressions FROM \`$SOURCE_SCHEMA\`.\`$source_table\` s"
    printf '%s;\n' "$base_statement" \
        > "$REPORTS_DIR/$RUN_ID/generated-$kind-$target_table.sql"
    local script_hash
    script_hash=$(printf '%s' "$base_statement" | sha256sum | awk '{print $1}')
    prepare_target_for_copy "$kind" "$target_table"
    defer_secondary_indexes "$kind" "$target_table" "$expected_rows"

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
            chunk_end=$((chunk_start + LOAD_CHUNK_SIZE - 1))
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
            local inserted delete_clause
            if [[ -n $primary_key ]]; then
                delete_clause="WHERE \`$primary_key\` BETWEEN $chunk_start AND $chunk_end"
            else
                delete_clause=
            fi
            mark_operation_running "load-$kind" load-table "$kind" "$target_table" \
                "$chunk_start" "$chunk_end" "$script_hash" 0

            inserted=$(mysql_query -e "
                SET SESSION time_zone='+00:00';
                SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';
                START TRANSACTION;
                DELETE FROM \`$TARGET_SCHEMA\`.\`$target_table\` $delete_clause;
                $base_statement$where_clause;
                SET @inserted_rows=ROW_COUNT();
                INSERT INTO \`$CONTROL_SCHEMA\`.chunk_checkpoint
                    (run_id,database_kind,source_table,target_table,chunk_start,
                     chunk_end,script_hash,source_rows,target_rows,status)
                VALUES
                    ('$(sql_escape "$RUN_ID")','$(sql_escape "$kind")',
                     '$(sql_escape "$source_table")','$(sql_escape "$target_table")',
                     $chunk_start,$chunk_end,'$script_hash',
                     @inserted_rows,@inserted_rows,'COMPLETE') AS new
                ON DUPLICATE KEY UPDATE
                    script_hash=new.script_hash,source_rows=new.source_rows,
                    target_rows=new.target_rows,status='COMPLETE',
                    finished_at=UTC_TIMESTAMP();
                INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
                    (run_id,phase_name,operation_name,database_kind,table_name,
                     chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
                     status,started_at,finished_at,detail)
                VALUES
                    ('$(sql_escape "$RUN_ID")','load-$kind','load-table',
                     '$(sql_escape "$kind")','$(sql_escape "$target_table")',
                     $chunk_start,$chunk_end,'$script_hash',@inserted_rows,
                     @inserted_rows,'COMPLETE',UTC_TIMESTAMP(),UTC_TIMESTAMP(),
                     'atomic insert and checkpoint') AS new
                ON DUPLICATE KEY UPDATE
                    script_hash=new.script_hash,planned_rows=new.planned_rows,
                    affected_rows=new.affected_rows,status='COMPLETE',
                    finished_at=UTC_TIMESTAMP(),detail=new.detail;
                COMMIT;
                SELECT @inserted_rows;")
            log "Loaded $target_table [$chunk_start,$chunk_end]: $inserted row(s)"
        fi

        [[ -z $primary_key || $chunk_end -ge $maximum ]] && break
        chunk_start=$(mysql_query -e "
            SELECT COALESCE(MIN(\`$primary_key\`),$((maximum + 1)))
            FROM \`$SOURCE_SCHEMA\`.\`$source_table\`
            WHERE \`$primary_key\` > $chunk_end;")
        (( chunk_start > maximum )) && break
    done

    local loaded_rows
    loaded_rows=$(mysql_query -e "
        SELECT COALESCE(SUM(source_rows),0)
        FROM \`$CONTROL_SCHEMA\`.chunk_checkpoint
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND source_table='$(sql_escape "$source_table")'
          AND target_table='$(sql_escape "$target_table")'
          AND script_hash='$script_hash' AND status='COMPLETE';")
    [[ $loaded_rows == "$expected_rows" ]] ||
        die "Loaded row total mismatch for $target_table: expected=$expected_rows actual=$loaded_rows"
    restore_secondary_indexes "$kind" "$target_table"
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
    local expected
    expected=$(source_snapshot_count auth rbac_account_permissions)
    execute_transform_atomic auth rbac_account_permissions "$target_table" \
        "$hash" "$expected" \
        "DELETE FROM \`$TARGET_SCHEMA\`.\`$target_table\`;" "$statement"
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
    local expected
    expected=$(mysql_query -e "
        SELECT
          (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`item_loot_items\`) +
          (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`item_loot_money\` WHERE money > 0);")
    execute_transform_atomic characters item_loot_items+item_loot_money \
        "$target_table" "$hash" "$expected" \
        "DELETE FROM \`$TARGET_SCHEMA\`.\`$target_table\`;" "$statement"
}

load_character_talents() {
    local target_table=character_talent
    local statement="
        INSERT INTO \`$TARGET_SCHEMA\`.\`character_talent\` (guid,spell,specMask)
        SELECT guid,spell,BIT_OR(CAST(1 AS UNSIGNED) << talentGroup)
        FROM \`$SOURCE_SCHEMA\`.\`character_talent\`
        GROUP BY guid,spell"
    local hash expected
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
    expected=$(mysql_query -e "
        SELECT COUNT(*) FROM (
            SELECT guid,spell FROM \`$SOURCE_SCHEMA\`.character_talent GROUP BY guid,spell
        ) x;")
    execute_transform_atomic characters character_talent "$target_table" \
        "$hash" "$expected" \
        "DELETE FROM \`$TARGET_SCHEMA\`.\`$target_table\`;" "$statement"
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
    local hash expected
    printf '%s;\n' "$statement" \
        > "$REPORTS_DIR/$RUN_ID/generated-characters-channels.sql"
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    if checkpoint_complete characters channels 0 0 "$hash"; then
        log "Skipping completed transform: channels and channels_bans"
        return
    fi
    expected=$(mysql_query -e "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.channels;")
    execute_transform_atomic characters channels channels "$hash" "$expected" \
        "DELETE FROM \`$TARGET_SCHEMA\`.channels_bans;
         DELETE FROM \`$TARGET_SCHEMA\`.channels;" "$statement"
}

load_item_loot_reverse() {
    local normalized
    normalized=$(normalized_reverse_loot_query)
    local statement="
        INSERT INTO \`$TARGET_SCHEMA\`.item_loot_items
            (container_id,item_id,item_count,item_index,follow_rules,ffa,blocked,
             counted,under_threshold,needs_quest,rnd_prop,rnd_suffix)
        SELECT containerGUID,itemid,\`count\`,normalized_index,follow_loot_rules,
               freeforall,is_blocked,is_counted,is_underthreshold,needs_quest,
               randomPropertyId,randomSuffix
        FROM ($normalized) normalized;
        INSERT INTO \`$TARGET_SCHEMA\`.item_loot_money (container_id,money)
        SELECT containerGUID,\`count\`
        FROM \`$SOURCE_SCHEMA\`.item_loot_storage WHERE itemid=0"
    local ambiguous
    ambiguous=$(mysql_query -e "
        SELECT COUNT(*) FROM (
          SELECT containerGUID FROM \`$SOURCE_SCHEMA\`.item_loot_storage
          WHERE itemid=0 GROUP BY containerGUID HAVING COUNT(*)>1
        ) x;")
    [[ $ambiguous == 0 ]] ||
        die "item_loot_storage has $ambiguous container(s) with multiple money rows"
    local expected hash
    expected=$(mysql_query -e "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.item_loot_storage;")
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    printf '%s;\n' "$statement" > "$REPORTS_DIR/$RUN_ID/generated-characters-item-loot-reverse.sql"
    {
        printf 'container_guid\titem_id\toriginal_index\tnormalized_index\tquantity\n'
        mysql_query -e "SELECT containerGUID,itemid,item_index,normalized_index,\`count\`
            FROM ($normalized) normalized WHERE item_index<>normalized_index
            ORDER BY containerGUID,normalized_index;"
    } > "$REPORTS_DIR/$RUN_ID/loot-index-normalization.tsv"
    execute_multi_transform_atomic characters item_loot_storage \
        item_loot_items+item_loot_money "$hash" "$expected" \
        "DELETE FROM \`$TARGET_SCHEMA\`.item_loot_items;
         DELETE FROM \`$TARGET_SCHEMA\`.item_loot_money;" \
        "$statement" \
        "(SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.item_loot_items) +
         (SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.item_loot_money)"
}

load_character_talents_reverse() {
    local statement="
        INSERT INTO \`$TARGET_SCHEMA\`.character_talent (guid,spell,talentGroup)
        SELECT guid,spell,0 FROM \`$SOURCE_SCHEMA\`.character_talent
        WHERE specMask & 1
        UNION ALL
        SELECT guid,spell,1 FROM \`$SOURCE_SCHEMA\`.character_talent
        WHERE specMask & 2;"
    local invalid expected hash
    invalid=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.character_talent
        WHERE specMask=0 OR specMask & ~3;")
    [[ $invalid == 0 ]] ||
        die "character_talent has $invalid invalid specMask row(s)"
    expected=$(mysql_query -e "
        SELECT SUM((specMask & 1)<>0)+SUM((specMask & 2)<>0)
        FROM \`$SOURCE_SCHEMA\`.character_talent;")
    expected=${expected:-0}
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    execute_multi_transform_atomic characters character_talent character_talent \
        "$hash" "$expected" "DELETE FROM \`$TARGET_SCHEMA\`.character_talent;" \
        "$statement" "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.character_talent"
}

load_channels_reverse() {
    local statement="
        INSERT INTO \`$TARGET_SCHEMA\`.channels
            (name,team,announce,ownership,password,bannedList,lastUsed)
        SELECT c.name,c.team,c.announce,c.ownership,c.password,
               NULLIF(GROUP_CONCAT(b.playerGUID ORDER BY b.playerGUID SEPARATOR ' '),''),
               c.lastUsed
        FROM \`$SOURCE_SCHEMA\`.channels c
        LEFT JOIN \`$SOURCE_SCHEMA\`.channels_bans b ON b.channelId=c.channelId
        GROUP BY c.channelId,c.name,c.team,c.announce,c.ownership,c.password,c.lastUsed;"
    local expected hash
    expected=$(source_snapshot_count characters channels)
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    execute_multi_transform_atomic characters channels+channels_bans channels \
        "$hash" "$expected" "DELETE FROM \`$TARGET_SCHEMA\`.channels;" \
        "SET SESSION group_concat_max_len=1048576; $statement" \
        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.channels"
}

load_respawn_reverse() {
    local statement="
        INSERT INTO \`$TARGET_SCHEMA\`.respawn
            (type,spawnId,respawnTime,mapId,instanceId)
        SELECT 0,guid,respawnTime,mapId,instanceId
        FROM \`$SOURCE_SCHEMA\`.creature_respawn
        UNION ALL
        SELECT 1,guid,respawnTime,mapId,instanceId
        FROM \`$SOURCE_SCHEMA\`.gameobject_respawn;"
    local expected hash
    expected=$(mysql_query -e "
        SELECT (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.creature_respawn) +
               (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.gameobject_respawn);")
    if (( expected > 0 )); then
        [[ -n $SOURCE_WORLD_SCHEMA ]] ||
            die "SOURCE_WORLD_SCHEMA is required to validate nonempty respawn tables"
        table_exists "$SOURCE_WORLD_SCHEMA" creature ||
            die "World creature table is required for respawn validation"
        table_exists "$SOURCE_WORLD_SCHEMA" gameobject ||
            die "World gameobject table is required for respawn validation"
        local invalid_respawns
        invalid_respawns=$(mysql_query -e "
            SELECT
              (SELECT COUNT(*)
               FROM \`$SOURCE_SCHEMA\`.creature_respawn r
               LEFT JOIN \`$SOURCE_WORLD_SCHEMA\`.creature w ON w.guid=r.guid
               WHERE w.guid IS NULL OR w.map<>r.mapId) +
              (SELECT COUNT(*)
               FROM \`$SOURCE_SCHEMA\`.gameobject_respawn r
               LEFT JOIN \`$SOURCE_WORLD_SCHEMA\`.gameobject w ON w.guid=r.guid
               WHERE w.guid IS NULL OR w.map<>r.mapId);")
        [[ $invalid_respawns == 0 ]] ||
            die "$invalid_respawns respawn row(s) do not match the read-only world schema"
    fi
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    execute_multi_transform_atomic characters creature_respawn+gameobject_respawn \
        respawn "$hash" "$expected" "DELETE FROM \`$TARGET_SCHEMA\`.respawn;" \
        "$statement" "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.respawn"
}

handle_noncopy_mapping() {
    local kind=$1 source_table=$2 target_table=$3 disposition=$4 approval=$5 validation=$6
    case "$disposition" in
        TARGET_SEED)
            log "Retaining target-core seed table: $target_table"
            ;;
        TARGET_EMPTY)
            [[ $(mysql_query -e "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`;") == 0 ]] ||
                die "Target-empty table contains seed rows unexpectedly: $target_table"
            ;;
        DERIVED)
            log "Target table is derived by a later approved phase: $target_table"
            ;;
        SOURCE_ARCHIVE)
            local rows
            rows=$(mysql_query -e "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\`;")
            if [[ $rows != 0 ]]; then
                [[ $ALLOW_SOURCE_ARCHIVE == 1 ]] ||
                    die "$source_table has $rows row(s) and is not approved for archival"
                [[ $approval != REVIEW_REQUIRED || $ALLOW_GAMEPLAY_ARCHIVE == 1 ]] ||
                    die "$source_table requires explicit gameplay-archive approval"
                [[ $(mysql_query -e "
                    SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.archive_manifest
                    WHERE run_id='$(sql_escape "$RUN_ID")'
                      AND database_kind='$(sql_escape "$kind")'
                      AND source_table='$(sql_escape "$source_table")'
                      AND row_count=$rows;") == 1 ]] ||
                    die "$source_table has not been archived for this immutable source snapshot"
                log "WARNING: $source_table has $rows source-only row(s); disposition: $validation"
            fi
            ;;
        BLOCKED)
            local blocked_rows
            if table_exists "$SOURCE_SCHEMA" "$source_table"; then
                blocked_rows=$(mysql_query -e "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\`;")
            else
                blocked_rows=0
            fi
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
    require_phase archive-unsupported
    [[ $kind == auth ]] || require_phase load-auth
    schemas_for_kind "$kind"
    assert_schema_unchanged "$kind" "$SOURCE_SCHEMA"
    check_quiescence
    check_source_representations
    mapping_inventory_check "$kind"

    # Verify required archives before any COPY/TRANSFORM can omit metadata.
    local archive_source _at _asc _atc _ae _ad _ag archive_disposition _av archive_approval
    while IFS=, read -r archive_source _at _asc _atc _ae _ad _ag archive_disposition _av archive_approval; do
        [[ $archive_disposition == SOURCE_ARCHIVE ]] || continue
        require_source_archive "$kind" "$SOURCE_SCHEMA" "$archive_source" "$archive_approval"
    done < "$(mapping_file_for "$kind")"

    local mapping_file
    mapping_file=$(mapping_file_for "$kind")
    local source_table target_table _source_columns _target_columns expression
    local _default_policy _dependency_group disposition validation approval
    while IFS=, read -r source_table target_table _source_columns _target_columns expression \
        _default_policy _dependency_group disposition validation approval; do
        [[ $source_table == source_table ]] && continue
        [[ $source_table == "-" ]] || validate_identifier "${source_table//+/_}" source_table
        [[ $target_table == "-" ]] ||
            validate_identifier "${target_table//+/_}" target_table

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
                elif [[ $expression == ITEM_LOOT_STORAGE_REVERSE ]]; then
                    load_item_loot_reverse
                elif [[ $expression == CHARACTER_TALENTS ]]; then
                    load_character_talents
                elif [[ $expression == CHARACTER_TALENTS_REVERSE ]]; then
                    load_character_talents_reverse
                elif [[ $expression == CHANNELS ]]; then
                    load_channels_and_bans
                elif [[ $expression == CHANNELS_REVERSE ]]; then
                    load_channels_reverse
                elif [[ $expression == RESPAWN_REVERSE ]]; then
                    load_respawn_reverse
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
                    elif [[ $expression == CHARACTERS_REVERSE ]]; then
                        local invalid_empty_names
                        invalid_empty_names=$(mysql_query -e "
                            SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.characters
                            WHERE name='' AND
                              (deleteDate IS NULL OR deleteInfos_Name IS NULL
                               OR deleteInfos_Account IS NULL OR account<>0);")
                        [[ $invalid_empty_names == 0 ]] ||
                            die "characters contains $invalid_empty_names malformed empty name row(s)"
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

    log "Completed approved $kind mappings"
}
