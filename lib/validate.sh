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
                    local removed
                    removed=$(mysql_query -e "
                        SELECT COALESCE(MAX(removed_rows),0)
                        FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
                        WHERE run_id='$(sql_escape "$RUN_ID")'
                          AND database_kind='$kind' AND table_name='$target_table';")
                    check_equal \
                        "count.characters.item_loot_storage" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.item_loot_storage;" \
                        "SELECT
                            (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.item_loot_items) +
                            (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.item_loot_money WHERE money > 0) -
                            $removed;" \
                        "Combined item and money loot rows minus approved target cleanup"
                elif [[ $expression == CHARACTER_SPELL || $expression == CHARACTER_SPELL_REVERSE ]]; then
                    check_equal "count.characters.character_spell" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.character_spell;" \
                        "SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.spell_expected e
                         JOIN \`$TARGET_SCHEMA\`.characters c ON c.guid=e.guid
                         WHERE e.run_id='$(sql_escape "$RUN_ID")' AND e.disposition='PERSISTENT';" \
                        "Reconstructed persistent spell rows for retained characters"
                elif [[ $expression == CHARACTER_TALENTS ]]; then
                    local removed
                    removed=$(mysql_query -e "
                        SELECT COALESCE(MAX(removed_rows),0)
                        FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
                        WHERE run_id='$(sql_escape "$RUN_ID")'
                          AND database_kind='$kind' AND table_name='$target_table';")
                    check_equal \
                        "count.characters.character_talent" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.character_talent;" \
                        "SELECT COUNT(*)-$removed FROM (
                            SELECT guid,spell FROM \`$SOURCE_SCHEMA\`.character_talent
                            GROUP BY guid,spell
                         ) x;" \
                        "Collapsed talent rows minus approved target cleanup"
                elif [[ $expression == ITEM_LOOT_STORAGE_REVERSE ]]; then
                    check_equal \
                        "count.characters.item_loot_reverse" \
                        "SELECT
                           (SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.item_loot_items) +
                           (SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.item_loot_money);" \
                        "SELECT COUNT(*) - (
                           SELECT COALESCE(SUM(removed_rows),0)
                           FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
                           WHERE run_id='$(sql_escape "$RUN_ID")' AND database_kind='characters'
                             AND table_name IN ('item_loot_items','item_loot_money')
                         ) FROM \`$SOURCE_SCHEMA\`.item_loot_storage;" \
                        "Consolidated loot rows minus approved target cleanup"
                elif [[ $expression == CHARACTER_TALENTS_REVERSE ]]; then
                    check_equal \
                        "count.characters.character_talent_reverse" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.character_talent;" \
                        "SELECT COALESCE(SUM((specMask & 1)<>0)+SUM((specMask & 2)<>0),0)
                         FROM \`$SOURCE_SCHEMA\`.character_talent;" \
                        "Every set spec bit must become one TrinityCore talent row"
                elif [[ $expression == CHANNELS_REVERSE ]]; then
                    check_equal "count.characters.channels_reverse" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.channels;" \
                        "SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.channels;" \
                        "Channel bans are serialized without changing channel count"
                elif [[ $expression == RESPAWN_REVERSE ]]; then
                    check_equal "count.characters.respawn_reverse" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.respawn;" \
                        "SELECT
                           (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.creature_respawn) +
                           (SELECT COUNT(*) FROM \`$SOURCE_SCHEMA\`.gameobject_respawn);" \
                        "Split respawns must merge without row loss"
                else
                    local removed
                    removed=$(mysql_query -e "
                        SELECT COALESCE(MAX(removed_rows),0)
                        FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
                        WHERE run_id='$(sql_escape "$RUN_ID")'
                          AND database_kind='$kind' AND table_name='$target_table';")
                    check_equal \
                        "count.$kind.$target_table" \
                        "SELECT COUNT(*) FROM \`$TARGET_SCHEMA\`.\`$target_table\`;" \
                        "SELECT COUNT(*)-$removed FROM \`$SOURCE_SCHEMA\`.\`$source_table\`;" \
                        "$source_table to $target_table rows minus approved target cleanup"
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

validate_updated_representations() {
    check_zero account_username_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_AUTH_SCHEMA\`.account s
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account t ON t.id=s.id
        WHERE t.id IS NULL OR BINARY t.username<>BINARY s.username;" \
        "Account usernames must be preserved byte-for-byte"
    check_zero mail_flags_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.mail s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.mail t ON t.id=s.id
        LEFT JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND (o.guid=s.receiver OR o.guid=s.sender)
        WHERE o.guid IS NULL AND (t.id IS NULL OR t.checked<>s.checked);" \
        "Retained mail flags must be preserved exactly"
    local pet_table
    for pet_table in pet_aura pet_spell pet_spell_cooldown; do
        check_zero "$pet_table.without_pet" "
            SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.\`$pet_table\` s
            LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_pet p ON p.id=s.guid
            WHERE p.id IS NULL;" "Pet relations must reference retained pets"
    done
    if [[ $MIGRATION_DIRECTION == tc-to-ac ]]; then
        check_zero uptime_outcome_mismatch "
            SELECT COUNT(*) FROM \`$SOURCE_AUTH_SCHEMA\`.uptime s
            LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.uptime t
              ON t.realmid=s.realmid AND t.starttime=s.starttime
            WHERE t.realmid IS NULL OR t.uptime<>s.uptime OR t.maxplayers<>s.maxplayers
               OR BINARY t.revision<>BINARY s.revision OR t.EndTime IS NULL
               OR t.EndTime<>s.starttime+s.uptime OR t.ShutdownType<>0
               OR t.ExitCode IS NOT NULL OR t.ShutdownReason<>'';" \
            "Historical sessions have a derived end and unknown outcome, not a crash"
    else
        require_source_archive auth "$SOURCE_AUTH_SCHEMA" uptime APPROVED
        check_zero uptime_common_mismatch "
            SELECT COUNT(*) FROM \`$SOURCE_AUTH_SCHEMA\`.uptime s
            LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.uptime t
              ON t.realmid=s.realmid AND t.starttime=s.starttime
            WHERE t.realmid IS NULL OR t.uptime<>s.uptime OR t.maxplayers<>s.maxplayers
               OR BINARY t.revision<>BINARY s.revision;" \
            "Common session history survives the reverse copy"
    fi
}

perform_validation_reverse() {
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
        "Target auth DDL must match the assembled TrinityCore schema"
    record_validation schema.characters ERROR "$characters_fingerprint" "$expected_characters" \
        "$([[ $characters_fingerprint == "$expected_characters" ]] && printf 1 || printf 0)" \
        "Target characters DDL must match the assembled TrinityCore schema"

    check_zero rejects "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.migration_reject
        WHERE run_id='$(sql_escape "$RUN_ID")';" "No rejected source rows are allowed"
    check_zero account_online "
        SELECT COUNT(*) FROM \`$TARGET_AUTH_SCHEMA\`.account WHERE online<>0;" \
        "All migrated accounts must start offline"
    check_zero character_online "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters WHERE online<>0;" \
        "All migrated characters must start offline"
    check_zero character_name_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.characters s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters t ON t.guid=s.guid
        LEFT JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=s.guid
        WHERE o.guid IS NULL AND
          (t.guid IS NULL OR NOT (BINARY t.name <=> BINARY NULLIF(s.name,'')));" \
        "Active and soft-deleted character names must preserve target semantics"
    check_zero character_without_account "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters c
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account a ON a.id=c.account
        WHERE c.account<>0 AND a.id IS NULL;" "Every character must belong to an account"
    check_zero inventory_without_character "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.guid
        WHERE c.guid IS NULL;" "Every inventory row must belong to a character"
    check_zero inventory_without_item "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance x ON x.guid=i.item
        WHERE x.guid IS NULL;" "Every inventory row must reference an item"
    check_zero item_without_owner "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.owner_guid
        WHERE i.owner_guid<>0 AND c.guid IS NULL;" "Every owned item must reference a character"
    check_zero mail_item_without_mail "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items mi
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.mail m ON m.id=mi.mail_id
        WHERE m.id IS NULL;" "Every mail item must reference mail"
    check_zero mail_item_without_item "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items mi
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=mi.item_guid
        WHERE i.guid IS NULL;" "Every mail item must reference an item"
    check_zero pet_without_owner "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_pet p
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=p.owner
        WHERE c.guid IS NULL;" "Every pet must reference a character"
    check_zero guild_member_without_owner "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild_member gm
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=gm.guid
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.guild g ON g.guildid=gm.guildid
        WHERE c.guid IS NULL OR g.guildid IS NULL;" \
        "Every guild member must reference a character and guild"
    check_zero group_member_without_character "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.group_member gm
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c
          ON c.guid=gm.memberGuid WHERE c.guid IS NULL;" \
        "Every group member must reference a character"
    check_zero character_instance_without_instance "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_instance ci
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.instance i ON i.id=ci.instance
        WHERE i.id IS NULL;" "Every binding must reference an instance"
    check_zero item_loot_without_container "
        SELECT
          (SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_items l
           LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
             ON i.guid=l.container_id WHERE i.guid IS NULL) +
          (SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_money l
           LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
             ON i.guid=l.container_id WHERE i.guid IS NULL);" \
        "Every stored-loot row must reference its container"
    check_zero srp6_binary_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_AUTH_SCHEMA\`.account s
        JOIN \`$TARGET_AUTH_SCHEMA\`.account t ON t.id=s.id
        WHERE BINARY t.salt<>BINARY s.salt
           OR BINARY t.verifier<>BINARY s.verifier
           OR NOT (BINARY t.session_key_auth <=> BINARY s.session_key);" \
        "SRP6 and session bytes must be preserved"
    check_zero account_access_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_AUTH_SCHEMA\`.account_access s
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account_access t
          ON t.AccountID=s.id AND t.RealmID=s.RealmID
        WHERE t.AccountID IS NULL OR t.SecurityLevel<>s.gmlevel
           OR NOT (t.Comment <=> s.comment);" \
        "Account security levels must survive renamed columns"
    check_zero rbac_account_permission_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_AUTH_SCHEMA\`.rbac_account_permissions ap
        JOIN \`$SOURCE_AUTH_SCHEMA\`.rbac_permissions sp
          ON sp.id=ap.permissionId
        JOIN \`$TARGET_AUTH_SCHEMA\`.rbac_permissions tp
          ON BINARY tp.name=BINARY sp.name
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.rbac_account_permissions mapped
          ON mapped.accountId=ap.accountId AND mapped.permissionId=tp.id
         AND mapped.realmId=ap.realmId
        WHERE mapped.accountId IS NULL OR mapped.granted<>ap.granted;" \
        "RBAC overrides must preserve names, grants, and realm scopes"
    check_zero realm_character_count_mismatch "
        SELECT COUNT(*) FROM \`$TARGET_AUTH_SCHEMA\`.realmcharacters rc
        LEFT JOIN (
          SELECT account,COUNT(*) numchars
          FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters GROUP BY account
        ) c ON c.account=rc.acctid
        WHERE rc.realmid=$REALM_ID
          AND rc.numchars<>LEAST(COALESCE(c.numchars,0),255);" \
        "realmcharacters must match retained characters"
    validate_character_spells
    check_zero character_talent_reverse_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_talent s
        LEFT JOIN (
          SELECT guid,spell,BIT_OR(1 << talentGroup) mask
          FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_talent GROUP BY guid,spell
        ) t ON t.guid=s.guid AND t.spell=s.spell
        WHERE t.guid IS NULL OR t.mask<>s.specMask;" \
        "Talent groups must reconstruct every supported spec mask"
    check_zero character_cooldown_reverse_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_spell_cooldown s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_spell_cooldown t
          ON t.guid=s.guid AND t.spell=s.spell
        WHERE t.guid IS NULL OR t.item<>s.item OR t.time<>s.time
           OR t.categoryId<>COALESCE(s.category,0)
           OR t.categoryEnd<>IF(COALESCE(s.category,0)=0,0,s.time);" \
        "Character cooldowns must use the reviewed reverse representation"
    check_zero pet_cooldown_reverse_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.pet_spell_cooldown s
        JOIN \`$SOURCE_CHARACTERS_SCHEMA\`.character_pet p ON p.id=s.guid
        LEFT JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=p.owner
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.pet_spell_cooldown t
          ON t.guid=s.guid AND t.spell=s.spell
        WHERE o.guid IS NULL AND (t.guid IS NULL OR t.time<>s.time
           OR t.categoryId<>COALESCE(s.category,0)
           OR t.categoryEnd<>IF(COALESCE(s.category,0)=0,0,s.time));" \
        "Pet cooldowns must use the reviewed reverse representation"
    local normalized
    normalized=$(normalized_reverse_loot_query)
    check_zero item_loot_reverse_mismatch "
        SELECT COUNT(*) FROM ($normalized) s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance retained ON retained.guid=s.containerGUID
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_items i
          ON i.container_id=s.containerGUID
         AND i.item_id=s.itemid AND i.item_count=s.count
         AND i.item_index=s.normalized_index AND i.rnd_prop=s.randomPropertyId
         AND i.rnd_suffix=s.randomSuffix
         AND i.follow_rules=s.follow_loot_rules AND i.ffa=s.freeforall
         AND i.blocked=s.is_blocked AND i.counted=s.is_counted
         AND i.under_threshold=s.is_underthreshold AND i.needs_quest=s.needs_quest
        WHERE i.container_id IS NULL;" \
        "Normalized slots preserve every retained loot payload, including duplicates"
    check_zero item_loot_money_reverse_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_storage s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance retained ON retained.guid=s.containerGUID
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_money m
          ON m.container_id=s.containerGUID AND m.money=s.count
        WHERE s.itemid=0 AND m.container_id IS NULL;" \
        "Every retained money row must survive the split"
    check_zero channel_ban_reverse_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.channels_bans b
        JOIN \`$SOURCE_CHARACTERS_SCHEMA\`.channels sc ON sc.channelId=b.channelId
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.channels tc
          ON BINARY tc.name=BINARY sc.name AND tc.team=sc.team
        WHERE tc.name IS NULL OR LOCATE(
          CONCAT(_binary' ',CAST(b.playerGUID AS BINARY),_binary' '),
          CAST(CONCAT(' ',COALESCE(tc.bannedList,''),' ') AS BINARY))=0;" \
        "Every AzerothCore channel ban GUID must be serialized"
    check_zero entry_point_reverse_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_entry_point s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_battleground_data t
          ON t.guid=s.guid
        WHERE t.guid IS NULL OR t.instanceId<>0 OR t.team<>0
           OR t.joinX<>s.joinX OR t.joinY<>s.joinY OR t.joinZ<>s.joinZ
           OR t.joinO<>s.joinO OR t.joinMapId<>s.joinMapId
           OR t.taxiStart<>s.taxiPath0 OR t.taxiEnd<>s.taxiPath1
           OR t.mountSpell<>s.mountSpell;" \
        "Entry points must map to the reviewed TrinityCore representation"
    check_zero instance_extension_reverse_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_instance s
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_instance t
          ON t.guid=s.guid AND t.instance=s.instance
        WHERE t.guid IS NULL OR t.extendState<>IF(s.extended=1,2,1);" \
        "Instance extension booleans must become TrinityCore enum values"
    check_zero respawn_reverse_mismatch "
        SELECT COUNT(*) FROM (
          SELECT 0 type,guid spawnId,respawnTime,mapId,instanceId
          FROM \`$SOURCE_CHARACTERS_SCHEMA\`.creature_respawn
          UNION ALL
          SELECT 1,guid,respawnTime,mapId,instanceId
          FROM \`$SOURCE_CHARACTERS_SCHEMA\`.gameobject_respawn
        ) s LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.respawn t
          ON t.type=s.type AND t.spawnId=s.spawnId
         AND t.instanceId=s.instanceId
        WHERE t.spawnId IS NULL OR t.respawnTime<>s.respawnTime
           OR t.mapId<>s.mapId;" "Every split respawn must survive the merge"
    check_zero respawn_type_mismatch "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.respawn
        WHERE type NOT IN (0,1);" "Only creature and gameobject respawn types are supported"
    check_zero archive_manifest_mismatch "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.archive_manifest
        WHERE run_id='$(sql_escape "$RUN_ID")' AND row_count=0;" \
        "Archive manifests must represent nonempty source-only tables"

    validate_updated_representations
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
        mysql_query -e "UPDATE \`$CONTROL_SCHEMA\`.migration_run
            SET status='FAILED' WHERE run_id='$(sql_escape "$RUN_ID")';"
        write_final_report
        die "Validation failed with $failures error(s)"
    fi
    write_final_report
    purge_validated_item_candidates
    mysql_query -e "UPDATE \`$CONTROL_SCHEMA\`.migration_run
        SET status='READY' WHERE run_id='$(sql_escape "$RUN_ID")';"
    write_final_report
    log "Validation passed; migration run $RUN_ID is READY for TrinityCore smoke tests"
}

perform_validation() {
    require_phase load-auth
    require_phase load-characters
    require_phase sanitize-target
    schemas_for_kind characters

    if [[ $MIGRATION_DIRECTION == ac-to-tc ]]; then
        perform_validation_reverse
        return
    fi

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
        LEFT JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=s.guid
        WHERE o.guid IS NULL
          AND (t.guid IS NULL OR NOT (BINARY t.name <=> BINARY COALESCE(s.name,'')));" \
        "Retained names must be preserved and soft-deleted NULL names must become empty strings"
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
    check_zero approved_orphan_character_still_present "
        SELECT COUNT(*)
        FROM \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=o.guid
        WHERE o.run_id='$(sql_escape "$RUN_ID")';" \
        "Every character in the approved cleanup manifest must be absent from the target"
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
        SELECT
          (SELECT COUNT(*)
           FROM \`$TARGET_AUTH_SCHEMA\`.realmcharacters rc
           LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account a ON a.id=rc.acctid
           WHERE rc.realmid=$REALM_ID AND a.id IS NULL) +
          ABS(
            (SELECT COUNT(*) FROM \`$TARGET_AUTH_SCHEMA\`.account) -
            (SELECT COUNT(*) FROM \`$TARGET_AUTH_SCHEMA\`.realmcharacters WHERE realmid=$REALM_ID)
          ) +
          (SELECT COUNT(*)
           FROM \`$TARGET_AUTH_SCHEMA\`.realmcharacters rc
           LEFT JOIN (
               SELECT account,COUNT(*) AS numchars
               FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters
               GROUP BY account
           ) c ON c.account=rc.acctid
           WHERE rc.realmid=$REALM_ID
             AND rc.numchars <> LEAST(COALESCE(c.numchars,0),255));" \
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
    validate_character_spells
    check_zero character_talent_mask_mismatch "
        SELECT COUNT(*)
        FROM (
            SELECT guid,spell,BIT_OR(CAST(1 AS UNSIGNED) << talentGroup) AS expected
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_talent
            GROUP BY guid,spell
        ) s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=s.guid
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_talent t
          ON t.guid=s.guid AND t.spell=s.spell
        WHERE t.guid IS NULL OR t.specMask<>s.expected;" \
        "Talent group rows must combine into the correct target spec mask"
    check_zero character_cooldown_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_spell_cooldown s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=s.guid
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_spell_cooldown t
          ON t.guid=s.guid AND t.spell=s.spell
        WHERE t.guid IS NULL OR t.category<>s.categoryId
           OR t.time<>GREATEST(s.time,s.categoryEnd) OR t.needSend<>1;" \
        "Character cooldown category and latest expiration must be preserved"
    check_zero pet_cooldown_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.pet_spell_cooldown s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_pet p ON p.id=s.guid
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.pet_spell_cooldown t
          ON t.guid=s.guid AND t.spell=s.spell
        WHERE t.guid IS NULL OR t.category<>s.categoryId
           OR t.time<>GREATEST(s.time,s.categoryEnd);" \
        "Pet cooldown category and latest expiration must be preserved"
    check_zero item_loot_item_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_items s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=s.container_id
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_storage t
          ON t.containerGUID=s.container_id AND t.itemid=s.item_id
         AND t.count=s.item_count AND t.item_index=s.item_index
        WHERE t.containerGUID IS NULL;" \
        "Every stored item-loot row must be represented in the merged table"
    check_zero item_loot_money_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_money s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=s.container_id
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_storage t
          ON t.containerGUID=s.container_id AND t.itemid=0 AND t.count=s.money
        WHERE s.money>0 AND t.containerGUID IS NULL;" \
        "Every positive stored-money row must be represented as itemid zero"
    check_zero entry_point_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_battleground_data s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=s.guid
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_entry_point t ON t.guid=s.guid
        WHERE t.guid IS NULL OR t.joinX<>s.joinX OR t.joinY<>s.joinY
           OR t.joinZ<>s.joinZ OR t.joinO<>s.joinO OR t.joinMapId<>s.joinMapId
           OR t.taxiPath0<>s.taxiStart OR t.taxiPath1<>s.taxiEnd
           OR t.mountSpell<>s.mountSpell;" \
        "Battleground return state must become character entry-point state"
    check_zero instance_extension_mismatch "
        SELECT COUNT(*)
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_instance s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=s.guid
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

    validate_updated_representations
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

    # Materialize the candidate manifest into the report before releasing its
    # large control-schema rows. The operation checkpoint retains its immutable
    # count/min/max/checksum signature after the rows are purged.
    write_final_report
    purge_validated_item_candidates
    mysql_query -e "
        UPDATE \`$CONTROL_SCHEMA\`.migration_run
        SET status='READY' WHERE run_id='$(sql_escape "$RUN_ID")';"
    write_final_report
    log "Validation passed; migration run $RUN_ID is READY for application smoke tests"
}

show_status() {
    mysql_table -e "
        SELECT run_id,migration_direction,compatibility_profile,
               LEFT(trinitycore_revision,12) AS trinitycore_revision,
               LEFT(azerothcore_revision,12) AS azerothcore_revision,
               status,started_at,updated_at
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
        ORDER BY database_kind,target_table;
        SELECT database_kind,table_name,before_rows,after_rows,removed_rows
        FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
        WHERE run_id='$(sql_escape "$RUN_ID")' AND removed_rows>0
        ORDER BY database_kind,table_name;
        SELECT phase_name,operation_name,database_kind,table_name,
               chunk_start,chunk_end,status,
               TIMESTAMPDIFF(SECOND,started_at,COALESCE(finished_at,UTC_TIMESTAMP()))
                   AS elapsed_seconds,
               affected_rows,
               ROUND(affected_rows /
                   GREATEST(TIMESTAMPDIFF(SECOND,started_at,
                           COALESCE(finished_at,UTC_TIMESTAMP())),1),1)
                   AS rows_per_second
        FROM \`$CONTROL_SCHEMA\`.operation_checkpoint
        WHERE run_id='$(sql_escape "$RUN_ID")'
        ORDER BY (status='RUNNING') DESC,started_at DESC
        LIMIT 15;
        SELECT database_kind,table_name,index_name,status,started_at,finished_at,detail
        FROM \`$CONTROL_SCHEMA\`.deferred_index
        WHERE run_id='$(sql_escape "$RUN_ID")'
        ORDER BY database_kind,table_name,index_name;"
    if table_exists "$TARGET_CHARACTERS_SCHEMA" item_instance; then
        mysql_table -e "
            SELECT
              planned.planned_rows AS candidate_rows,
              planned.planned_rows-pending.remaining_rows AS completed_rows,
              pending.remaining_rows,
              staged.staged_rows
            FROM
              (SELECT COALESCE(MAX(affected_rows),0) AS planned_rows
               FROM \`$CONTROL_SCHEMA\`.operation_checkpoint
               WHERE run_id='$(sql_escape "$RUN_ID")'
                 AND phase_name='sanitize-target'
                 AND operation_name='materialize-item-candidates'
                 AND status='COMPLETE') planned
            CROSS JOIN
              (SELECT COUNT(*) AS remaining_rows
               FROM \`$CONTROL_SCHEMA\`.cleanup_item_candidate c
               JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=c.guid
               WHERE c.run_uuid=UUID_TO_BIN('$(sql_escape "$RUN_ID")')) pending
            CROSS JOIN
              (SELECT COUNT(*) AS staged_rows
               FROM \`$CONTROL_SCHEMA\`.cleanup_item_candidate
               WHERE run_uuid=UUID_TO_BIN('$(sql_escape "$RUN_ID")')) staged;"
    fi
}

purge_validated_item_candidates() {
    local detail count hash
    detail=$(mysql_query -e "
        SELECT COALESCE(MAX(detail),'')
        FROM \`$CONTROL_SCHEMA\`.operation_checkpoint
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND phase_name='sanitize-target'
          AND operation_name='materialize-item-candidates'
          AND status='COMPLETE';")
    [[ -n $detail ]] || return
    count=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.cleanup_item_candidate
        WHERE run_uuid=UUID_TO_BIN('$(sql_escape "$RUN_ID")');")
    [[ $count != 0 ]] || return
    hash=$(printf '%s' 'validated item candidate purge v1' | sha256sum | awk '{print $1}')
    mark_operation_running validate purge-item-candidates control \
        cleanup_item_candidate 0 0 "$hash" "$count"
    mysql_query -e "
        START TRANSACTION;
        DELETE FROM \`$CONTROL_SCHEMA\`.cleanup_item_candidate
        WHERE run_uuid=UUID_TO_BIN('$(sql_escape "$RUN_ID")');
        SET @affected_rows=ROW_COUNT();
        INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
            (run_id,phase_name,operation_name,database_kind,table_name,
             chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
             status,started_at,finished_at,detail)
        VALUES
            ('$(sql_escape "$RUN_ID")','validate','purge-item-candidates',
             'control','cleanup_item_candidate',0,0,'$hash',$count,
             @affected_rows,'COMPLETE',UTC_TIMESTAMP(),UTC_TIMESTAMP(),
             'candidate signature retained by materialize-item-candidates') AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash,planned_rows=new.planned_rows,
            affected_rows=new.affected_rows,status='COMPLETE',
            finished_at=new.finished_at,detail=new.detail;
        COMMIT;"
    log "Purged $count validated item candidate staging row(s)"
}

write_final_report() {
    local run_reports="$REPORTS_DIR/$RUN_ID"
    mkdir -p "$run_reports"
    write_spell_reports
    local report="$run_reports/final-report.md"
    local run_status failures warnings run_identity
    run_status=$(mysql_query -e "
        SELECT status FROM \`$CONTROL_SCHEMA\`.migration_run
        WHERE run_id='$(sql_escape "$RUN_ID")';")
    failures=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.validation_result
        WHERE run_id='$(sql_escape "$RUN_ID")' AND severity='ERROR' AND passed=0;")
    warnings=$(mysql_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.validation_result
        WHERE run_id='$(sql_escape "$RUN_ID")' AND severity='WARNING';")
    run_identity=$(mysql_query -e "
        SELECT CONCAT_WS('|',compatibility_profile,trinitycore_revision,
                         azerothcore_revision,trinitycore_sql_digest,
                         trinitycore_semantic_digest,azerothcore_sql_digest,
                         azerothcore_semantic_digest)
        FROM \`$CONTROL_SCHEMA\`.migration_run
        WHERE run_id='$(sql_escape "$RUN_ID")';")
    local report_profile report_tc_revision report_ac_revision report_tc_sql
    local report_tc_semantic report_ac_sql report_ac_semantic
    IFS='|' read -r report_profile report_tc_revision report_ac_revision report_tc_sql \
        report_tc_semantic report_ac_sql report_ac_semantic <<< "$run_identity"

    {
        printf '# TrinityCore/AzerothCore database migration report\n\n'
        printf -- '- Run ID: `%s`\n' "$RUN_ID"
        printf -- '- Direction: `%s`\n' "$MIGRATION_DIRECTION"
        printf -- '- Compatibility profile: `%s`\n' "$report_profile"
        printf -- '- TrinityCore revision: `%s`\n' "$report_tc_revision"
        printf -- '- AzerothCore revision: `%s`\n' "$report_ac_revision"
        printf -- '- TrinityCore SQL/semantic digests: `%s` / `%s`\n' \
            "$report_tc_sql" "$report_tc_semantic"
        printf -- '- AzerothCore SQL/semantic digests: `%s` / `%s`\n' \
            "$report_ac_sql" "$report_ac_semantic"
        printf -- '- Generated: `%s`\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
        printf -- '- Status: **%s**\n' "$run_status"
        printf -- '- Failed validation checks: **%s**\n' "$failures"
        printf -- '- Warnings: **%s**\n\n' "$warnings"
        printf '## Spell reconstruction\n\n'
        printf 'Rows and specialization decisions: `spell-reconstruction.tsv`. Input evidence: `spell-fingerprints.tsv`.\n\n'
        printf '| Representation | Rows | Derived rows |\n|---|---:|---:|\n'
        mysql_query -e "SELECT CONCAT('| ',disposition,' | ',COUNT(*),' | ',SUM(derived),' |')
            FROM \`$CONTROL_SCHEMA\`.spell_provenance WHERE run_id='$(sql_escape "$RUN_ID")'
            GROUP BY disposition ORDER BY disposition;"
        printf '\nStored persistent rows with specialization-limited masks: '
        mysql_query -e "SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.spell_provenance
            WHERE run_id='$(sql_escape "$RUN_ID")' AND derived=0
              AND disposition='PERSISTENT' AND spec_mask<>3;"
        printf '\n'
        printf 'Reviewed native passive-rank contracts: `spell-native-passive-ranks.tsv` (exact owners, TC predecessor state and target representation).\n\n'
        printf 'Consumed dual-spec teaching wrappers: `spell-consumed-teachers.tsv` (original flags, exact derived buttons and preserved spec ownership; no teaching effects executed).\n\n'
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
        printf '\n## Approved target cleanup\n\n'
        printf '| Database | Table | Before | After | Removed |\n'
        printf '|---|---|---:|---:|---:|\n'
        mysql_query -e "
            SELECT CONCAT(
                '| ',database_kind,
                ' | ',table_name,
                ' | ',before_rows,
                ' | ',after_rows,
                ' | ',removed_rows,' |')
            FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
            WHERE run_id='$(sql_escape "$RUN_ID")' AND removed_rows>0
            ORDER BY database_kind,table_name;"
        printf '\n## Unsupported source data archives\n\n'
        printf '| Database | Table | Rows | SHA-256 | Path |\n'
        printf '|---|---|---:|---|---|\n'
        mysql_query -e "
            SELECT CONCAT('| ',database_kind,' | ',source_table,' | ',row_count,
                          ' | ',dump_sha256,' | ',REPLACE(dump_path,'|','/'),' |')
            FROM \`$CONTROL_SCHEMA\`.archive_manifest
            WHERE run_id='$(sql_escape "$RUN_ID")'
            ORDER BY database_kind,source_table;"
        printf '\n## Item cleanup candidate manifest\n\n'
        printf '| Signature | Staged rows remaining |\n'
        printf '|---|---:|\n'
        mysql_query -e "
            SELECT CONCAT(
                '| ',COALESCE(detail,'not materialized'),
                ' | ',
                (SELECT COUNT(*)
                 FROM \`$CONTROL_SCHEMA\`.cleanup_item_candidate
                 WHERE run_uuid=UUID_TO_BIN('$(sql_escape "$RUN_ID")')),
                ' |')
            FROM \`$CONTROL_SCHEMA\`.operation_checkpoint
            WHERE run_id='$(sql_escape "$RUN_ID")'
              AND phase_name='sanitize-target'
              AND operation_name='materialize-item-candidates'
              AND status='COMPLETE'
            LIMIT 1;"
        printf '\n## Slowest database operations\n\n'
        printf '| Phase | Operation | Table | Rows | Seconds | Rows/sec | Status |\n'
        printf '|---|---|---|---:|---:|---:|---|\n'
        mysql_query -e "
            SELECT CONCAT(
                '| ',phase_name,' | ',operation_name,' | ',table_name,
                ' | ',affected_rows,
                ' | ',TIMESTAMPDIFF(SECOND,started_at,
                       COALESCE(finished_at,UTC_TIMESTAMP())),
                ' | ',ROUND(affected_rows /
                         GREATEST(TIMESTAMPDIFF(SECOND,started_at,
                           COALESCE(finished_at,UTC_TIMESTAMP())),1),1),
                ' | ',status,' |')
            FROM \`$CONTROL_SCHEMA\`.operation_checkpoint
            WHERE run_id='$(sql_escape "$RUN_ID")'
            ORDER BY TIMESTAMPDIFF(MICROSECOND,started_at,
                     COALESCE(finished_at,UTC_TIMESTAMP())) DESC
            LIMIT 20;"
        printf '\n## Deferred secondary indexes\n\n'
        printf '| Database | Table | Index | Status | Detail |\n'
        printf '|---|---|---|---|---|\n'
        mysql_query -e "
            SELECT CONCAT(
                '| ',database_kind,' | ',table_name,' | ',index_name,
                ' | ',status,' | ',REPLACE(COALESCE(detail,''),'|','/'),' |')
            FROM \`$CONTROL_SCHEMA\`.deferred_index
            WHERE run_id='$(sql_escape "$RUN_ID")'
            ORDER BY database_kind,table_name,index_name;"
        printf '\n## Decision\n\n'
        if [[ $run_status == READY && $failures == 0 ]]; then
            if [[ $MIGRATION_DIRECTION == tc-to-ac ]]; then
                printf 'Database validation passed. Application-level AzerothCore smoke tests are still required before opening the realm.\n'
            else
                printf 'Database validation passed. Application-level TrinityCore smoke tests are still required before opening the realm.\n'
            fi
        else
            printf 'NO-GO. Resolve failed checks and rerun validation.\n'
        fi
    } > "$report"
    log "Wrote $report"
}
