#!/usr/bin/env bash
# shellcheck disable=SC2016

# Only the Python SELECT reader touches source/world data. Expected rows are
# immutable control data; actual provenance commits with each target chunk.
summarize_spell_blockers() {
    local report=$1
    printf 'Spell reconstruction blockers (reason_code, affected characters):\n' >&2
    awk -F '\t' 'NR>1 { counts[$3]++ } END { for (reason in counts) print reason "\t" counts[reason] }' \
        "$report" | LC_ALL=C sort >&2
}

prepare_spell_snapshot() {
    local mode=${1:-verify} temporary input_hash expected_hash existing reader_status=0
    require_command python3
    mkdir -p "$REPORTS_DIR/$RUN_ID"
    temporary=$(mktemp -d)
    python3 "$MIGRATION_ROOT/lib/spells.py" \
        --profile "$COMPATIBILITY_PROFILE_DIR/spell-metadata.json" \
        --output "$temporary" --source-characters "$SOURCE_CHARACTERS_SCHEMA" \
        --source-world "$SOURCE_WORLD_SCHEMA" --target-world "$TARGET_WORLD_SCHEMA" \
        --tc-dbc "$TRINITYCORE_DBC_DIR" --ac-dbc "$AZEROTHCORE_DBC_DIR" \
        --control "$CONTROL_SCHEMA" --run-id "$RUN_ID" --direction "$MIGRATION_DIRECTION" \
        --mysql "${MYSQL_ARGS[@]}" || reader_status=$?
    # This diagnostic also covers bindings hidden by a character's first error.
    # Its own status stays INCOMPLETE if the source/metadata read did not finish.
    if [[ -f $temporary/spell-script-review.json ]]; then
        cp "$temporary/spell-script-review.json" "$REPORTS_DIR/$RUN_ID/"
    fi
    if (( reader_status != 0 )); then
        mkdir -p "$REPORTS_DIR/$RUN_ID"
        if (( reader_status == 2 )); then
            cp "$temporary/spell-metadata-errors.tsv" "$REPORTS_DIR/$RUN_ID/"
            rm -rf "$temporary"
            mysql_query -e "UPDATE \`$CONTROL_SCHEMA\`.migration_run SET status='FAILED'
                WHERE run_id='$(sql_escape "$RUN_ID")';"
            die "Spell metadata read failed; see spell-metadata-errors.tsv; compatibility could not be established"
        fi
        if [[ -f $temporary/spell-state-blockers.tsv ]]; then
            cp "$temporary/spell-state-blockers.tsv" "$REPORTS_DIR/$RUN_ID/"
            summarize_spell_blockers "$temporary/spell-state-blockers.tsv"
            local guid spell reason detail
            while IFS=$'\t' read -r guid spell reason detail; do
                [[ $guid == guid ]] && continue
                mysql_query -e "
                    INSERT INTO \`$CONTROL_SCHEMA\`.migration_reject
                        (run_id,database_kind,source_table,source_key,reason_code,reason_detail)
                    VALUES ('$(sql_escape "$RUN_ID")','characters','character_spell',
                        '$(sql_escape "$guid:$spell")','$(sql_escape "$reason")',
                        '$(sql_escape "$detail")');"
            done < "$temporary/spell-state-blockers.tsv"
        fi
        rm -rf "$temporary"
        mysql_query -e "UPDATE \`$CONTROL_SCHEMA\`.migration_run SET status='FAILED'
            WHERE run_id='$(sql_escape "$RUN_ID")';"
        die "Spell state is incompatible; see $REPORTS_DIR/$RUN_ID/spell-state-blockers.tsv; resolve and start a new run"
    fi
    IFS=$'\t' read -r input_hash expected_hash < "$temporary/spell-digests.tsv"
    existing=$(mysql_query -e "SELECT CONCAT(input_hash,':',expected_hash)
        FROM \`$CONTROL_SCHEMA\`.spell_input_snapshot WHERE run_id='$(sql_escape "$RUN_ID")';") ||
        die "Could not read the spell input checkpoint"
    if [[ -n $existing && $existing != "$input_hash:$expected_hash" ]]; then
        cp "$temporary/spell-fingerprints.tsv" "$REPORTS_DIR/$RUN_ID/spell-drift-fingerprints.tsv"
        rm -rf "$temporary"
        mysql_query -e "UPDATE \`$CONTROL_SCHEMA\`.migration_run SET status='FAILED'
            WHERE run_id='$(sql_escape "$RUN_ID")';"
        die "Spell inputs or reconstruction changed after preflight; start a new run"
    fi
    if [[ -z $existing ]]; then
        [[ $mode == capture ]] || die "Missing spell snapshot; start a new run"
        {
            printf 'START TRANSACTION;\n'
            cat "$temporary/spell-expected.sql"
            printf "INSERT INTO \`%s\`.spell_input_snapshot (run_id,input_hash,expected_hash) VALUES ('%s','%s','%s');\n" \
                "$CONTROL_SCHEMA" "$RUN_ID" "$input_hash" "$expected_hash"
            printf 'COMMIT;\n'
        } > "$temporary/capture.sql"
        if ! mysql "${MYSQL_ARGS[@]}" < "$temporary/capture.sql"; then
            rm -rf "$temporary"
            die "Could not commit the spell expectation snapshot"
        fi
        cp "$temporary/spell-fingerprints.tsv" "$REPORTS_DIR/$RUN_ID/"
        cp "$temporary/spell-state-blockers.tsv" "$REPORTS_DIR/$RUN_ID/"
        cp "$temporary/spell-expected.tsv" "$REPORTS_DIR/$RUN_ID/"
    fi
    # Independently recomputed rows also verify that committed expected data
    # has not been edited since capture. Canonical TSV is hashed by Python.
    local actual_hash
    actual_hash=$(mysql_query -e "SELECT guid,spell,spec_mask,active,disabled,disposition,derived,provenance
        FROM \`$CONTROL_SCHEMA\`.spell_expected
        WHERE run_id='$(sql_escape "$RUN_ID")' ORDER BY guid,spell;" | sha256sum | awk '{print $1}') ||
        die "Could not verify committed spell expectations"
    [[ $actual_hash == "$expected_hash" ]] || {
        rm -rf "$temporary"
        die "Committed spell expectation differs from reconstructed source state"
    }
    rm -rf "$temporary"
}

verify_spell_snapshot_if_present() {
    if [[ $(mysql_query -e "SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.spell_input_snapshot
        WHERE run_id='$(sql_escape "$RUN_ID")';") == 1 ]]; then
        prepare_spell_snapshot verify
    fi
}

load_character_spells() {
    local input_hash expected_hash hash expected start end maximum inserted columns values snapshot bounds
    snapshot=$(mysql_query -e "
        SELECT input_hash,expected_hash FROM \`$CONTROL_SCHEMA\`.spell_input_snapshot
        WHERE run_id='$(sql_escape "$RUN_ID")';") || die "Could not read spell checkpoint hashes"
    IFS=$'\t' read -r input_hash expected_hash <<< "$snapshot"
    [[ -n $input_hash && -n $expected_hash ]] || die "Spell snapshot is required before loading"
    hash=$(printf '%s\n' 'spell-state-v4' "$MIGRATION_DIRECTION" "$input_hash" "$expected_hash" "$TOOLKIT_HASH" |
        sha256sum | awk '{print $1}')
    columns='guid,spell,specMask'
    values='guid,spell,spec_mask'
    if [[ $MIGRATION_DIRECTION == ac-to-tc ]]; then
        columns='guid,spell,active,disabled'
        values='guid,spell,active,disabled'
    fi
    expected=$(mysql_query -e "SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.spell_expected
        WHERE run_id='$(sql_escape "$RUN_ID")' AND disposition='PERSISTENT';") || die "Could not count reconstructed spells"
    defer_secondary_indexes characters character_spell "$expected"
    bounds=$(mysql_query -e "SELECT COALESCE(MIN(guid),0),COALESCE(MAX(guid),0)
        FROM \`$CONTROL_SCHEMA\`.spell_expected WHERE run_id='$(sql_escape "$RUN_ID")';") || die "Could not read spell chunk bounds"
    read -r start maximum <<< "$bounds"
    local generated="$REPORTS_DIR/$RUN_ID/generated-characters-character_spell.sql"
    printf '%s\n' "-- spell-state-v4; inputs=$input_hash; expected=$expected_hash" > "$generated"
    while :; do
        end=$((start + LOAD_CHUNK_SIZE - 1))
        (( end > maximum )) && end=$maximum
        local predicate
        predicate="run_id='$(sql_escape "$RUN_ID")' AND guid BETWEEN $start AND $end"
        local statement="INSERT INTO \`$TARGET_SCHEMA\`.character_spell ($columns)
            SELECT $values FROM \`$CONTROL_SCHEMA\`.spell_expected
            WHERE $predicate AND disposition='PERSISTENT' ORDER BY guid,spell;"
        printf '%s\n' "$statement" >> "$generated"
        if ! checkpoint_complete characters character_spell "$start" "$end" "$hash"; then
            mark_operation_running load-characters load-spells characters character_spell \
                "$start" "$end" "$hash" 0
            if ! inserted=$(mysql_query -e "
                SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';
                START TRANSACTION;
                DELETE FROM \`$TARGET_SCHEMA\`.character_spell WHERE guid BETWEEN $start AND $end;
                $statement
                SET @inserted=ROW_COUNT();
                DELETE FROM \`$CONTROL_SCHEMA\`.spell_provenance WHERE $predicate;
                INSERT INTO \`$CONTROL_SCHEMA\`.spell_provenance
                    SELECT * FROM \`$CONTROL_SCHEMA\`.spell_expected WHERE $predicate;
                INSERT INTO \`$CONTROL_SCHEMA\`.chunk_checkpoint
                    (run_id,database_kind,source_table,target_table,chunk_start,chunk_end,
                     script_hash,source_rows,target_rows,status)
                VALUES ('$(sql_escape "$RUN_ID")','characters','character_spell','character_spell',
                    $start,$end,'$hash',@inserted,@inserted,'COMPLETE') AS new
                ON DUPLICATE KEY UPDATE script_hash=new.script_hash,source_rows=new.source_rows,
                    target_rows=new.target_rows,status='COMPLETE',finished_at=UTC_TIMESTAMP();
                INSERT INTO \`$CONTROL_SCHEMA\`.operation_checkpoint
                    (run_id,phase_name,operation_name,database_kind,table_name,chunk_start,chunk_end,
                     script_hash,planned_rows,affected_rows,status,finished_at,detail)
                VALUES ('$(sql_escape "$RUN_ID")','load-characters','load-spells','characters','character_spell',
                    $start,$end,'$hash',@inserted,@inserted,'COMPLETE',UTC_TIMESTAMP(),'spell rows and provenance committed atomically') AS new
                ON DUPLICATE KEY UPDATE status='COMPLETE',script_hash=new.script_hash,
                    affected_rows=new.affected_rows,finished_at=new.finished_at;
                COMMIT;
                SELECT @inserted;"); then
                die "Atomic spell load failed for GUID range [$start,$end]"
            fi
            log "Loaded reconstructed spells [$start,$end]: $inserted row(s)"
        fi
        (( end >= maximum )) && break
        start=$(mysql_query -e "SELECT COALESCE(MIN(guid),$((maximum + 1)))
            FROM \`$CONTROL_SCHEMA\`.spell_expected WHERE run_id='$(sql_escape "$RUN_ID")' AND guid>$end;") ||
            die "Could not advance the spell chunk"
        (( start > maximum )) && break
    done
    restore_secondary_indexes characters character_spell
    write_spell_reports
}

validate_character_spells() {
    local fields='t.specMask<>e.spec_mask'
    [[ $MIGRATION_DIRECTION == tc-to-ac ]] || fields='t.active<>e.active OR t.disabled<>e.disabled'
    check_zero character_spell_semantic_mismatch "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.spell_expected e
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=e.guid
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_spell t ON t.guid=e.guid AND t.spell=e.spell
        WHERE e.run_id='$(sql_escape "$RUN_ID")' AND e.disposition='PERSISTENT'
          AND (t.guid IS NULL OR $fields);" \
        "Every reconstructed persistent spell must have exactly the authorized target state"
    check_zero character_spell_unexpected "
        SELECT COUNT(*) FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_spell t
        LEFT JOIN \`$CONTROL_SCHEMA\`.spell_expected e
          ON e.run_id='$(sql_escape "$RUN_ID")' AND e.guid=t.guid AND e.spell=t.spell AND e.disposition='PERSISTENT'
        WHERE e.guid IS NULL;" "No spell may be granted outside the verified reconstructed set"
    check_zero character_spell_provenance_mismatch "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.spell_expected e
        LEFT JOIN \`$CONTROL_SCHEMA\`.spell_provenance p ON p.run_id=e.run_id AND p.guid=e.guid AND p.spell=e.spell
        WHERE e.run_id='$(sql_escape "$RUN_ID")' AND (p.guid IS NULL OR p.spec_mask<>e.spec_mask
          OR p.disposition<>e.disposition OR p.active<>e.active OR p.disabled<>e.disabled
          OR p.derived<>e.derived OR BINARY p.provenance<>BINARY e.provenance);" \
        "Committed spell provenance must cover persistent and runtime-owned representations"
    check_zero character_spell_unexpected_provenance "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.spell_provenance p
        LEFT JOIN \`$CONTROL_SCHEMA\`.spell_expected e ON e.run_id=p.run_id AND e.guid=p.guid AND e.spell=p.spell
        WHERE p.run_id='$(sql_escape "$RUN_ID")' AND e.guid IS NULL;" \
        "Reports must not contain provenance outside the reconstructed source state"
    local talent_state="SELECT guid,spell,specMask mask FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_talent"
    if [[ $MIGRATION_DIRECTION == ac-to-tc ]]; then
        talent_state="SELECT guid,spell,BIT_OR(1 << talentGroup) mask
            FROM \`$TARGET_CHARACTERS_SCHEMA\`.character_talent GROUP BY guid,spell"
    fi
    check_zero character_spell_delegated_talent_mismatch "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.spell_expected e
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=e.guid
        LEFT JOIN ($talent_state) t ON t.guid=e.guid AND t.spell=e.spell
        WHERE e.run_id='$(sql_escape "$RUN_ID")' AND e.disposition='TALENT'
          AND (t.guid IS NULL OR t.mask<>e.spec_mask);" \
        "Delegated direct talent spells require exactly their unchanged talent owners"
    check_zero character_spell_runtime_owner_mismatch "
        SELECT COUNT(*) FROM (
          SELECT e.guid,e.spell,e.spec_mask,COALESCE(BIT_OR(t.mask),0) owned_mask
          FROM \`$CONTROL_SCHEMA\`.spell_expected e
          JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=e.guid
          CROSS JOIN JSON_TABLE(e.provenance,'$.derivations[*]'
            COLUMNS (anchor INT UNSIGNED PATH '\$[0]')) proof
          LEFT JOIN ($talent_state) t ON t.guid=e.guid AND t.spell=proof.anchor
          WHERE e.run_id='$(sql_escape "$RUN_ID")' AND e.disposition IN ('RUNTIME','AURA')
          GROUP BY e.guid,e.spell,e.spec_mask
        ) ownership WHERE spec_mask<>owned_mask;" \
        "Runtime temporary spells must be covered by verified target talent ownership"
    if [[ $MIGRATION_DIRECTION == tc-to-ac ]]; then
        check_zero character_spell_native_passive_contract_mismatch "
            SELECT COUNT(*) FROM (
              SELECT e.guid,e.spell,e.spec_mask,e.disposition,
                JSON_UNQUOTE(JSON_EXTRACT(e.provenance,'$.authorization.native_passive_rank.target_representation')) representation,
                JSON_UNQUOTE(JSON_EXTRACT(e.provenance,'$.authorization.native_passive_rank.target_predecessors_persisted')) persisted,
                COALESCE(BIT_OR(owner.mask),0) owner_mask,
                SUM(IF(t.guid IS NULL OR t.mask<>owner.mask,1,0)) invalid_owner
              FROM \`$CONTROL_SCHEMA\`.spell_expected e
              JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=e.guid
              LEFT JOIN JSON_TABLE(e.provenance,'$.authorization.native_passive_rank.owner_masks[*]'
                COLUMNS (spell INT UNSIGNED PATH '\$[0]',mask INT UNSIGNED PATH '\$[1]')) owner ON TRUE
              LEFT JOIN ($talent_state) t ON t.guid=e.guid AND t.spell=owner.spell
              WHERE e.run_id='$(sql_escape "$RUN_ID")'
                AND JSON_EXTRACT(e.provenance,'$.authorization.native_passive_rank') IS NOT NULL
              GROUP BY e.guid,e.spell,e.spec_mask,e.disposition,representation,persisted
            ) passive_contract WHERE disposition<>'RUNTIME' OR spec_mask<>owner_mask OR invalid_owner<>0
                OR COALESCE(representation,'')<>'AC_NATIVE_EXACT' OR COALESCE(persisted,'')<>'false';" \
            "Reviewed passive ranks must remain exact native children of unchanged selected talents"
    fi
    check_zero character_spell_skill_reward_mismatch "
        SELECT COUNT(*) FROM \`$CONTROL_SCHEMA\`.spell_expected e
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=e.guid
        LEFT JOIN JSON_TABLE(e.provenance,'$.authorization.native_skill_rewards[*]'
          COLUMNS (parent_spell INT PATH '$.parent',skill INT PATH '$.skill',
                   value_expected INT PATH '$.value',max_expected INT PATH '$.max')) reward ON TRUE
        LEFT JOIN \`$CONTROL_SCHEMA\`.spell_expected parent ON parent.run_id=e.run_id
          AND parent.guid=e.guid AND parent.spell=reward.parent_spell
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_skills s ON s.guid=e.guid AND s.skill=reward.skill
        WHERE e.run_id='$(sql_escape "$RUN_ID")' AND e.disposition='SKILL'
          AND (e.spec_mask<>3 OR reward.skill IS NULL OR parent.spell IS NULL
            OR parent.disposition<>'PERSISTENT' OR parent.spec_mask<>3
            OR s.skill IS NULL OR s.value<>reward.value_expected OR s.max<>reward.max_expected);" \
        "Native skill rewards require an unchanged skill and verified known parent"
    check_zero character_spell_specialization_context_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.characters s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters t ON t.guid=s.guid
        WHERE s.activeTalentGroup<>t.activeTalentGroup OR s.talentGroupsCount<>t.talentGroupsCount;" \
        "Spell conversion must retain specialization count and active group"
    local teacher_button_state='button.specMask<>3'
    [[ $MIGRATION_DIRECTION == ac-to-tc ]] && teacher_button_state='button.active<>1 OR button.disabled<>0'
    check_zero character_spell_consumed_teacher_mismatch "
        SELECT COUNT(*) FROM (
          SELECT e.guid,e.spell,e.spec_mask,c.talentGroupsCount,c.level,
            generic.value generic_value,generic.max generic_cap,
            COUNT(DISTINCT child.spell) children,COUNT(child.spell) child_rows,
            SUM(IF(child.spell IS NULL OR child.spell NOT IN (63644,63645)
              OR (e.spell IN (63706,63707) AND child.spell<>IF(e.spell=63706,63645,63644))
              OR expected_button.spell IS NULL OR expected_button.spec_mask<>3
              OR expected_button.disposition<>'PERSISTENT' OR button.spell IS NULL
              OR $teacher_button_state,1,0)) invalid_buttons
          FROM \`$CONTROL_SCHEMA\`.spell_expected e
          JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=e.guid
          LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_skills generic ON generic.guid=e.guid AND generic.skill=183
          LEFT JOIN JSON_TABLE(e.provenance,'$.authorization.consumed_teacher.children[*]'
            COLUMNS (spell INT UNSIGNED PATH '$')) child ON TRUE
          LEFT JOIN \`$CONTROL_SCHEMA\`.spell_expected expected_button ON expected_button.run_id=e.run_id
            AND expected_button.guid=e.guid AND expected_button.spell=child.spell
          LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_spell button ON button.guid=e.guid AND button.spell=child.spell
          WHERE e.run_id='$(sql_escape "$RUN_ID")' AND e.disposition='TEACHER'
          GROUP BY e.guid,e.spell,e.spec_mask,c.talentGroupsCount,c.level,generic.value,generic.max
        ) contract WHERE '$MIGRATION_DIRECTION'<>'tc-to-ac' OR spell NOT IN (63680,63706,63707) OR spec_mask<>3
            OR talentGroupsCount<>2 OR children<>IF(spell=63680,2,1) OR child_rows<>children OR invalid_buttons<>0
            OR generic_value IS NULL OR generic_value<>level*5 OR generic_cap<>level*5;" \
        "Consumed spec wrappers require their exact persistent buttons and unchanged existing two-spec ownership"
    check_zero character_skill_semantic_mismatch "
        SELECT COUNT(*) FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_skills s
        JOIN \`$TARGET_CHARACTERS_SCHEMA\`.characters c ON c.guid=s.guid
        LEFT JOIN \`$TARGET_CHARACTERS_SCHEMA\`.character_skills t ON t.guid=s.guid AND t.skill=s.skill
        WHERE t.guid IS NULL OR t.value<>s.value OR t.max<>s.max;" \
        "Spell reconstruction must not alter stored skill values or caps"
    write_spell_reports
}

write_spell_reports() {
    mkdir -p "$REPORTS_DIR/$RUN_ID"
    {
        printf 'guid\tspell\tspec_mask\tdisposition\tderived\tprovenance\n'
        mysql_query -e "SELECT guid,spell,spec_mask,disposition,derived,provenance
            FROM \`$CONTROL_SCHEMA\`.spell_provenance WHERE run_id='$(sql_escape "$RUN_ID")' ORDER BY guid,spell;"
    } > "$REPORTS_DIR/$RUN_ID/spell-reconstruction.tsv"
    {
        printf 'guid\tspell\tspec_mask\tnative_passive_rank_contract\n'
        mysql_query -e "SELECT guid,spell,spec_mask,JSON_EXTRACT(provenance,'$.authorization.native_passive_rank')
            FROM \`$CONTROL_SCHEMA\`.spell_provenance WHERE run_id='$(sql_escape "$RUN_ID")'
              AND JSON_EXTRACT(provenance,'$.authorization.native_passive_rank') IS NOT NULL ORDER BY guid,spell;"
    } > "$REPORTS_DIR/$RUN_ID/spell-native-passive-ranks.tsv"
    {
        printf 'guid\tspell\toriginal_flags\tconsumed_teacher_contract\n'
        mysql_query -e "SELECT guid,spell,JSON_EXTRACT(provenance,'$.original'),JSON_EXTRACT(provenance,'$.authorization.consumed_teacher')
            FROM \`$CONTROL_SCHEMA\`.spell_provenance WHERE run_id='$(sql_escape "$RUN_ID")'
              AND disposition='TEACHER' ORDER BY guid,spell;"
    } > "$REPORTS_DIR/$RUN_ID/spell-consumed-teachers.tsv"
}
