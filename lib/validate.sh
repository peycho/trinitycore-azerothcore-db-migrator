#!/usr/bin/env bash
# shellcheck disable=SC2016

record_validation() {
    local name=$1 severity=$2 observed=$3 expected=$4 passed=$5 detail=${6:-}
    mysql_query -e "
        INSERT INTO \`$CONTROL_SCHEMA\`.validation_result
            (run_id,check_name,severity,observed_value,expected_value,passed,detail)
        VALUES
            ('$(sql_escape "$RUN_ID")','$(sql_escape "$name")','$(sql_escape "$severity")',
             '$(sql_escape "$observed")','$(sql_escape "$expected")',$passed,
             '$(sql_escape "$detail")') AS new
        ON DUPLICATE KEY UPDATE
            severity=new.severity, observed_value=new.observed_value,
            expected_value=new.expected_value, passed=new.passed,
            detail=new.detail, checked_at=UTC_TIMESTAMP();"
}

check_zero() {
    local name=$1
    local query=$2
    local detail=$3
    local observed
    observed=$(mysql_query -e "$query")
    if [[ $observed == 0 ]]; then
        record_validation "$name" ERROR "$observed" 0 1 "$detail"
    else
        record_validation "$name" ERROR "$observed" 0 0 "$detail"
    fi
}

check_equal() {
    local name=$1
    local observed_query=$2
    local expected_query=$3
    local detail=$4
    local observed expected passed=0
    observed=$(mysql_query -e "$observed_query")
    expected=$(mysql_query -e "$expected_query")
    [[ $observed == "$expected" ]] && passed=1
    record_validation "$name" ERROR "$observed" "$expected" "$passed" "$detail"
}

reseed_auto_increment() {
    local schema=$1
    local table column maximum next
    while IFS=$'\t' read -r table column; do
        maximum=$(mysql_query -e "
            SELECT COALESCE(MAX(\`$column\`),0) FROM \`$schema\`.\`$table\`;")
        next=$((maximum + 1))
        mysql_query -e "ALTER TABLE \`$schema\`.\`$table\` AUTO_INCREMENT=$next;"
    done < <(mysql_query -e "
        SELECT TABLE_NAME,COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA='$(sql_escape "$schema")'
          AND EXTRA LIKE '%auto_increment%'
        ORDER BY TABLE_NAME;")
}

analyze_schema() {
    local schema=$1
    local table
    while IFS= read -r table; do
        mysql_query -e "ANALYZE TABLE \`$schema\`.\`$table\`;" >/dev/null
    done < <(mysql_query -e "
        SELECT TABLE_NAME FROM information_schema.TABLES
        WHERE TABLE_SCHEMA='$(sql_escape "$schema")'
          AND TABLE_TYPE='BASE TABLE'
        ORDER BY TABLE_NAME;")
}

validate_mapping_counts() {
    local kind=$1
    schemas_for_kind "$kind"
    local source_table target_table _source_columns _target_columns expression
    local _default_policy _dependency disposition validation _approval
    while IFS=, read -r source_table target_table _source_columns _target_columns expression \
        _default_policy _dependency disposition validation _approval; do
        [[ $source_table == source_table ]] && continue
        case "$disposition" in
            COPY|TRANSFORM)
                if [[ $kind == auth && $target_table == realmcharacters ]]; then
                    continue
                elif [[ $expression == ITEM_LOOT_STORAGE ]]; then
                    check_equal \
                        "count.characters.item_loot_storage" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.item_loot_storage;" \
                        "SELECT
                            (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.item_loot_items) +
                            (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.item_loot_money WHERE money > 0);" \
                        "Combined item and money loot row count"
                elif [[ $expression == CHARACTER_TALENTS ]]; then
                    check_equal \
                        "count.characters.character_talent" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.character_talent;" \
                        "SELECT COUNT(*) FROM (
                            SELECT guid,spell FROM \`$SOURCE_SCHEMA\`.character_talent
                            GROUP BY guid,spell
                         ) x;" \
                        "Talent rows collapse by guid and spell while spec masks are combined"
                else
                    check_equal \
                        "count.$kind.$target_table" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`;" \
                        "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\`;" \
                        "$source_table to $target_table row count"
                fi
                ;;
            SOURCE_ARCHIVE)
                local rows
                rows=$(mysql_query -e "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.\`$source_table\`;")
                record_validation "archive.$kind.$source_table" WARNING "$rows" \
                    "operator-approved" 1 "$validation"
                ;;
        esac
    done < "$(mapping_file_for "$kind")"
}

perform_validation() {
    require_phase load-auth
    require_phase load-characters
    schemas_for_kind characters

    reseed_auto_increment "$TARGET_AUTH_SCHEMA"
    reseed_auto_increment "$TARGET_CHARACTERS_SCHEMA"

    local auth_fingerprint characters_fingerprint expected_auth expected_characters
    auth_fingerprint=$(schema_fingerprint "$TARGET_AUTH_SCHEMA")
    characters_fingerprint=$(schema_fingerprint "$TARGET_CHARACTERS_SCHEMA")
    read -r expected_auth expected_characters < <(
        mysql_query -e "
            SELECT target_auth_fingerprint,target_characters_fingerprint
            FROM \`$CONTROL_SCHEMA\`.migration_run
            WHERE run_id='$(sql_escape "$RUN_ID")';"
    )
    record_validation schema.auth ERROR "$auth_fingerprint" "$expected_auth" \
        "$([[ $auth_fingerprint == "$expected_auth" ]] && printf 1 || printf 0)" \
        "Target auth DDL must match the assembled AzerothCore schema"
    record_validation schema.characters ERROR "$characters_fingerprint" "$expected_characters" \
        "$([[ $characters_fingerprint == "$expected_characters" ]] && printf 1 || printf 0)" \
        "Target characters DDL must match the assembled AzerothCore schema"

    check_zero rejects "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.migration_reject
        WHERE run_id='$(sql_escape "$RUN_ID")';" \
        "No rejected source rows are allowed"
    check_zero account_online "
        SELECT COUNT(*) FROM \`$TARGET_AUTH_SCHEMA\`.account WHERE online <> 0;" \
        "All migrated accounts must start offline"
    check_zero character_online "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters WHERE online <> 0;" \
        "All migrated characters must start offline"
    check_zero character_name_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.characters s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters t ON t.guid=s.guid
        WHERE t.guid IS NULL
           OR NOT (BINARY t.name <=> BINARY COALESCE(s.name,''));" \
        "Active names must be preserved and soft-deleted NULL names must become empty strings"
    check_zero malformed_soft_deleted_character "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters
        WHERE
            (
                name=''
                AND (
                    deleteDate IS NULL
                    OR deleteInfos_Name IS NULL
                    OR deleteInfos_Account IS NULL
                    OR account<>0
                )
            )
            OR (
                name<>''
                AND (
                    deleteDate IS NOT NULL
                    OR account=0
                )
            );" \
        "Every unnamed target character must retain internally consistent soft-delete metadata"
    check_zero character_without_account "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters c
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account a ON a.id=c.account
        WHERE c.account<>0 AND a.id IS NULL;" \
        "Every character must belong to an auth account"
    check_zero inventory_without_character "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.guid
        WHERE c.guid IS NULL;" \
        "Every inventory row must belong to a character"
    check_zero inventory_without_item "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance x ON x.guid=i.item
        WHERE x.guid IS NULL;" \
        "Every inventory row must reference an item instance"
    check_zero inventory_without_bag "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance b ON b.guid=i.bag
        WHERE i.bag <> 0 AND b.guid IS NULL;" \
        "Every nonzero bag identifier must reference an item instance"
    check_zero item_without_owner "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.owner_guid
        WHERE i.owner_guid <> 0 AND c.guid IS NULL;" \
        "Every owned item must reference a character"
    check_zero pet_without_owner "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_pet p
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=p.owner
        WHERE c.guid IS NULL;" \
        "Every pet must belong to a character"
    check_zero guild_member_without_character "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild_member gm
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=gm.guid
        WHERE c.guid IS NULL;" \
        "Every guild member must reference a character"
    check_zero guild_member_without_guild "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild_member gm
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.guild g ON g.guildid=gm.guildid
        WHERE g.guildid IS NULL;" \
        "Every guild member must reference a guild"
    check_zero group_member_without_character "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.group_member gm
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=gm.memberGuid
        WHERE c.guid IS NULL;" \
        "Every group member must reference a character"
    check_zero mail_item_without_mail "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items mi
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.mail m ON m.id=mi.mail_id
        WHERE m.id IS NULL;" \
        "Every mail item must reference a mail row"
    check_zero mail_item_without_item "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items mi
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=mi.item_guid
        WHERE i.guid IS NULL;" \
        "Every mail item must reference an item instance"
    check_zero character_instance_without_instance "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_instance ci
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.instance i ON i.id=ci.instance
        WHERE i.id IS NULL;" \
        "Every character instance binding must reference an instance"
    check_zero item_loot_without_container "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_storage l
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=l.containerGUID
        WHERE i.guid IS NULL;" \
        "Every stored-loot row must reference its container item"
    check_zero realm_character_count_mismatch "
        SELECT COUNT(*)
        FROM \`$TARGET_AUTH_SCHEMA\`.realmcharacters rc
        LEFT JOIN (
            SELECT account,COUNT(*) AS numchars
            FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters
            GROUP BY account
        ) c ON c.account=rc.acctid
        WHERE rc.realmid=$REALM_ID
          AND rc.numchars <> LEAST(COALESCE(c.numchars,0),255);" \
        "realmcharacters must match migrated characters for the configured realm"
    check_zero srp6_binary_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_AUTH_SCHEMA\`.account s
        JOIN \`$TARGET_AUTH_SCHEMA\`.account t ON t.id=s.id
        WHERE BINARY t.salt <> BINARY s.salt
           OR BINARY t.verifier <> BINARY s.verifier
           OR NOT (BINARY t.session_key <=> BINARY s.session_key_auth);" \
        "SRP6 salt/verifier/session bytes must be preserved exactly"
    check_zero account_access_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_AUTH_SCHEMA\`.account_access s
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account_access t
          ON t.id=s.AccountID AND t.RealmID=s.RealmID
        WHERE t.id IS NULL OR t.gmlevel<>s.SecurityLevel
           OR NOT (t.comment <=> s.Comment);" \
        "Account security levels and comments must survive renamed columns"
    check_zero rbac_account_permission_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_AUTH_SCHEMA\`.rbac_account_permissions ap
        JOIN \`$SOURCE_AUTH_SCHEMA\`.rbac_permissions sp
          ON sp.id=ap.permissionId
        JOIN \`$TARGET_AUTH_SCHEMA\`.rbac_permissions tp
          ON BINARY tp.name=BINARY sp.name
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.rbac_account_permissions mapped
          ON mapped.accountId=ap.accountId
         AND mapped.permissionId=tp.id
         AND mapped.realmId=ap.realmId
        WHERE mapped.accountId IS NULL OR mapped.granted<>ap.granted;" \
        "Account RBAC overrides must preserve exact permission names, grants, and realm scopes"
    check_zero character_spell_mask_mismatch "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_spell
        WHERE specMask <> 3;" \
        "TrinityCore character spells must be available in both target specs"
    check_zero character_talent_mask_mismatch "
        SELECT COUNT(*)
        FROM (
            SELECT guid,spell,BIT_OR(CAST(1 AS UNSIGNED) << talentGroup) AS expected
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_talent
            GROUP BY guid,spell
        ) s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_talent t
          ON t.guid=s.guid AND t.spell=s.spell
        WHERE t.guid IS NULL OR t.specMask<>s.expected;" \
        "Talent group rows must combine into the correct target spec mask"
    check_zero character_cooldown_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_spell_cooldown s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_spell_cooldown t
          ON t.guid=s.guid AND t.spell=s.spell
        WHERE t.guid IS NULL OR t.category<>s.categoryId
           OR t.time<>GREATEST(s.time,s.categoryEnd) OR t.needSend<>1;" \
        "Character cooldown category and latest expiration must be preserved"
    check_zero pet_cooldown_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.pet_spell_cooldown s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.pet_spell_cooldown t
          ON t.guid=s.guid AND t.spell=s.spell
        WHERE t.guid IS NULL OR t.category<>s.categoryId
           OR t.time<>GREATEST(s.time,s.categoryEnd);" \
        "Pet cooldown category and latest expiration must be preserved"
    check_zero item_loot_item_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_items s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_storage t
          ON t.containerGUID=s.container_id AND t.itemid=s.item_id
         AND t.count=s.item_count AND t.item_index=s.item_index
        WHERE t.containerGUID IS NULL;" \
        "Every stored item-loot row must be represented in the merged table"
    check_zero item_loot_money_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_money s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_storage t
          ON t.containerGUID=s.container_id AND t.itemid=0 AND t.count=s.money
        WHERE s.money>0 AND t.containerGUID IS NULL;" \
        "Every positive stored-money row must be represented as itemid zero"
    check_zero entry_point_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_battleground_data s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_entry_point t ON t.guid=s.guid
        WHERE t.guid IS NULL OR t.joinX<>s.joinX OR t.joinY<>s.joinY
           OR t.joinZ<>s.joinZ OR t.joinO<>s.joinO OR t.joinMapId<>s.joinMapId
           OR t.taxiPath0<>s.taxiStart OR t.taxiPath1<>s.taxiEnd
           OR t.mountSpell<>s.mountSpell;" \
        "Battleground return state must become character entry-point state"
    check_zero instance_extension_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_instance s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_instance t
          ON t.guid=s.guid AND t.instance=s.instance
        WHERE t.guid IS NULL OR t.extended<>IF(s.extendState=2,1,0);" \
        "Only TrinityCore EXTENDED bindings map to target extended=true"
    check_zero petition_id_mismatch "
        SELECT
          (SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.petition
           WHERE petition_id<>petitionguid) +
          (SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.petition_sign
           WHERE petition_id<>petitionguid);" \
        "New petition IDs are seeded from preserved petition GUIDs"

    validate_mapping_counts auth
    validate_mapping_counts characters
    analyze_schema "$TARGET_AUTH_SCHEMA"
    analyze_schema "$TARGET_CHARACTERS_SCHEMA"

    local failures
    failures=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.validation_result
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND severity='ERROR' AND passed=0;")
    if [[ $failures != 0 ]]; then
        mysql_query -e "
            UPDATE \`$CONTROL_SCHEMA\`.migration_run
            SET status='FAILED' WHERE run_id='$(sql_escape "$RUN_ID")';"
        write_final_report
        die "Validation failed with $failures error(s)"
    fi

    mysql_query -e "
        UPDATE \`$CONTROL_SCHEMA\`.migration_run
        SET status='READY' WHERE run_id='$(sql_escape "$RUN_ID")';"
    write_final_report
    log "Validation passed; migration run $RUN_ID is READY for application smoke tests"
}

show_status() {
    mysql_table -e "
        SELECT run_id,status,started_at,updated_at
        FROM \`$CONTROL_SCHEMA\`.migration_run
        WHERE run_id='$(sql_escape "$RUN_ID")';
        SELECT phase_name,status,started_at,finished_at,detail
        FROM \`$CONTROL_SCHEMA\`.phase_checkpoint
        WHERE run_id='$(sql_escape "$RUN_ID")'
        ORDER BY started_at,phase_name;
        SELECT database_kind,target_table,COUNT(*) AS completed_chunks,
               SUM(source_rows) AS source_rows,SUM(target_rows) AS target_rows
        FROM \`$CONTROL_SCHEMA\`.chunk_checkpoint
        WHERE run_id='$(sql_escape "$RUN_ID")' AND status='COMPLETE'
        GROUP BY database_kind,target_table
        ORDER BY database_kind,target_table;"
}

write_final_report() {
    local run_reports="$REPORTS_DIR/$RUN_ID"
    mkdir -p "$run_reports"
    local report="$run_reports/final-report.md"
    local run_status failures warnings
    run_status=$(mysql_query -e "
        SELECT status FROM \`$CONTROL_SCHEMA\`.migration_run
        WHERE run_id='$(sql_escape "$RUN_ID")';")
    failures=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.validation_result
        WHERE run_id='$(sql_escape "$RUN_ID")' AND severity='ERROR' AND passed=0;")
    warnings=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.validation_result
        WHERE run_id='$(sql_escape "$RUN_ID")' AND severity='WARNING';")

    {
        printf '# TrinityCore to AzerothCore migration report\n\n'
        printf -- '- Run ID: `%s`\n' "$RUN_ID"
        printf -- '- Generated: `%s`\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
        printf -- '- Status: **%s**\n' "$run_status"
        printf -- '- Failed validation checks: **%s**\n' "$failures"
        printf -- '- Warnings: **%s**\n\n' "$warnings"
        printf '## Validation results\n\n'
        printf '| Check | Severity | Observed | Expected | Passed | Detail |\n'
        printf '|---|---:|---:|---:|:---:|---|\n'
        mysql_query -e "
            SELECT CONCAT(
                '| ',REPLACE(check_name,'|','/'),
                ' | ',severity,
                ' | ',REPLACE(observed_value,'|','/'),
                ' | ',REPLACE(expected_value,'|','/'),
                ' | ',IF(passed=1,'yes','NO'),
                ' | ',REPLACE(COALESCE(detail,''),'|','/'),' |')
            FROM \`$CONTROL_SCHEMA\`.validation_result
            WHERE run_id='$(sql_escape "$RUN_ID")'
            ORDER BY severity,check_name;"
        printf '\n## Decision\n\n'
        if [[ $run_status == READY && $failures == 0 ]]; then
            printf 'Database validation passed. Application-level AzerothCore smoke tests are still required before opening the realm.\n'
        else
            printf 'NO-GO. Resolve failed checks and rerun validation.\n'
        fi
    } > "$report"
    log "Wrote $report"
}
