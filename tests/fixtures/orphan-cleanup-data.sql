-- Apply after auth-data.sql and characters-data.sql. Account 999 deliberately
-- does not exist. None of these characters is an organization leader.
INSERT INTO `characters` (`guid`,`account`,`name`,`taximask`,`online`)
VALUES (900,999,'Orphaned','',0);
UPDATE `characters` SET race=1,class=1,level=80 WHERE guid=900;

INSERT INTO `character_spell` (`guid`,`spell`,`active`,`disabled`)
VALUES (900,6603,1,0);

INSERT INTO `character_pet` (`id`,`entry`,`owner`,`name`)
VALUES (930,1,900,'OrphanPet');
INSERT INTO `pet_spell` (`guid`,`spell`,`active`)
VALUES (930,1,1);

INSERT INTO `guild` (`guildid`,`name`,`leaderguid`)
VALUES (940,'Cleanup Guild',100);
INSERT INTO `guild_member` (`guildid`,`guid`,`rank`)
VALUES (940,100,0),(940,900,1);

INSERT INTO `groups`
    (`guid`,`leaderGuid`,`lootMethod`,`looterGuid`,`lootThreshold`,
     `icon1`,`icon2`,`icon3`,`icon4`,`icon5`,`icon6`,`icon7`,`icon8`,
     `groupType`,`masterLooterGuid`)
VALUES (950,100,0,900,2,0,0,0,0,0,0,0,0,0,900);
INSERT INTO `group_member` (`guid`,`memberGuid`)
VALUES (950,100),(950,900);

INSERT INTO `arena_team` (`arenaTeamId`,`name`,`captainGuid`,`type`)
VALUES (960,'Cleanup Arena',100,2);
INSERT INTO `arena_team_member` (`arenaTeamId`,`guid`)
VALUES (960,100),(960,900);

INSERT INTO `item_instance`
    (`guid`,`itemEntry`,`owner_guid`,`count`,`enchantments`)
VALUES
    (901,6948,900,1,''),
    (902,6948,900,1,'');
INSERT INTO `character_inventory` (`guid`,`bag`,`slot`,`item`)
VALUES (900,0,23,902);
INSERT INTO `item_loot_money` (`container_id`,`money`)
VALUES (901,1);

INSERT INTO `mail`
    (`id`,`sender`,`receiver`,`subject`,`body`,`has_items`)
VALUES (970,900,100,'cleanup','cleanup',0);

