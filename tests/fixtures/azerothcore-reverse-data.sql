-- Apply to a disposable native AzerothCore characters schema.
INSERT INTO `character_talent` (`guid`,`spell`,`specMask`)
VALUES (100,12282,1),(100,12301,2);

INSERT INTO `character_spell` (`guid`,`spell`,`specMask`)
VALUES (100,6603,3);

INSERT INTO `character_spell_cooldown`
    (`guid`,`spell`,`category`,`item`,`time`,`needSend`)
VALUES (100,8690,1,0,2000000100,1);

INSERT INTO `pet_spell_cooldown` (`guid`,`spell`,`category`,`time`)
VALUES (300,17253,2,2000000200);

INSERT INTO `item_loot_storage`
    (`containerGUID`,`itemid`,`count`,`item_index`,`randomPropertyId`,
     `randomSuffix`,`follow_loot_rules`,`freeforall`,`is_blocked`,`is_counted`,
     `is_underthreshold`,`needs_quest`,`conditionLootId`)
VALUES
    (201,2589,2,0,0,0,0,0,0,0,0,0,0),
    (201,0,12345,0,0,0,0,0,0,0,0,0,0);

INSERT INTO `channels`
    (`channelId`,`name`,`team`,`announce`,`ownership`,`password`,`lastUsed`)
VALUES (1,'ReverseMigration',0,1,1,NULL,2000000000);
INSERT INTO `channels_bans` (`channelId`,`playerGUID`,`banTime`)
VALUES (1,100,2000000000),(1,101,4294967295);

INSERT INTO `creature_respawn`
    (`guid`,`respawnTime`,`mapId`,`instanceId`)
VALUES (700,2000000000,0,0);
INSERT INTO `gameobject_respawn`
    (`guid`,`respawnTime`,`mapId`,`instanceId`)
VALUES (701,2000000100,0,0);
-- The disposable world fixture must contain creature 700 and gameobject 701
-- on map 0 before an ac-to-tc load is expected to accept these rows.

-- Must be archived before loading because TrinityCore has no equivalent.
INSERT INTO `character_settings` (`guid`,`source`,`data`)
VALUES (100,'migration-fixture','{"enabled":true}');
