#!/usr/bin/env bash
# shellcheck disable=SC2016

# Read-only checks run before target assembly and again before either load.
# Reports identify rows without exposing credentials, names, or mail bodies.
check_source_representations() {
    local query
    if [[ $MIGRATION_DIRECTION == tc-to-ac ]]; then
        query="
            SELECT 'auth' database_kind,'account' source_table,CAST(id AS CHAR) source_key,
                   'USERNAME_NOT_AUTHENTICATABLE' reason_code,
                   CONCAT('characters=',CHAR_LENGTH(username),'; bytes=',OCTET_LENGTH(username),
                          '; target column=32 characters; auth limit=17 bytes') reason_detail
            FROM \`$SOURCE_AUTH_SCHEMA\`.account
            WHERE CHAR_LENGTH(username)>32 OR OCTET_LENGTH(username)>17
            UNION ALL
            SELECT 'characters','mail',CAST(id AS CHAR),'UNSUPPORTED_MAIL_FLAGS',
                   CONCAT('checked=',checked,'; supported mask=31')
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.mail WHERE (checked & 4294967264)<>0
            UNION ALL
            SELECT 'characters','character_aura',CONCAT(guid,':',spell),
                   'EMPTY_AURA_CASTER','AzerothCore skips auras with an empty caster GUID'
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.character_aura WHERE casterGuid=0
            UNION ALL
            SELECT 'auth','uptime',CONCAT(realmid,':',starttime),'UPTIME_END_OVERFLOW',
                   'starttime + uptime exceeds unsigned 32-bit EndTime'
            FROM \`$SOURCE_AUTH_SCHEMA\`.uptime WHERE starttime+uptime>4294967295"
    else
        query="
            SELECT 'characters' database_kind,'item_loot_storage' source_table,
                   CONCAT(containerGUID,':',itemid,':',item_index) source_key,
                   'LOOT_INTEGER_OUT_OF_RANGE' reason_code,
                   'Loot payload exceeds native TrinityCore signed integer bounds' reason_detail
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_storage
            WHERE itemid<>0 AND (\`count\`>2147483647 OR randomSuffix>2147483647
                OR follow_loot_rules>127 OR freeforall>127 OR is_blocked>127
                OR is_counted>127 OR is_underthreshold>127 OR needs_quest>127)
            UNION ALL
            SELECT 'characters','item_loot_storage',CAST(containerGUID AS CHAR),
                   'MULTIPLE_LOOT_MONEY_ROWS','More than one money row for a container'
            FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_storage WHERE itemid=0
            GROUP BY containerGUID HAVING COUNT(*)>1"
    fi
    local report="$REPORTS_DIR/$RUN_ID/source-blockers.tsv"
    mkdir -p "$(dirname "$report")"
    printf 'database_kind\tsource_table\tsource_key\treason_code\treason_detail\n' > "$report"
    mysql_query -e "$query ORDER BY database_kind,source_table,source_key,reason_code;" >> "$report"
    if [[ $(wc -l < "$report") -gt 1 ]]; then
        mysql_query -e "
            INSERT INTO \`$CONTROL_SCHEMA\`.migration_reject
                (run_id,database_kind,source_table,source_key,reason_code,reason_detail)
            SELECT '$(sql_escape "$RUN_ID")',database_kind,source_table,source_key,
                   reason_code,reason_detail FROM ($query) blockers;"
        die "Source representations are incompatible; see $report; resolve and start a new run"
    fi
}

normalized_reverse_loot_query() {
    # Payload tie breakers keep distinct rows deterministic. Completely equal
    # duplicates are interchangeable but must retain their multiplicity.
    printf '%s\n' "
        SELECT s.*,
            ROW_NUMBER() OVER (PARTITION BY containerGUID ORDER BY
                item_index,itemid,\`count\`,randomPropertyId,randomSuffix,
                follow_loot_rules,freeforall,is_blocked,is_counted,
                is_underthreshold,needs_quest,conditionLootId)-1 normalized_index
        FROM \`$SOURCE_CHARACTERS_SCHEMA\`.item_loot_storage s WHERE itemid<>0"
}
