#!/usr/bin/env bash

# This phase only mutates the freshly assembled AzerothCore targets. TrinityCore
# remains the immutable archive and rollback source.

sanitize_query() {
    mysql_query --database="$TARGET_CHARACTERS_SCHEMA" "$@"
}

snapshot_cleanup_tables() {
    local kind=$1 schema=$2 table rows
    while IFS= read -r table; do
        rows=$(sanitize_query -e "SELECT COUNT(*) FROM \`$schema\`.\`$table\`;")
        sanitize_query -e "
            INSERT IGNORE INTO \`$CONTROL_SCHEMA\`.cleanup_table_summary
                (run_id,database_kind,table_name,before_rows)
            VALUES
                ('$(sql_escape "$RUN_ID")','$(sql_escape "$kind")',
                 '$(sql_escape "$table")',$rows);"
    done < <(sanitize_query -e "
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA='$(sql_escape "$schema")'
          AND TABLE_TYPE='BASE TABLE'
        ORDER BY TABLE_NAME;")
}

finish_cleanup_table_summary() {
    local kind=$1 schema=$2 table rows before
    while IFS= read -r table; do
        rows=$(sanitize_query -e "SELECT COUNT(*) FROM \`$schema\`.\`$table\`;")
        before=$(sanitize_query -e "
            SELECT before_rows
            FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
            WHERE run_id='$(sql_escape "$RUN_ID")'
              AND database_kind='$(sql_escape "$kind")'
              AND table_name='$(sql_escape "$table")';")
        [[ -n $before ]] ||
            die "Missing cleanup baseline for $schema.$table"
        if (( rows > before )); then
            [[ $kind == auth && $table == realmcharacters ]] ||
                die "Sanitization unexpectedly increased $schema.$table from $before to $rows rows"
            sanitize_query -e "
                UPDATE \`$CONTROL_SCHEMA\`.cleanup_table_summary
                SET after_rows=$rows,removed_rows=0,detail='DERIVED_REALM_CHARACTER_COUNTS'
                WHERE run_id='$(sql_escape "$RUN_ID")'
                  AND database_kind='$(sql_escape "$kind")'
                  AND table_name='$(sql_escape "$table")';"
            continue
        fi
        sanitize_query -e "
            UPDATE \`$CONTROL_SCHEMA\`.cleanup_table_summary
            SET after_rows=$rows,removed_rows=before_rows-$rows
            WHERE run_id='$(sql_escape "$RUN_ID")'
              AND database_kind='$(sql_escape "$kind")'
              AND table_name='$(sql_escape "$table")';"
    done < <(sanitize_query -e "
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA='$(sql_escape "$schema")'
          AND TABLE_TYPE='BASE TABLE'
        ORDER BY TABLE_NAME;")
}

capture_orphan_characters() {
    sanitize_query -e "
        INSERT IGNORE INTO \`$CONTROL_SCHEMA\`.cleanup_orphan_character
            (run_id,guid,account_id,character_name)
        SELECT '$(sql_escape "$RUN_ID")',c.guid,c.account,c.name
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters c
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account a ON a.id=c.account
        WHERE c.account<>0 AND a.id IS NULL;"

    local run_reports="$REPORTS_DIR/$RUN_ID"
    mkdir -p "$run_reports"
    {
        printf 'guid\taccount_id\tcharacter_name\n'
        sanitize_query -e "
            SELECT guid,account_id,character_name
            FROM \`$CONTROL_SCHEMA\`.cleanup_orphan_character
            WHERE run_id='$(sql_escape "$RUN_ID")'
            ORDER BY guid;"
    } > "$run_reports/cleanup-orphan-characters.tsv"
}

assert_no_organization_leaders() {
    local guild_leaders arena_captains
    guild_leaders=$(sanitize_query -e "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild g
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=g.leaderguid;")
    arena_captains=$(sanitize_query -e "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.arena_team a
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=a.captainGuid;")
    [[ $guild_leaders == 0 ]] ||
        die "$guild_leaders orphan character(s) lead a guild; choose a successor or explicitly disband before sanitization"
    [[ $arena_captains == 0 ]] ||
        die "$arena_captains orphan character(s) captain an arena team; choose a successor or explicitly disband before sanitization"
}

delete_direct_character_rows() {
    local table column
    local direct_tables=(
        character_account_data:guid
        character_achievement:guid
        character_achievement_offline_updates:guid
        character_achievement_progress:guid
        character_action:guid
        character_arena_stats:guid
        character_aura:guid
        character_banned:guid
        character_battleground_random:guid
        character_brew_of_the_month:guid
        character_declinedname:guid
        character_entry_point:guid
        character_equipmentsets:guid
        character_gifts:guid
        character_glyphs:guid
        character_homebind:guid
        character_instance:guid
        character_inventory:guid
        character_queststatus:guid
        character_queststatus_daily:guid
        character_queststatus_monthly:guid
        character_queststatus_rewarded:guid
        character_queststatus_seasonal:guid
        character_queststatus_weekly:guid
        character_reputation:guid
        character_settings:guid
        character_skills:guid
        character_spell:guid
        character_spell_cooldown:guid
        character_stats:guid
        character_talent:guid
        corpse:guid
        gm_survey:guid
        gm_ticket:playerGuid
        lag_reports:guid
        lfg_data:guid
        pvpstats_players:character_guid
        quest_tracker:character_guid
        battleground_deserters:guid
        channels_bans:playerGUID
        guild_member:guid
        guild_member_withdraw:guid
        arena_team_member:guid
    )
    for table_column in "${direct_tables[@]}"; do
        table=${table_column%%:*}
        column=${table_column#*:}
        table_exists "$TARGET_CHARACTERS_SCHEMA" "$table" || continue
        sanitize_query -e "
            DELETE t
            FROM \`$TARGET_CHARACTERS_SCHEMA\`.\`$table\` t
            JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
              ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=t.\`$column\`;"
    done

    sanitize_query -e "
        DELETE s FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_social s
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=s.guid OR o.guid=s.friend);

        DELETE ps FROM \`$TARGET_CHARACTERS_SCHEMA\`.petition_sign ps
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=ps.ownerguid OR o.guid=ps.playerguid);

        DELETE p FROM \`$TARGET_CHARACTERS_SCHEMA\`.petition p
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=p.ownerguid;

        DELETE ps FROM \`$TARGET_CHARACTERS_SCHEMA\`.petition_sign ps
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.petition p
          ON p.petitionguid=ps.petitionguid
        WHERE p.petitionguid IS NULL;"

    sanitize_query -e "
        DELETE ci FROM \`$TARGET_CHARACTERS_SCHEMA\`.calendar_invites ci
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=ci.invitee OR o.guid=ci.sender);

        DELETE ci FROM \`$TARGET_CHARACTERS_SCHEMA\`.calendar_invites ci
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.calendar_events ce ON ce.id=ci.event
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=ce.creator;

        DELETE ce FROM \`$TARGET_CHARACTERS_SCHEMA\`.calendar_events ce
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=ce.creator;"

    sanitize_query -e "
        DELETE mi FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items mi
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.mail m ON m.id=mi.mail_id
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=m.sender OR o.guid=m.receiver);

        DELETE m FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail m
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=m.sender OR o.guid=m.receiver);

        DELETE a FROM \`$TARGET_CHARACTERS_SCHEMA\`.auctionhouse a
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=a.itemowner OR o.guid=a.buyguid);"

    # Groups are runtime/social state. Remove a group led by an orphan, then
    # remove ordinary orphan memberships and any now-empty group shells.
    sanitize_query -e "
        DELETE gm FROM \`$TARGET_CHARACTERS_SCHEMA\`.group_member gm
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.groups g ON g.guid=gm.guid
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=g.leaderGuid;
        DELETE g FROM \`$TARGET_CHARACTERS_SCHEMA\`.groups g
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=g.leaderGuid;
        DELETE gm FROM \`$TARGET_CHARACTERS_SCHEMA\`.group_member gm
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=gm.memberGuid;
        UPDATE \`$TARGET_CHARACTERS_SCHEMA\`.groups g
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=g.looterGuid OR o.guid=g.masterLooterGuid)
        SET g.looterGuid=IF(g.looterGuid=o.guid,0,g.looterGuid),
            g.masterLooterGuid=IF(g.masterLooterGuid=o.guid,0,g.masterLooterGuid);
        DELETE g FROM \`$TARGET_CHARACTERS_SCHEMA\`.groups g
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.group_member gm ON gm.guid=g.guid
        WHERE gm.guid IS NULL;"

    # Historical guild logs may reference deleted players but are not required
    # for guild ownership or balances.
    sanitize_query -e "
        DELETE e FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild_eventlog e
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=e.PlayerGuid1 OR o.guid=e.PlayerGuid2);
        DELETE e FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild_bank_eventlog e
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=e.PlayerGuid;"
}

delete_orphan_pets() {
    sanitize_query -e "
        CREATE TEMPORARY TABLE cleanup_pets (id int unsigned PRIMARY KEY) ENGINE=InnoDB
        SELECT p.id
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_pet p
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=p.owner;
        DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.pet_aura x JOIN cleanup_pets p ON p.id=x.guid;
        DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.pet_spell x JOIN cleanup_pets p ON p.id=x.guid;
        DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.pet_spell_cooldown x JOIN cleanup_pets p ON p.id=x.guid;
        DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_pet_declinedname x JOIN cleanup_pets p ON p.id=x.id;
        DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_pet x JOIN cleanup_pets p ON p.id=x.id;"
}

delete_dangling_relations() {
    sanitize_query -e "
        DELETE i FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.guid
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance x ON x.guid=i.item
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance b ON b.guid=i.bag
        WHERE c.guid IS NULL OR x.guid IS NULL OR (i.bag<>0 AND b.guid IS NULL);

        DELETE mi FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items mi
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.mail m ON m.id=mi.mail_id
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=mi.item_guid
        WHERE m.id IS NULL OR i.guid IS NULL;

        DELETE l FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_storage l
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=l.containerGUID
        WHERE i.guid IS NULL;"
}

delete_unreachable_items() {
    local lower=0 upper maximum reachable
    maximum=$(sanitize_query -e "
        SELECT COALESCE(MAX(i.guid),0)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.owner_guid
        WHERE i.owner_guid<>0 AND c.guid IS NULL;")
    while (( lower < maximum )); do
        upper=$((lower + CHUNK_SIZE))
        reachable=$(sanitize_query -e "
            SELECT COUNT(*)
            FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
            LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.owner_guid
            WHERE i.guid>$lower AND i.guid<=$upper
              AND i.owner_guid<>0 AND c.guid IS NULL
              AND (
                EXISTS (SELECT 1 FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory x WHERE x.item=i.guid OR x.bag=i.guid)
                OR EXISTS (SELECT 1 FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items x JOIN \`$TARGET_CHARACTERS_SCHEMA\`.mail m ON m.id=x.mail_id WHERE x.item_guid=i.guid)
                OR EXISTS (SELECT 1 FROM \`$TARGET_CHARACTERS_SCHEMA\`.auctionhouse x WHERE x.itemguid=i.guid)
                OR EXISTS (SELECT 1 FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild_bank_item x WHERE x.item_guid=i.guid)
              );")
        [[ $reachable == 0 ]] ||
            die "$reachable item(s) with missing owners in GUID range ($lower,$upper] remain reachable; refusing destructive cleanup"

        sanitize_query -e "
            START TRANSACTION;
            CREATE TEMPORARY TABLE cleanup_items (guid int unsigned PRIMARY KEY) ENGINE=InnoDB
            SELECT i.guid
            FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
            LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.owner_guid
            WHERE i.guid>$lower AND i.guid<=$upper
              AND i.owner_guid<>0 AND c.guid IS NULL;
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_storage x JOIN cleanup_items i ON i.guid=x.containerGUID;
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_refund_instance x JOIN cleanup_items i ON i.guid=x.item_guid;
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_soulbound_trade_data x JOIN cleanup_items i ON i.guid=x.itemGuid;
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_gifts x JOIN cleanup_items i ON i.guid=x.item_guid;
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance x JOIN cleanup_items i ON i.guid=x.guid;
            COMMIT;"
        lower=$upper
    done
}

delete_missing_account_state() {
    sanitize_query -e "
        DELETE d FROM \`$TARGET_CHARACTERS_SCHEMA\`.account_data d
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account a ON a.id=d.accountId
        WHERE a.id IS NULL;
        DELETE d FROM \`$TARGET_CHARACTERS_SCHEMA\`.account_tutorial d
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account a ON a.id=d.accountId
        WHERE a.id IS NULL;
        DELETE d FROM \`$TARGET_CHARACTERS_SCHEMA\`.account_instance_times d
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account a ON a.id=d.accountId
        WHERE a.id IS NULL;"
}

rebuild_realmcharacters() {
    sanitize_query -e "
        DELETE FROM \`$TARGET_AUTH_SCHEMA\`.realmcharacters
        WHERE realmid=$REALM_ID;
        INSERT INTO \`$TARGET_AUTH_SCHEMA\`.realmcharacters (realmid,acctid,numchars)
        SELECT $REALM_ID,a.id,LEAST(COUNT(c.guid),255)
        FROM \`$TARGET_AUTH_SCHEMA\`.account a
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.account=a.id
        GROUP BY a.id;"
}

write_cleanup_report() {
    local run_reports="$REPORTS_DIR/$RUN_ID"
    {
        printf 'database_kind\ttable_name\tbefore_rows\tafter_rows\tremoved_rows\tdetail\n'
        sanitize_query -e "
            SELECT database_kind,table_name,before_rows,after_rows,removed_rows,detail
            FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
            WHERE run_id='$(sql_escape "$RUN_ID")' AND removed_rows>0
            ORDER BY database_kind,table_name;"
    } > "$run_reports/cleanup-table-summary.tsv"
}

perform_sanitize_target() {
    require_phase load-auth
    require_phase load-characters
    assert_schema_unchanged auth "$SOURCE_AUTH_SCHEMA"
    assert_schema_unchanged characters "$SOURCE_CHARACTERS_SCHEMA"
    assert_source_counts_unchanged auth "$SOURCE_AUTH_SCHEMA"
    assert_source_counts_unchanged characters "$SOURCE_CHARACTERS_SCHEMA"

    snapshot_cleanup_tables auth "$TARGET_AUTH_SCHEMA"
    snapshot_cleanup_tables characters "$TARGET_CHARACTERS_SCHEMA"
    capture_orphan_characters
    assert_no_organization_leaders

    local orphan_count
    orphan_count=$(sanitize_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.cleanup_orphan_character
        WHERE run_id='$(sql_escape "$RUN_ID")';")
    log "Sanitizing $orphan_count target character(s) whose auth accounts are absent"

    delete_orphan_pets
    delete_direct_character_rows
    sanitize_query -e "
        DELETE c FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters c
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=c.guid;"
    delete_missing_account_state
    delete_dangling_relations
    delete_unreachable_items
    delete_dangling_relations
    rebuild_realmcharacters

    finish_cleanup_table_summary auth "$TARGET_AUTH_SCHEMA"
    finish_cleanup_table_summary characters "$TARGET_CHARACTERS_SCHEMA"
    write_cleanup_report
    log "Completed approved target sanitization; TrinityCore source schemas were not modified"
}
