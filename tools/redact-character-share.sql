-- Privacy redaction for a disposable TrinityCore character sharing copy only.
-- Policy tc-character-share-v1; reviewed TC 92127cd6252edb96fbfa36540db0eba17d0031fa.
-- See runbooks/sharing-character-snapshot.md before running.
-- Select a dedicated database whose name ends in _share through mysql --database.
-- Installing this procedure DOES NOT redact data. CALL PREVIEW, APPLY, then VERIFY.
-- No original sensitive content is archived. Restore the private input dump to undo.
-- Use fresh batch connections with --skip-force; do not use --force or SOURCE.

DELIMITER //
CREATE PROCEDURE migrator_redact_character_share(
    IN p_mode VARCHAR(16),
    IN p_ack VARCHAR(80)
)
SQL SECURITY INVOKER
main: BEGIN
    DECLARE v_schema VARCHAR(64);
    DECLARE v_mode VARCHAR(16);
    DECLARE v_table VARCHAR(64);
    DECLARE v_column VARCHAR(64);
    DECLARE v_action VARCHAR(8);
    DECLARE v_issues BIGINT DEFAULT 0;
    DECLARE v_done BOOLEAN DEFAULT FALSE;
    DECLARE v_started BOOLEAN DEFAULT FALSE;
    DECLARE v_prepared BOOLEAN DEFAULT FALSE;
    DECLARE v_cursor_open BOOLEAN DEFAULT FALSE;
    DECLARE v_changed BIGINT DEFAULT 0;
    DECLARE v_catalog JSON;
    DECLARE rules CURSOR FOR
        SELECT table_name,column_name,action
        FROM tmp_migrator_share_rules ORDER BY table_name,column_name;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done=TRUE;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        IF v_started THEN ROLLBACK; END IF;
        IF v_prepared THEN DEALLOCATE PREPARE share_stmt; END IF;
        IF v_cursor_open THEN CLOSE rules; END IF;
        SET @migrator_share_sql=NULL, @migrator_share_count=NULL;
        RESIGNAL;
    END;

    SET v_schema=DATABASE(),v_mode=UPPER(p_mode);
    IF v_schema IS NULL OR RIGHT(v_schema,6)<>'_share'
       OR v_schema NOT REGEXP '^[A-Za-z0-9_]+$' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT=
            'SHARE_SCHEMA_REQUIRED: select a disposable database ending in _share';
    END IF;
    IF p_mode IS NULL OR v_mode NOT IN ('PREVIEW','APPLY','VERIFY') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='INVALID_SHARE_MODE: PREVIEW, APPLY or VERIFY';
    END IF;
    IF v_mode='APPLY' AND (p_ack IS NULL OR BINARY p_ack<>
            BINARY 'DISPOSABLE_SHARE_COPY_WRITERS_STOPPED') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT=
            'SHARE_ACK_REQUIRED: APPLY requires DISPOSABLE_SHARE_COPY_WRITERS_STOPPED';
    END IF;
    IF @@autocommit<>1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='FRESH_CONNECTION_REQUIRED: use autocommit=1';
    END IF;
    IF @@version NOT LIKE '8.4.%' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='MYSQL_84_REQUIRED: this procedure is tested on MySQL 8.4';
    END IF;

    DROP TEMPORARY TABLE IF EXISTS tmp_migrator_share_columns;
    DROP TEMPORARY TABLE IF EXISTS tmp_migrator_share_rules;
    DROP TEMPORARY TABLE IF EXISTS tmp_migrator_share_issues;
    DROP TEMPORARY TABLE IF EXISTS tmp_migrator_share_report;
    CREATE TEMPORARY TABLE tmp_migrator_share_columns(
        table_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
        column_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
        data_type VARCHAR(64) NOT NULL, PRIMARY KEY(table_name,column_name)
    ) ENGINE=InnoDB;
    CREATE TEMPORARY TABLE tmp_migrator_share_rules(
        table_name VARCHAR(64) NOT NULL,column_name VARCHAR(64) NOT NULL,
        action VARCHAR(8) NOT NULL,PRIMARY KEY(table_name,column_name)
    ) ENGINE=InnoDB;
    CREATE TEMPORARY TABLE tmp_migrator_share_issues(
        reason VARCHAR(48),object_name VARCHAR(140)
    ) ENGINE=InnoDB;
    CREATE TEMPORARY TABLE tmp_migrator_share_report(
        table_name VARCHAR(64),column_name VARCHAR(64),action VARCHAR(8),
        nonempty_before BIGINT,changed_rows BIGINT DEFAULT 0,nonempty_after BIGINT,
        PRIMARY KEY(table_name,column_name)
    ) ENGINE=InnoDB;

    -- Stock columns are an inventory, not deletion instructions for unknown fields.
    SET v_catalog='[
{"table":"account_data","columns":[["accountId","int"],["type","tinyint"],["time","int"],["data","blob"]]},
{"table":"account_instance_times","columns":[["accountId","int"],["instanceId","int"],["releaseTime","bigint"]]},
{"table":"account_tutorial","columns":[["accountId","int"],["tut0","int"],["tut1","int"],["tut2","int"],["tut3","int"],["tut4","int"],["tut5","int"],["tut6","int"],["tut7","int"]]},
{"table":"addons","columns":[["name","varchar"],["crc","int"]]},
{"table":"arena_team","columns":[["arenaTeamId","int"],["name","varchar"],["captainGuid","int"],["type","tinyint"],["rating","smallint"],["seasonGames","smallint"],["seasonWins","smallint"],["weekGames","smallint"],["weekWins","smallint"],["rank","int"],["backgroundColor","int"],["emblemStyle","tinyint"],["emblemColor","int"],["borderStyle","tinyint"],["borderColor","int"]]},
{"table":"arena_team_member","columns":[["arenaTeamId","int"],["guid","int"],["weekGames","smallint"],["weekWins","smallint"],["seasonGames","smallint"],["seasonWins","smallint"],["personalRating","smallint"]]},
{"table":"auctionbidders","columns":[["id","int"],["bidderguid","int"]]},
{"table":"auctionhouse","columns":[["id","int"],["houseid","tinyint"],["itemguid","int"],["itemowner","int"],["buyoutprice","int"],["time","int"],["buyguid","int"],["lastbid","int"],["startbid","int"],["deposit","int"],["Flags","tinyint"]]},
{"table":"banned_addons","columns":[["Id","int"],["Name","varchar"],["Version","varchar"],["Timestamp","timestamp"]]},
{"table":"battleground_deserters","columns":[["guid","int"],["type","tinyint"],["datetime","datetime"]]},
{"table":"bugreport","columns":[["id","int"],["type","longtext"],["content","longtext"]]},
{"table":"calendar_events","columns":[["id","bigint"],["creator","int"],["title","varchar"],["description","varchar"],["type","tinyint"],["dungeon","int"],["eventtime","int"],["flags","int"],["time2","int"]]},
{"table":"calendar_invites","columns":[["id","bigint"],["event","bigint"],["invitee","int"],["sender","int"],["status","tinyint"],["statustime","int"],["rank","tinyint"],["text","varchar"]]},
{"table":"channels","columns":[["name","varchar"],["team","int"],["announce","tinyint"],["ownership","tinyint"],["password","varchar"],["bannedList","text"],["lastUsed","int"]]},
{"table":"character_account_data","columns":[["guid","int"],["type","tinyint"],["time","int"],["data","blob"]]},
{"table":"character_achievement","columns":[["guid","int"],["achievement","smallint"],["date","int"]]},
{"table":"character_achievement_progress","columns":[["guid","int"],["criteria","smallint"],["counter","int"],["date","int"]]},
{"table":"character_action","columns":[["guid","int"],["spec","tinyint"],["button","tinyint"],["action","int"],["type","tinyint"]]},
{"table":"character_arena_stats","columns":[["guid","int"],["slot","tinyint"],["matchMakerRating","smallint"]]},
{"table":"character_aura","columns":[["guid","int"],["casterGuid","bigint"],["itemGuid","bigint"],["spell","mediumint"],["effectMask","tinyint"],["recalculateMask","tinyint"],["stackCount","tinyint"],["amount0","int"],["amount1","int"],["amount2","int"],["base_amount0","int"],["base_amount1","int"],["base_amount2","int"],["maxDuration","int"],["remainTime","int"],["remainCharges","tinyint"],["critChance","float"],["applyResilience","tinyint"]]},
{"table":"character_banned","columns":[["guid","int"],["bandate","int"],["unbandate","int"],["bannedby","varchar"],["banreason","varchar"],["active","tinyint"]]},
{"table":"character_battleground_data","columns":[["guid","int"],["instanceId","int"],["team","smallint"],["joinX","float"],["joinY","float"],["joinZ","float"],["joinO","float"],["joinMapId","smallint"],["taxiStart","int"],["taxiEnd","int"],["mountSpell","int"]]},
{"table":"character_battleground_random","columns":[["guid","int"]]},
{"table":"character_declinedname","columns":[["guid","int"],["genitive","varchar"],["dative","varchar"],["accusative","varchar"],["instrumental","varchar"],["prepositional","varchar"]]},
{"table":"character_equipmentsets","columns":[["guid","int"],["setguid","bigint"],["setindex","tinyint"],["name","varchar"],["iconname","varchar"],["ignore_mask","int"],["item0","int"],["item1","int"],["item2","int"],["item3","int"],["item4","int"],["item5","int"],["item6","int"],["item7","int"],["item8","int"],["item9","int"],["item10","int"],["item11","int"],["item12","int"],["item13","int"],["item14","int"],["item15","int"],["item16","int"],["item17","int"],["item18","int"]]},
{"table":"character_fishingsteps","columns":[["guid","int"],["fishingSteps","tinyint"]]},
{"table":"character_gifts","columns":[["guid","int"],["item_guid","int"],["entry","int"],["flags","int"]]},
{"table":"character_glyphs","columns":[["guid","int"],["talentGroup","tinyint"],["glyph1","smallint"],["glyph2","smallint"],["glyph3","smallint"],["glyph4","smallint"],["glyph5","smallint"],["glyph6","smallint"]]},
{"table":"character_homebind","columns":[["guid","int"],["mapId","smallint"],["zoneId","smallint"],["posX","float"],["posY","float"],["posZ","float"]]},
{"table":"character_instance","columns":[["guid","int"],["instance","int"],["permanent","tinyint"],["extendState","tinyint"]]},
{"table":"character_inventory","columns":[["guid","int"],["bag","int"],["slot","tinyint"],["item","int"]]},
{"table":"character_pet","columns":[["id","int"],["entry","int"],["owner","int"],["modelid","int"],["CreatedBySpell","mediumint"],["PetType","tinyint"],["level","smallint"],["exp","int"],["Reactstate","tinyint"],["name","varchar"],["renamed","tinyint"],["slot","tinyint"],["curhealth","int"],["curmana","int"],["curhappiness","int"],["savetime","int"],["abdata","text"]]},
{"table":"character_pet_declinedname","columns":[["id","int"],["owner","int"],["genitive","varchar"],["dative","varchar"],["accusative","varchar"],["instrumental","varchar"],["prepositional","varchar"]]},
{"table":"character_queststatus","columns":[["guid","int"],["quest","int"],["status","tinyint"],["explored","tinyint"],["timer","int"],["mobcount1","smallint"],["mobcount2","smallint"],["mobcount3","smallint"],["mobcount4","smallint"],["itemcount1","smallint"],["itemcount2","smallint"],["itemcount3","smallint"],["itemcount4","smallint"],["itemcount5","smallint"],["itemcount6","smallint"],["playercount","smallint"]]},
{"table":"character_queststatus_daily","columns":[["guid","int"],["quest","int"],["time","int"]]},
{"table":"character_queststatus_monthly","columns":[["guid","int"],["quest","int"]]},
{"table":"character_queststatus_rewarded","columns":[["guid","int"],["quest","int"],["active","tinyint"]]},
{"table":"character_queststatus_seasonal","columns":[["guid","int"],["quest","int"],["event","int"],["completedTime","bigint"]]},
{"table":"character_queststatus_weekly","columns":[["guid","int"],["quest","int"]]},
{"table":"character_reputation","columns":[["guid","int"],["faction","smallint"],["standing","int"],["flags","smallint"]]},
{"table":"character_skills","columns":[["guid","int"],["skill","smallint"],["value","smallint"],["max","smallint"]]},
{"table":"character_social","columns":[["guid","int"],["friend","int"],["flags","tinyint"],["note","varchar"]]},
{"table":"character_spell","columns":[["guid","int"],["spell","mediumint"],["active","tinyint"],["disabled","tinyint"]]},
{"table":"character_spell_cooldown","columns":[["guid","int"],["spell","mediumint"],["item","int"],["time","int"],["categoryId","int"],["categoryEnd","int"]]},
{"table":"character_stats","columns":[["guid","int"],["maxhealth","int"],["maxpower1","int"],["maxpower2","int"],["maxpower3","int"],["maxpower4","int"],["maxpower5","int"],["maxpower6","int"],["maxpower7","int"],["strength","int"],["agility","int"],["stamina","int"],["intellect","int"],["spirit","int"],["armor","int"],["resHoly","int"],["resFire","int"],["resNature","int"],["resFrost","int"],["resShadow","int"],["resArcane","int"],["blockPct","float"],["dodgePct","float"],["parryPct","float"],["critPct","float"],["rangedCritPct","float"],["spellCritPct","float"],["attackPower","int"],["rangedAttackPower","int"],["spellPower","int"],["resilience","int"]]},
{"table":"character_talent","columns":[["guid","int"],["spell","mediumint"],["talentGroup","tinyint"]]},
{"table":"characters","columns":[["guid","int"],["account","int"],["name","varchar"],["race","tinyint"],["class","tinyint"],["gender","tinyint"],["level","tinyint"],["xp","int"],["money","int"],["skin","tinyint"],["face","tinyint"],["hairStyle","tinyint"],["hairColor","tinyint"],["facialStyle","tinyint"],["bankSlots","tinyint"],["restState","tinyint"],["playerFlags","int"],["position_x","float"],["position_y","float"],["position_z","float"],["map","smallint"],["instance_id","int"],["instance_mode_mask","tinyint"],["orientation","float"],["taximask","text"],["online","tinyint"],["cinematic","tinyint"],["totaltime","int"],["leveltime","int"],["logout_time","int"],["is_logout_resting","tinyint"],["rest_bonus","float"],["resettalents_cost","int"],["resettalents_time","int"],["trans_x","float"],["trans_y","float"],["trans_z","float"],["trans_o","float"],["transguid","mediumint"],["extra_flags","smallint"],["stable_slots","tinyint"],["at_login","smallint"],["zone","smallint"],["death_expire_time","int"],["taxi_path","text"],["arenaPoints","int"],["totalHonorPoints","int"],["todayHonorPoints","int"],["yesterdayHonorPoints","int"],["totalKills","int"],["todayKills","smallint"],["yesterdayKills","smallint"],["chosenTitle","int"],["knownCurrencies","bigint"],["watchedFaction","int"],["drunk","tinyint"],["health","int"],["power1","int"],["power2","int"],["power3","int"],["power4","int"],["power5","int"],["power6","int"],["power7","int"],["latency","mediumint"],["talentGroupsCount","tinyint"],["activeTalentGroup","tinyint"],["exploredZones","longtext"],["equipmentCache","longtext"],["ammoId","int"],["knownTitles","longtext"],["actionBars","tinyint"],["grantableLevels","tinyint"],["deleteInfos_Account","int"],["deleteInfos_Name","varchar"],["deleteDate","int"]]},
{"table":"corpse","columns":[["guid","int"],["posX","float"],["posY","float"],["posZ","float"],["orientation","float"],["mapId","smallint"],["phaseMask","int"],["displayId","int"],["itemCache","text"],["bytes1","int"],["bytes2","int"],["guildId","int"],["flags","tinyint"],["dynFlags","tinyint"],["time","int"],["corpseType","tinyint"],["instanceId","int"]]},
{"table":"game_event_condition_save","columns":[["eventEntry","tinyint"],["condition_id","int"],["done","float"]]},
{"table":"game_event_save","columns":[["eventEntry","tinyint"],["state","tinyint"],["next_start","int"]]},
{"table":"gm_subsurvey","columns":[["surveyId","int"],["questionId","int"],["answer","int"],["answerComment","text"]]},
{"table":"gm_survey","columns":[["surveyId","int"],["guid","int"],["mainSurvey","int"],["comment","longtext"],["createTime","int"]]},
{"table":"gm_ticket","columns":[["id","int"],["type","tinyint"],["playerGuid","int"],["name","varchar"],["description","text"],["createTime","int"],["mapId","smallint"],["posX","float"],["posY","float"],["posZ","float"],["lastModifiedTime","int"],["closedBy","int"],["assignedTo","int"],["comment","text"],["response","text"],["completed","tinyint"],["escalated","tinyint"],["viewed","tinyint"],["needMoreHelp","tinyint"],["resolvedBy","int"]]},
{"table":"group_instance","columns":[["guid","int"],["instance","int"],["permanent","tinyint"]]},
{"table":"group_member","columns":[["guid","int"],["memberGuid","int"],["memberFlags","tinyint"],["subgroup","tinyint"],["roles","tinyint"]]},
{"table":"groups","columns":[["guid","int"],["leaderGuid","int"],["lootMethod","tinyint"],["looterGuid","int"],["lootThreshold","tinyint"],["icon1","bigint"],["icon2","bigint"],["icon3","bigint"],["icon4","bigint"],["icon5","bigint"],["icon6","bigint"],["icon7","bigint"],["icon8","bigint"],["groupType","tinyint"],["difficulty","tinyint"],["raidDifficulty","tinyint"],["masterLooterGuid","int"]]},
{"table":"guild","columns":[["guildid","int"],["name","varchar"],["leaderguid","int"],["EmblemStyle","tinyint"],["EmblemColor","tinyint"],["BorderStyle","tinyint"],["BorderColor","tinyint"],["BackgroundColor","tinyint"],["info","varchar"],["motd","varchar"],["createdate","int"],["BankMoney","bigint"]]},
{"table":"guild_bank_eventlog","columns":[["guildid","int"],["LogGuid","int"],["TabId","tinyint"],["EventType","tinyint"],["PlayerGuid","int"],["ItemOrMoney","int"],["ItemStackCount","smallint"],["DestTabId","tinyint"],["TimeStamp","int"]]},
{"table":"guild_bank_item","columns":[["guildid","int"],["TabId","tinyint"],["SlotId","tinyint"],["item_guid","int"]]},
{"table":"guild_bank_right","columns":[["guildid","int"],["TabId","tinyint"],["rid","tinyint"],["gbright","tinyint"],["SlotPerDay","int"]]},
{"table":"guild_bank_tab","columns":[["guildid","int"],["TabId","tinyint"],["TabName","varchar"],["TabIcon","varchar"],["TabText","varchar"]]},
{"table":"guild_eventlog","columns":[["guildid","int"],["LogGuid","int"],["EventType","tinyint"],["PlayerGuid1","int"],["PlayerGuid2","int"],["NewRank","tinyint"],["TimeStamp","int"]]},
{"table":"guild_member","columns":[["guildid","int"],["guid","int"],["rank","tinyint"],["pnote","varchar"],["offnote","varchar"]]},
{"table":"guild_member_withdraw","columns":[["guid","int"],["tab0","int"],["tab1","int"],["tab2","int"],["tab3","int"],["tab4","int"],["tab5","int"],["money","int"]]},
{"table":"guild_rank","columns":[["guildid","int"],["rid","tinyint"],["rname","varchar"],["rights","mediumint"],["BankMoneyPerDay","int"]]},
{"table":"instance","columns":[["id","int"],["map","smallint"],["resettime","bigint"],["difficulty","tinyint"],["completedEncounters","int"],["data","tinytext"]]},
{"table":"instance_reset","columns":[["mapid","smallint"],["difficulty","tinyint"],["resettime","bigint"]]},
{"table":"item_instance","columns":[["guid","int"],["itemEntry","mediumint"],["owner_guid","int"],["creatorGuid","int"],["giftCreatorGuid","int"],["count","int"],["duration","int"],["charges","tinytext"],["flags","mediumint"],["enchantments","text"],["randomPropertyId","smallint"],["durability","smallint"],["playedTime","int"],["text","text"]]},
{"table":"item_loot_items","columns":[["container_id","int"],["item_id","int"],["item_count","int"],["item_index","int"],["follow_rules","tinyint"],["ffa","tinyint"],["blocked","tinyint"],["counted","tinyint"],["under_threshold","tinyint"],["needs_quest","tinyint"],["rnd_prop","int"],["rnd_suffix","int"]]},
{"table":"item_loot_money","columns":[["container_id","int"],["money","int"]]},
{"table":"item_refund_instance","columns":[["item_guid","int"],["player_guid","int"],["paidMoney","int"],["paidExtendedCost","smallint"]]},
{"table":"item_soulbound_trade_data","columns":[["itemGuid","int"],["allowedPlayers","text"]]},
{"table":"lag_reports","columns":[["reportId","int"],["guid","int"],["lagType","tinyint"],["mapId","smallint"],["posX","float"],["posY","float"],["posZ","float"],["latency","int"],["createTime","int"]]},
{"table":"lfg_data","columns":[["guid","int"],["dungeon","int"],["state","tinyint"]]},
{"table":"mail","columns":[["id","int"],["messageType","tinyint"],["stationery","tinyint"],["mailTemplateId","smallint"],["sender","int"],["receiver","int"],["subject","longtext"],["body","longtext"],["has_items","tinyint"],["expire_time","int"],["deliver_time","int"],["money","int"],["cod","int"],["checked","int"]]},
{"table":"mail_items","columns":[["mail_id","int"],["item_guid","int"],["receiver","int"]]},
{"table":"pet_aura","columns":[["guid","int"],["casterGuid","bigint"],["spell","mediumint"],["effectMask","tinyint"],["recalculateMask","tinyint"],["stackCount","tinyint"],["amount0","mediumint"],["amount1","mediumint"],["amount2","mediumint"],["base_amount0","mediumint"],["base_amount1","mediumint"],["base_amount2","mediumint"],["maxDuration","int"],["remainTime","int"],["remainCharges","tinyint"],["critChance","float"],["applyResilience","tinyint"]]},
{"table":"pet_spell","columns":[["guid","int"],["spell","mediumint"],["active","tinyint"]]},
{"table":"pet_spell_cooldown","columns":[["guid","int"],["spell","mediumint"],["time","int"],["categoryId","int"],["categoryEnd","int"]]},
{"table":"petition","columns":[["ownerguid","int"],["petitionguid","int"],["name","varchar"],["type","tinyint"]]},
{"table":"petition_sign","columns":[["ownerguid","int"],["petitionguid","int"],["playerguid","int"],["player_account","int"],["type","tinyint"]]},
{"table":"pool_quest_save","columns":[["pool_id","int"],["quest_id","int"]]},
{"table":"pvpstats_battlegrounds","columns":[["id","bigint"],["winner_faction","tinyint"],["bracket_id","tinyint"],["type","tinyint"],["date","datetime"]]},
{"table":"pvpstats_players","columns":[["battleground_id","bigint"],["character_guid","int"],["winner","bit"],["score_killing_blows","mediumint"],["score_deaths","mediumint"],["score_honorable_kills","mediumint"],["score_bonus_honor","mediumint"],["score_damage_done","mediumint"],["score_healing_done","mediumint"],["attr_1","mediumint"],["attr_2","mediumint"],["attr_3","mediumint"],["attr_4","mediumint"],["attr_5","mediumint"]]},
{"table":"quest_tracker","columns":[["id","int"],["character_guid","int"],["quest_accept_time","datetime"],["quest_complete_time","datetime"],["quest_abandon_time","datetime"],["completed_by_gm","tinyint"],["core_hash","varchar"],["core_revision","varchar"]]},
{"table":"reserved_name","columns":[["name","varchar"]]},
{"table":"respawn","columns":[["type","smallint"],["spawnId","int"],["respawnTime","bigint"],["mapId","smallint"],["instanceId","int"]]},
{"table":"updates","columns":[["name","varchar"],["hash","char"],["state","enum"],["timestamp","timestamp"],["speed","int"]]},
{"table":"updates_include","columns":[["path","varchar"],["state","enum"]]},
{"table":"warden_action","columns":[["wardenId","smallint"],["action","tinyint"]]},
{"table":"worldstates","columns":[["entry","int"],["value","int"],["comment","tinytext"]]}
]';
    INSERT INTO tmp_migrator_share_columns
    SELECT table_name,column_name,data_type FROM JSON_TABLE(v_catalog,'$[*]' COLUMNS(
        table_name VARCHAR(64) PATH '$.table',
        NESTED PATH '$.columns[*]' COLUMNS(
            column_name VARCHAR(64) PATH '$[0]',data_type VARCHAR(64) PATH '$[1]'
        )
    )) AS stock_columns;
    INSERT INTO tmp_migrator_share_rules(table_name,column_name,action) VALUES
        ('account_data','data','EMPTY'),
        ('account_data','time','ZERO'),
        ('bugreport','content','EMPTY'),
        ('bugreport','type','EMPTY'),
        ('calendar_events','description','EMPTY'),
        ('calendar_events','title','EMPTY'),
        ('calendar_invites','text','EMPTY'),
        ('channels','password','EMPTY'),
        ('character_account_data','data','EMPTY'),
        ('character_account_data','time','ZERO'),
        ('character_banned','bannedby','EMPTY'),
        ('character_banned','banreason','EMPTY'),
        ('character_equipmentsets','iconname','EMPTY'),
        ('character_equipmentsets','name','EMPTY'),
        ('character_social','note','EMPTY'),
        ('gm_subsurvey','answerComment','EMPTY'),
        ('gm_survey','comment','EMPTY'),
        ('gm_ticket','comment','EMPTY'),
        ('gm_ticket','description','EMPTY'),
        ('gm_ticket','response','EMPTY'),
        ('guild','info','EMPTY'),
        ('guild','motd','EMPTY'),
        ('guild_bank_tab','TabIcon','EMPTY'),
        ('guild_bank_tab','TabName','EMPTY'),
        ('guild_bank_tab','TabText','EMPTY'),
        ('guild_member','offnote','EMPTY'),
        ('guild_member','pnote','EMPTY'),
        ('guild_rank','rname','EMPTY'),
        ('item_instance','text','EMPTY'),
        ('mail','body','EMPTY'),
        ('mail','subject','EMPTY'),
        ('worldstates','comment','EMPTY');

    -- Do not invoke unknown triggers, export hidden custom data, or erase columns
    -- whose shape differs from the reviewed schema. Report identifiers, never values.
    INSERT INTO tmp_migrator_share_issues
    SELECT 'MISSING_OR_CHANGED_STOCK_COLUMN',CONCAT(r.table_name,'.',r.column_name)
    FROM tmp_migrator_share_columns r
    LEFT JOIN information_schema.COLUMNS c ON c.TABLE_SCHEMA=v_schema
        AND BINARY c.TABLE_NAME=BINARY r.table_name AND BINARY c.COLUMN_NAME=BINARY r.column_name
    WHERE c.COLUMN_NAME IS NULL OR c.DATA_TYPE<>r.data_type
       OR c.GENERATION_EXPRESSION<>'' OR c.EXTRA LIKE '%INVISIBLE%';
    INSERT INTO tmp_migrator_share_issues
    SELECT 'UNREVIEWED_COLUMN',CONCAT(c.TABLE_NAME,'.',c.COLUMN_NAME)
    FROM information_schema.COLUMNS c
    LEFT JOIN tmp_migrator_share_columns r ON BINARY r.table_name=BINARY c.TABLE_NAME
        AND BINARY r.column_name=BINARY c.COLUMN_NAME
    WHERE c.TABLE_SCHEMA=v_schema AND r.column_name IS NULL;
    INSERT INTO tmp_migrator_share_issues
    SELECT 'UNREVIEWED_TABLE_OR_VIEW',t.TABLE_NAME FROM information_schema.TABLES t
    WHERE t.TABLE_SCHEMA=v_schema AND (t.TABLE_TYPE<>'BASE TABLE' OR NOT EXISTS(
        SELECT 1 FROM tmp_migrator_share_columns r WHERE BINARY r.table_name=BINARY t.TABLE_NAME));
    INSERT INTO tmp_migrator_share_issues
    SELECT 'NONTRANSACTIONAL_TABLE',TABLE_NAME FROM information_schema.TABLES
    WHERE TABLE_SCHEMA=v_schema AND TABLE_TYPE='BASE TABLE' AND ENGINE<>'InnoDB';
    INSERT INTO tmp_migrator_share_issues
    SELECT 'UNREVIEWED_TRIGGER',TRIGGER_NAME FROM information_schema.TRIGGERS
    WHERE TRIGGER_SCHEMA=v_schema;
    INSERT INTO tmp_migrator_share_issues
    SELECT 'UNREVIEWED_EVENT',EVENT_NAME FROM information_schema.EVENTS
    WHERE EVENT_SCHEMA=v_schema;
    INSERT INTO tmp_migrator_share_issues
    SELECT 'UNREVIEWED_ROUTINE',ROUTINE_NAME FROM information_schema.ROUTINES
    WHERE ROUTINE_SCHEMA=v_schema AND ROUTINE_NAME<>'migrator_redact_character_share';

    SELECT reason,object_name FROM tmp_migrator_share_issues ORDER BY reason,object_name;
    SELECT COUNT(*) INTO v_issues FROM tmp_migrator_share_issues;
    IF v_issues>0 THEN
        IF v_mode<>'PREVIEW' THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT=
                'SHARE_SCHEMA_REVIEW_REQUIRED: inspect PREVIEW identifiers; no redaction was performed';
        END IF;
        SELECT 'REVIEW_REQUIRED' AS status,v_schema AS share_schema,v_issues AS schema_issues;
        LEAVE main;
    END IF;

    IF v_mode='APPLY' THEN
        START TRANSACTION;
        SET v_started=TRUE;
    END IF;
    OPEN rules;
    SET v_cursor_open=TRUE;
    rule_loop: LOOP
        FETCH rules INTO v_table,v_column,v_action;
        IF v_done THEN LEAVE rule_loop; END IF;
        SET @migrator_share_count=NULL;
        SET @migrator_share_sql=CONCAT('SELECT COUNT(*) INTO @migrator_share_count FROM `',
            v_schema,'`.`',v_table,'` WHERE `',v_column,'` IS NOT NULL AND ',
            IF(v_action='ZERO',CONCAT('`',v_column,'`<>0'),
                CONCAT('OCTET_LENGTH(`',v_column,'`)>0')));
        PREPARE share_stmt FROM @migrator_share_sql;
        SET v_prepared=TRUE;
        EXECUTE share_stmt;
        DEALLOCATE PREPARE share_stmt;
        SET v_prepared=FALSE;
        INSERT INTO tmp_migrator_share_report(table_name,column_name,action,nonempty_before)
        VALUES(v_table,v_column,v_action,@migrator_share_count);
        IF v_mode='APPLY' AND @migrator_share_count>0 THEN
            SET @migrator_share_sql=CONCAT('UPDATE `',v_schema,'`.`',v_table,'` SET `',
                v_column,'`=',IF(v_action='ZERO','0',CHAR(39,39)),
                ' WHERE `',v_column,'` IS NOT NULL AND ',
                IF(v_action='ZERO',CONCAT('`',v_column,'`<>0'),
                    CONCAT('OCTET_LENGTH(`',v_column,'`)>0')));
            PREPARE share_stmt FROM @migrator_share_sql;
            SET v_prepared=TRUE;
            EXECUTE share_stmt;
            SET v_changed=ROW_COUNT();
            DEALLOCATE PREPARE share_stmt;
            SET v_prepared=FALSE;
            UPDATE tmp_migrator_share_report SET changed_rows=v_changed
            WHERE table_name=v_table AND column_name=v_column;
        END IF;
        -- Recount even on a rerun. No success result is emitted before COMMIT.
        SET @migrator_share_sql=CONCAT('SELECT COUNT(*) INTO @migrator_share_count FROM `',
            v_schema,'`.`',v_table,'` WHERE `',v_column,'` IS NOT NULL AND ',
            IF(v_action='ZERO',CONCAT('`',v_column,'`<>0'),
                CONCAT('OCTET_LENGTH(`',v_column,'`)>0')));
        PREPARE share_stmt FROM @migrator_share_sql;
        SET v_prepared=TRUE;
        EXECUTE share_stmt;
        DEALLOCATE PREPARE share_stmt;
        SET v_prepared=FALSE;
        UPDATE tmp_migrator_share_report SET nonempty_after=@migrator_share_count
        WHERE table_name=v_table AND column_name=v_column;
    END LOOP;
    CLOSE rules;
    SET v_cursor_open=FALSE;
    SELECT COALESCE(SUM(nonempty_after),0) INTO v_issues FROM tmp_migrator_share_report;
    IF v_mode IN ('APPLY','VERIFY') AND v_issues<>0 THEN
        SELECT * FROM tmp_migrator_share_report ORDER BY table_name,column_name;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT=
            'SHARE_REDACTION_INCOMPLETE: selected fields are not empty';
    END IF;
    IF v_started THEN COMMIT; SET v_started=FALSE; END IF;
    SET @migrator_share_sql=NULL,@migrator_share_count=NULL;
    SELECT * FROM tmp_migrator_share_report ORDER BY table_name,column_name;
    SELECT CASE v_mode WHEN 'APPLY' THEN 'REDACTED' WHEN 'VERIFY' THEN 'VERIFIED'
        ELSE 'PREVIEW_ONLY' END AS status,v_schema AS share_schema,
        'tc-character-share-v1' AS policy,
        'Public names, identifiers and structured gameplay state retained' AS retained;
END//
DELIMITER ;
