#!/usr/bin/env bash

# This phase mutates only freshly assembled target schemas. Source schemas
# remain the immutable rollback source in both directions.

sanitize_query() {
    mysql_query --database="$TARGET_CHARACTERS_SCHEMA" "$@"
}

operation_is_complete() {
    local operation=$1 kind=$2 table=$3 lower=$4 upper=$5 hash=$6
    [[ $(sanitize_query -e "
        SELECT COUNT(*)
        FROM \`$CONTROL_SCHEMA\`.operation_checkpoint
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND phase_name='sanitize-target'
          AND operation_name='$(sql_escape "$operation")'
          AND database_kind='$(sql_escape "$kind")'
          AND table_name='$(sql_escape "$table")'
          AND chunk_start=$lower AND chunk_end=$upper
          AND script_hash='$hash' AND status='COMPLETE';") == 1 ]]
}

summary_accumulator_sql() {
    local table=$1 variable=$2
    cat <<SQL
INSERT INTO \`$CONTROL_SCHEMA\`.cleanup_table_summary
    (run_id,database_kind,table_name,before_rows,removed_rows)
VALUES
    ('$(sql_escape "$RUN_ID")','characters','$(sql_escape "$table")',0,$variable) AS new
ON DUPLICATE KEY UPDATE
    removed_rows=COALESCE(cleanup_table_summary.removed_rows,0)+new.removed_rows;
SQL
}

run_cleanup_delete() {
    local operation=$1 table=$2 delete_sql=$3
    local hash affected summary_sql
    hash=$(printf '%s' "$delete_sql" | sha256sum | awk '{print $1}')
    if operation_is_complete "$operation" characters "$table" 0 0 "$hash"; then
        return
    fi
    mark_operation_running sanitize-target "$operation" characters "$table" 0 0 "$hash" 0
    summary_sql=$(summary_accumulator_sql "$table" '@affected_rows')
    if ! affected=$(sanitize_query -e "
        START TRANSACTION;
        $delete_sql
        SET @affected_rows=ROW_COUNT();
        $summary_sql
        INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
            (run_id,phase_name,operation_name,database_kind,table_name,
             chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
             status,started_at,finished_at)
        VALUES
            ('$(sql_escape "$RUN_ID")','sanitize-target',
             '$(sql_escape "$operation")','characters','$(sql_escape "$table")',
             0,0,'$hash',@affected_rows,@affected_rows,
             'COMPLETE',UTC_TIMESTAMP(),UTC_TIMESTAMP()) AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash,planned_rows=new.planned_rows,
            affected_rows=new.affected_rows,status='COMPLETE',
            finished_at=new.finished_at,detail=NULL;
        COMMIT;
        SELECT @affected_rows;"); then
        die "Cleanup operation failed: $operation"
    fi
    log "sanitize-target: $operation completed ($affected row(s))"
}

run_cleanup_update() {
    local operation=$1 table=$2 statement=$3
    local hash affected
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    if operation_is_complete "$operation" characters "$table" 0 0 "$hash"; then
        return
    fi
    mark_operation_running sanitize-target "$operation" characters "$table" 0 0 "$hash" 0
    if ! affected=$(sanitize_query -e "
        START TRANSACTION;
        $statement
        SET @affected_rows=ROW_COUNT();
        INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
            (run_id,phase_name,operation_name,database_kind,table_name,
             chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
             status,started_at,finished_at)
        VALUES
            ('$(sql_escape "$RUN_ID")','sanitize-target',
             '$(sql_escape "$operation")','characters','$(sql_escape "$table")',
             0,0,'$hash',@affected_rows,@affected_rows,
             'COMPLETE',UTC_TIMESTAMP(),UTC_TIMESTAMP()) AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash,planned_rows=new.planned_rows,
            affected_rows=new.affected_rows,status='COMPLETE',
            finished_at=new.finished_at,detail=NULL;
        COMMIT;
        SELECT @affected_rows;"); then
        die "Cleanup update failed: $operation"
    fi
    log "sanitize-target: $operation completed ($affected row(s))"
}

capture_orphan_characters() {
    local statement hash affected run_reports
    statement="
        INSERT IGNORE INTO \`$CONTROL_SCHEMA\`.cleanup_orphan_character
            (run_id,guid,account_id,character_name)
        SELECT '$(sql_escape "$RUN_ID")',c.guid,c.account,c.name
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters c
        LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account a ON a.id=c.account
        WHERE c.account<>0 AND a.id IS NULL;"
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    if ! operation_is_complete capture-orphan-characters control cleanup_orphan_character 0 0 "$hash"; then
        mark_operation_running sanitize-target capture-orphan-characters control \
            cleanup_orphan_character 0 0 "$hash" 0
        if ! affected=$(sanitize_query -e "
            START TRANSACTION;
            $statement
            SET @affected_rows=ROW_COUNT();
            INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
                (run_id,phase_name,operation_name,database_kind,table_name,
                 chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
                 status,started_at,finished_at)
            VALUES
                ('$(sql_escape "$RUN_ID")','sanitize-target',
                 'capture-orphan-characters','control','cleanup_orphan_character',
                 0,0,'$hash',@affected_rows,@affected_rows,
                 'COMPLETE',UTC_TIMESTAMP(),UTC_TIMESTAMP()) AS new
            ON DUPLICATE KEY UPDATE
                script_hash=new.script_hash,planned_rows=new.planned_rows,
                affected_rows=new.affected_rows,status='COMPLETE',
                finished_at=new.finished_at,detail=NULL;
            COMMIT;
            SELECT @affected_rows;"); then
            die "Failed to capture orphan characters"
        fi
        log "sanitize-target: captured $affected orphan character(s)"
    fi

    run_reports="$REPORTS_DIR/$RUN_ID"
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
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild g
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=g.leaderguid;")
    arena_captains=$(sanitize_query -e "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.arena_team a
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=a.captainGuid;")
    [[ $guild_leaders == 0 ]] ||
        die "$guild_leaders orphan character(s) lead a guild; choose a successor or explicitly disband before sanitization"
    [[ $arena_captains == 0 ]] ||
        die "$arena_captains orphan character(s) captain an arena team; choose a successor or explicitly disband before sanitization"
}

delete_direct_character_rows() {
    local table column table_column
    local direct_tables=(
        character_account_data:guid character_achievement:guid
        character_achievement_offline_updates:guid character_achievement_progress:guid
        character_action:guid character_arena_stats:guid character_aura:guid
        character_banned:guid character_battleground_data:guid
        character_battleground_random:guid
        character_brew_of_the_month:guid character_declinedname:guid
        character_entry_point:guid character_equipmentsets:guid character_gifts:guid
        character_glyphs:guid character_homebind:guid character_instance:guid
        character_inventory:guid character_queststatus:guid
        character_queststatus_daily:guid character_queststatus_monthly:guid
        character_queststatus_rewarded:guid character_queststatus_seasonal:guid
        character_queststatus_weekly:guid character_reputation:guid
        character_settings:guid character_skills:guid character_spell:guid
        character_spell_cooldown:guid character_stats:guid character_talent:guid
        corpse:guid gm_survey:guid gm_ticket:playerGuid lag_reports:guid lfg_data:guid
        pvpstats_players:character_guid quest_tracker:character_guid
        battleground_deserters:guid channels_bans:playerGUID guild_member:guid
        guild_member_withdraw:guid arena_team_member:guid
    )
    for table_column in "${direct_tables[@]}"; do
        table=${table_column%%:*}
        column=${table_column#*:}
        table_exists "$TARGET_CHARACTERS_SCHEMA" "$table" || continue
        run_cleanup_delete "orphan-character-$table" "$table" "
            DELETE t FROM \`$TARGET_CHARACTERS_SCHEMA\`.\`$table\` t
            JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
              ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=t.\`$column\`;"
    done

    run_cleanup_delete orphan-character-social character_social "
        DELETE s FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_social s
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=s.guid OR o.guid=s.friend);"
    run_cleanup_delete orphan-character-petition-sign petition_sign "
        DELETE ps FROM \`$TARGET_CHARACTERS_SCHEMA\`.petition_sign ps
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=ps.ownerguid OR o.guid=ps.playerguid);"
    run_cleanup_delete orphan-character-petition petition "
        DELETE p FROM \`$TARGET_CHARACTERS_SCHEMA\`.petition p
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=p.ownerguid;"
    run_cleanup_delete dangling-petition-sign petition_sign "
        DELETE ps FROM \`$TARGET_CHARACTERS_SCHEMA\`.petition_sign ps
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.petition p
          ON p.petitionguid=ps.petitionguid
        WHERE p.petitionguid IS NULL;"

    run_cleanup_delete orphan-character-calendar-invites calendar_invites "
        DELETE ci FROM \`$TARGET_CHARACTERS_SCHEMA\`.calendar_invites ci
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=ci.invitee OR o.guid=ci.sender);"
    run_cleanup_delete orphan-event-calendar-invites calendar_invites "
        DELETE ci FROM \`$TARGET_CHARACTERS_SCHEMA\`.calendar_invites ci
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.calendar_events ce ON ce.id=ci.event
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=ce.creator;"
    run_cleanup_delete orphan-character-calendar-events calendar_events "
        DELETE ce FROM \`$TARGET_CHARACTERS_SCHEMA\`.calendar_events ce
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=ce.creator;"

    run_cleanup_delete orphan-character-mail-items mail_items "
        DELETE mi FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items mi
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.mail m ON m.id=mi.mail_id
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=m.sender OR o.guid=m.receiver);"
    run_cleanup_delete orphan-character-mail mail "
        DELETE m FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail m
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=m.sender OR o.guid=m.receiver);"
    run_cleanup_delete orphan-character-auction auctionhouse "
        DELETE a FROM \`$TARGET_CHARACTERS_SCHEMA\`.auctionhouse a
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=a.itemowner OR o.guid=a.buyguid);"

    run_cleanup_delete orphan-leader-group-members group_member "
        DELETE gm FROM \`$TARGET_CHARACTERS_SCHEMA\`.group_member gm
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.groups g ON g.guid=gm.guid
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=g.leaderGuid;"
    run_cleanup_delete orphan-leader-groups groups "
        DELETE g FROM \`$TARGET_CHARACTERS_SCHEMA\`.groups g
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=g.leaderGuid;"
    run_cleanup_delete orphan-group-members group_member "
        DELETE gm FROM \`$TARGET_CHARACTERS_SCHEMA\`.group_member gm
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=gm.memberGuid;"
    run_cleanup_update orphan-group-runtime-references groups "
        UPDATE \`$TARGET_CHARACTERS_SCHEMA\`.groups g
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=g.looterGuid OR o.guid=g.masterLooterGuid)
        SET g.looterGuid=IF(g.looterGuid=o.guid,0,g.looterGuid),
            g.masterLooterGuid=IF(g.masterLooterGuid=o.guid,0,g.masterLooterGuid);"
    run_cleanup_delete empty-groups groups "
        DELETE g FROM \`$TARGET_CHARACTERS_SCHEMA\`.groups g
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.group_member gm ON gm.guid=g.guid
        WHERE gm.guid IS NULL;"

    run_cleanup_delete orphan-guild-eventlog guild_eventlog "
        DELETE e FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild_eventlog e
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")'
         AND (o.guid=e.PlayerGuid1 OR o.guid=e.PlayerGuid2);"
    run_cleanup_delete orphan-guild-bank-eventlog guild_bank_eventlog "
        DELETE e FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild_bank_eventlog e
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=e.PlayerGuid;"
}

delete_orphan_pets() {
    local table column
    for table_column in \
        pet_aura:guid pet_spell:guid pet_spell_cooldown:guid \
        character_pet_declinedname:id; do
        table=${table_column%%:*}
        column=${table_column#*:}
        run_cleanup_delete "orphan-character-$table" "$table" "
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.\`$table\` x
            JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_pet p ON p.id=x.\`$column\`
            JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
              ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=p.owner;"
    done
    run_cleanup_delete orphan-character-pet character_pet "
        DELETE p FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_pet p
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=p.owner;"
}

delete_dangling_relations() {
    run_cleanup_delete dangling-inventory character_inventory "
        DELETE i FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.guid
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance x ON x.guid=i.item
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance b ON b.guid=i.bag
        WHERE c.guid IS NULL OR x.guid IS NULL OR (i.bag<>0 AND b.guid IS NULL);"
    run_cleanup_delete dangling-mail-items mail_items "
        DELETE mi FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items mi
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.mail m ON m.id=mi.mail_id
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=mi.item_guid
        WHERE m.id IS NULL OR i.guid IS NULL;"
    if table_exists "$TARGET_CHARACTERS_SCHEMA" item_loot_storage; then
        run_cleanup_delete dangling-item-loot item_loot_storage "
            DELETE l FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_storage l
            LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
              ON i.guid=l.containerGUID
            WHERE i.guid IS NULL;"
    else
        run_cleanup_delete dangling-item-loot-items item_loot_items "
            DELETE l FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_items l
            LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
              ON i.guid=l.container_id
            WHERE i.guid IS NULL;"
        run_cleanup_delete dangling-item-loot-money item_loot_money "
            DELETE l FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_money l
            LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
              ON i.guid=l.container_id
            WHERE i.guid IS NULL;"
    fi
}

populate_item_root() {
    local operation=$1 mask=$2 select_sql=$3
    local statement hash affected
    select_sql=${select_sql%;}
    statement="
        INSERT INTO \`$CONTROL_SCHEMA\`.cleanup_item_root (run_uuid,guid,root_mask)
        $select_sql
        ON DUPLICATE KEY UPDATE root_mask=(root_mask | $mask);"
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    if operation_is_complete "$operation" control cleanup_item_root 0 0 "$hash"; then
        return
    fi
    mark_operation_running sanitize-target "$operation" control cleanup_item_root 0 0 "$hash" 0
    if ! affected=$(sanitize_query -e "
        START TRANSACTION;
        $statement
        SET @affected_rows=ROW_COUNT();
        INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
            (run_id,phase_name,operation_name,database_kind,table_name,
             chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
             status,started_at,finished_at)
        VALUES
            ('$(sql_escape "$RUN_ID")','sanitize-target',
             '$(sql_escape "$operation")','control','cleanup_item_root',
             0,0,'$hash',@affected_rows,@affected_rows,
             'COMPLETE',UTC_TIMESTAMP(),UTC_TIMESTAMP()) AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash,planned_rows=new.planned_rows,
            affected_rows=new.affected_rows,status='COMPLETE',
            finished_at=new.finished_at,detail=NULL;
        COMMIT;
        SELECT @affected_rows;"); then
        die "Failed to materialize item roots: $operation"
    fi
    log "sanitize-target: $operation materialized ($affected affected row(s))"
}

build_item_roots_and_candidates() {
    local run_binary
    run_binary="UUID_TO_BIN('$(sql_escape "$RUN_ID")')"
    populate_item_root root-inventory-items 1 "
        SELECT $run_binary,i.item,1
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory i;"
    populate_item_root root-inventory-bags 2 "
        SELECT $run_binary,i.bag,2
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_inventory i
        WHERE i.bag<>0;"
    populate_item_root root-valid-mail 4 "
        SELECT $run_binary,mi.item_guid,4
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.mail_items mi
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.mail m ON m.id=mi.mail_id;"
    populate_item_root root-auctions 8 "
        SELECT $run_binary,a.itemguid,8
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.auctionhouse a;"
    populate_item_root root-guild-bank 16 "
        SELECT $run_binary,g.item_guid,16
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.guild_bank_item g;"

    local reachable run_reports
    reachable=$(sanitize_query -e "
        SELECT COUNT(*)
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.owner_guid
        JOIN \`$CONTROL_SCHEMA\`.cleanup_item_root r
          ON r.run_uuid=$run_binary AND r.guid=i.guid
        WHERE i.owner_guid<>0 AND c.guid IS NULL;")
    if [[ $reachable != 0 ]]; then
        run_reports="$REPORTS_DIR/$RUN_ID"
        {
            printf 'guid\towner_guid\troot_mask\n'
            sanitize_query -e "
                SELECT i.guid,i.owner_guid,r.root_mask
                FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
                LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c
                  ON c.guid=i.owner_guid
                JOIN \`$CONTROL_SCHEMA\`.cleanup_item_root r
                  ON r.run_uuid=$run_binary AND r.guid=i.guid
                WHERE i.owner_guid<>0 AND c.guid IS NULL
                ORDER BY i.guid;"
        } > "$run_reports/cleanup-blocked-items.tsv"
        die "$reachable item(s) with missing owners remain reachable; see cleanup-blocked-items.tsv"
    fi

    local statement hash affected
    statement="
        INSERT IGNORE INTO \`$CONTROL_SCHEMA\`.cleanup_item_candidate (run_uuid,guid)
        SELECT $run_binary,i.guid
        FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=i.owner_guid
        LEFT JOIN \`$CONTROL_SCHEMA\`.cleanup_item_root r
          ON r.run_uuid=$run_binary AND r.guid=i.guid
        WHERE i.owner_guid<>0 AND c.guid IS NULL AND r.guid IS NULL;"
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    if ! operation_is_complete materialize-item-candidates control cleanup_item_candidate 0 0 "$hash"; then
        mark_operation_running sanitize-target materialize-item-candidates control \
            cleanup_item_candidate 0 0 "$hash" 0
        if ! affected=$(sanitize_query -e "
            START TRANSACTION;
            $statement
            SET @affected_rows=ROW_COUNT();
            INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
                (run_id,phase_name,operation_name,database_kind,table_name,
                 chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
                 status,started_at,finished_at)
            VALUES
                ('$(sql_escape "$RUN_ID")','sanitize-target',
                 'materialize-item-candidates','control','cleanup_item_candidate',
                 0,0,'$hash',@affected_rows,@affected_rows,
                 'COMPLETE',UTC_TIMESTAMP(),UTC_TIMESTAMP()) AS new
            ON DUPLICATE KEY UPDATE
                script_hash=new.script_hash,planned_rows=new.planned_rows,
                affected_rows=new.affected_rows,status='COMPLETE',
                finished_at=new.finished_at,detail=NULL;
            COMMIT;
            SELECT @affected_rows;"); then
            die "Failed to materialize item cleanup candidates"
        fi
        log "sanitize-target: materialized $affected unreachable item candidate(s)"
    fi

    local stats
    stats=$(sanitize_query -e "
        SELECT CONCAT(COUNT(*),',',COALESCE(MIN(guid),0),',',
                      COALESCE(MAX(guid),0),',',
                      COALESCE(BIT_XOR(CRC32(CAST(guid AS CHAR))),0))
        FROM \`$CONTROL_SCHEMA\`.cleanup_item_candidate
        WHERE run_uuid=$run_binary;")
    sanitize_query -e "
        UPDATE \`$CONTROL_SCHEMA\`.operation_checkpoint
        SET detail='count,min,max,checksum=$(sql_escape "$stats")'
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND phase_name='sanitize-target'
          AND operation_name='materialize-item-candidates'
          AND database_kind='control' AND table_name='cleanup_item_candidate';"
}

delete_item_candidates() {
    local run_binary
    run_binary="UUID_TO_BIN('$(sql_escape "$RUN_ID")')"
    local bounds count lower upper operation statement hash result
    while :; do
        bounds=$(sanitize_query -e "
            SELECT CONCAT(COUNT(*),',',COALESCE(MIN(guid),0),',',COALESCE(MAX(guid),0))
            FROM (
                SELECT c.guid
                FROM \`$CONTROL_SCHEMA\`.cleanup_item_candidate c
                JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=c.guid
                WHERE c.run_uuid=$run_binary
                ORDER BY c.guid
                LIMIT $CLEANUP_CHUNK_SIZE
            ) pending;")
        IFS=, read -r count lower upper <<< "$bounds"
        (( count > 0 )) || break
        operation=item-candidate-delete
        statement="item candidate deletion v1"
        hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
        if operation_is_complete "$operation" characters item_instance "$lower" "$upper" "$hash"; then
            die "Completed item cleanup chunk ($lower,$upper] still has target rows"
        fi
        mark_operation_running sanitize-target "$operation" characters item_instance \
            "$lower" "$upper" "$hash" "$count"

        local loot_cleanup_sql
        if table_exists "$TARGET_CHARACTERS_SCHEMA" item_loot_storage; then
            loot_cleanup_sql="
                DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_storage x
                JOIN cleanup_items c ON c.guid=x.containerGUID;
                SET @loot=ROW_COUNT();
                $(summary_accumulator_sql item_loot_storage '@loot')"
        else
            loot_cleanup_sql="
                DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_items x
                JOIN cleanup_items c ON c.guid=x.container_id;
                SET @loot_items=ROW_COUNT();
                $(summary_accumulator_sql item_loot_items '@loot_items')
                DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_loot_money x
                JOIN cleanup_items c ON c.guid=x.container_id;
                SET @loot_money=ROW_COUNT();
                $(summary_accumulator_sql item_loot_money '@loot_money')"
        fi

        if ! result=$(sanitize_query -e "
            START TRANSACTION;
            CREATE TEMPORARY TABLE cleanup_items
                (guid int unsigned PRIMARY KEY) ENGINE=InnoDB
            SELECT c.guid
            FROM \`$CONTROL_SCHEMA\`.cleanup_item_candidate c
            JOIN \`$TARGET_CHARACTERS_SCHEMA\`.item_instance i ON i.guid=c.guid
            WHERE c.run_uuid=$run_binary
              AND c.guid>=$lower AND c.guid<=$upper;

            $loot_cleanup_sql
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_refund_instance x
            JOIN cleanup_items c ON c.guid=x.item_guid;
            SET @refund=ROW_COUNT();
            $(summary_accumulator_sql item_refund_instance '@refund')
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_soulbound_trade_data x
            JOIN cleanup_items c ON c.guid=x.itemGuid;
            SET @soulbound=ROW_COUNT();
            $(summary_accumulator_sql item_soulbound_trade_data '@soulbound')
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_gifts x
            JOIN cleanup_items c ON c.guid=x.item_guid;
            SET @gifts=ROW_COUNT();
            $(summary_accumulator_sql character_gifts '@gifts')
            DELETE x FROM \`$TARGET_CHARACTERS_SCHEMA\`.item_instance x
            JOIN cleanup_items c ON c.guid=x.guid;
            SET @items=ROW_COUNT();
            $(summary_accumulator_sql item_instance '@items')

            INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
                (run_id,phase_name,operation_name,database_kind,table_name,
                 chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
                 status,started_at,finished_at)
            VALUES
                ('$(sql_escape "$RUN_ID")','sanitize-target','$operation',
                 'characters','item_instance',$lower,$upper,'$hash',
                 $count,@items,'COMPLETE',UTC_TIMESTAMP(),UTC_TIMESTAMP()) AS new
            ON DUPLICATE KEY UPDATE
                script_hash=new.script_hash,planned_rows=new.planned_rows,
                affected_rows=new.affected_rows,status='COMPLETE',
                finished_at=new.finished_at,detail=NULL;
            COMMIT;
            SELECT @items;"); then
            die "Failed to delete item candidate chunk [$lower,$upper]"
        fi
        [[ $result == "$count" ]] ||
            die "Item cleanup chunk [$lower,$upper] planned $count row(s), deleted $result"
        log "sanitize-target: item candidates [$lower,$upper] completed ($result row(s))"
    done
}

purge_item_roots() {
    run_cleanup_update purge-item-roots cleanup_item_root "
        DELETE FROM \`$CONTROL_SCHEMA\`.cleanup_item_root
        WHERE run_uuid=UUID_TO_BIN('$(sql_escape "$RUN_ID")');"
}

delete_missing_account_state() {
    local table
    for table in account_data account_tutorial account_instance_times; do
        run_cleanup_delete "missing-account-$table" "$table" "
            DELETE d FROM \`$TARGET_CHARACTERS_SCHEMA\`.\`$table\` d
            LEFT JOIN \`$TARGET_AUTH_SCHEMA\`.account a ON a.id=d.accountId
            WHERE a.id IS NULL;"
    done
}

rebuild_realmcharacters() {
    local statement hash affected
    statement="
        DELETE FROM \`$TARGET_AUTH_SCHEMA\`.realmcharacters WHERE realmid=$REALM_ID;
        INSERT INTO \`$TARGET_AUTH_SCHEMA\`.realmcharacters (realmid,acctid,numchars)
        SELECT $REALM_ID,a.id,LEAST(COUNT(c.guid),255)
        FROM \`$TARGET_AUTH_SCHEMA\`.account a
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.account=a.id
        GROUP BY a.id;"
    hash=$(printf '%s' "$statement" | sha256sum | awk '{print $1}')
    operation_is_complete rebuild-realmcharacters auth realmcharacters 0 0 "$hash" && return
    mark_operation_running sanitize-target rebuild-realmcharacters auth \
        realmcharacters 0 0 "$hash" 0
    if ! affected=$(sanitize_query -e "
        START TRANSACTION;
        DELETE FROM \`$TARGET_AUTH_SCHEMA\`.realmcharacters WHERE realmid=$REALM_ID;
        INSERT INTO \`$TARGET_AUTH_SCHEMA\`.realmcharacters (realmid,acctid,numchars)
        SELECT $REALM_ID,a.id,LEAST(COUNT(c.guid),255)
        FROM \`$TARGET_AUTH_SCHEMA\`.account a
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.account=a.id
        GROUP BY a.id;
        SET @affected_rows=ROW_COUNT();
        INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
            (run_id,phase_name,operation_name,database_kind,table_name,
             chunk_start,chunk_end,script_hash,planned_rows,affected_rows,
             status,started_at,finished_at)
        VALUES
            ('$(sql_escape "$RUN_ID")','sanitize-target','rebuild-realmcharacters',
             'auth','realmcharacters',0,0,'$hash',@affected_rows,@affected_rows,
             'COMPLETE',UTC_TIMESTAMP(),UTC_TIMESTAMP()) AS new
        ON DUPLICATE KEY UPDATE
            script_hash=new.script_hash,planned_rows=new.planned_rows,
            affected_rows=new.affected_rows,status='COMPLETE',
            finished_at=new.finished_at,detail=NULL;
        COMMIT;
        SELECT @affected_rows;"); then
        die "Failed to rebuild realmcharacters"
    fi
    log "sanitize-target: rebuilt realmcharacters for $affected account(s)"
}

finish_cleanup_table_summary() {
    local kind schema table removed after
    kind=$1
    schema=$2
    while IFS=$'\t' read -r table removed; do
        [[ -n $table ]] || continue
        if table_exists "$schema" "$table"; then
            after=$(sanitize_query -e "SELECT COUNT(*) FROM \`$schema\`.\`$table\`;")
            sanitize_query -e "
                UPDATE \`$CONTROL_SCHEMA\`.cleanup_table_summary
                SET after_rows=$after,before_rows=$after+$removed
                WHERE run_id='$(sql_escape "$RUN_ID")'
                  AND database_kind='$(sql_escape "$kind")'
                  AND table_name='$(sql_escape "$table")';"
        fi
    done < <(sanitize_query -e "
        SELECT table_name,COALESCE(removed_rows,0)
        FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
        WHERE run_id='$(sql_escape "$RUN_ID")'
          AND database_kind='$(sql_escape "$kind")'
          AND removed_rows>0
        ORDER BY table_name;")
}

write_cleanup_reports() {
    local run_reports="$REPORTS_DIR/$RUN_ID"
    {
        printf 'database_kind\ttable_name\tbefore_rows\tafter_rows\tremoved_rows\tdetail\n'
        sanitize_query -e "
            SELECT database_kind,table_name,before_rows,after_rows,removed_rows,detail
            FROM \`$CONTROL_SCHEMA\`.cleanup_table_summary
            WHERE run_id='$(sql_escape "$RUN_ID")' AND removed_rows>0
            ORDER BY database_kind,table_name;"
    } > "$run_reports/cleanup-table-summary.tsv"
    {
        printf 'phase\toperation\tdatabase_kind\ttable_name\tchunk_start\tchunk_end\tplanned_rows\taffected_rows\telapsed_seconds\tstatus\n'
        sanitize_query -e "
            SELECT phase_name,operation_name,database_kind,table_name,
                   chunk_start,chunk_end,planned_rows,affected_rows,
                   TIMESTAMPDIFF(SECOND,started_at,COALESCE(finished_at,UTC_TIMESTAMP())),
                   status
            FROM \`$CONTROL_SCHEMA\`.operation_checkpoint
            WHERE run_id='$(sql_escape "$RUN_ID")'
            ORDER BY TIMESTAMPDIFF(MICROSECOND,started_at,
                     COALESCE(finished_at,UTC_TIMESTAMP())) DESC;"
    } > "$run_reports/timing.tsv"
}

perform_sanitize_target() {
    require_phase load-auth
    require_phase load-characters
    assert_schema_unchanged auth "$SOURCE_AUTH_SCHEMA"
    assert_schema_unchanged characters "$SOURCE_CHARACTERS_SCHEMA"
    check_quiescence

    capture_orphan_characters
    assert_no_organization_leaders

    local orphan_count
    orphan_count=$(sanitize_query -e "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.cleanup_orphan_character
        WHERE run_id='$(sql_escape "$RUN_ID")';")
    log "Sanitizing $orphan_count target character(s) whose auth accounts are absent"

    delete_orphan_pets
    delete_direct_character_rows
    run_cleanup_delete orphan-characters characters "
        DELETE c FROM \`$TARGET_CHARACTERS_SCHEMA\`.characters c
        JOIN \`$CONTROL_SCHEMA\`.cleanup_orphan_character o
          ON o.run_id='$(sql_escape "$RUN_ID")' AND o.guid=c.guid;"
    delete_missing_account_state
    delete_dangling_relations
    build_item_roots_and_candidates
    delete_item_candidates
    purge_item_roots
    rebuild_realmcharacters

    finish_cleanup_table_summary characters "$TARGET_CHARACTERS_SCHEMA"
    write_cleanup_reports
    log "Completed approved target sanitization; source schemas were not modified"
}
