INSERT INTO `characters` (`guid`,`account`,`name`,`taximask`,`online`)
VALUES (100,1,'Migrator','',1),(101,2,'Signer','',0);

INSERT INTO `item_instance`
    (`guid`,`itemEntry`,`owner_guid`,`count`,`enchantments`)
VALUES
    (200,6948,100,1,''),
    (201,20815,100,1,'');

INSERT INTO `character_inventory` (`guid`,`bag`,`slot`,`item`)
VALUES (100,0,23,200);

INSERT INTO `item_loot_items`
    (`container_id`,`item_id`,`item_count`,`item_index`,`rnd_prop`,`rnd_suffix`)
VALUES (201,2589,2,0,0,0);

INSERT INTO `item_loot_money` (`container_id`,`money`)
VALUES (201,12345);

INSERT INTO `character_spell` (`guid`,`spell`,`active`,`disabled`)
VALUES (100,6603,1,0);

INSERT INTO `character_talent` (`guid`,`spell`,`talentGroup`)
VALUES (100,12282,0),(100,12282,1);

INSERT INTO `character_spell_cooldown`
    (`guid`,`spell`,`item`,`time`,`categoryId`,`categoryEnd`)
VALUES (100,8690,0,2000000000,1,2000000100);

INSERT INTO `pet_spell_cooldown`
    (`guid`,`spell`,`time`,`categoryId`,`categoryEnd`)
VALUES (300,17253,2000000000,2,2000000200);

INSERT INTO `instance`
    (`id`,`map`,`resettime`,`difficulty`,`completedEncounters`,`data`)
VALUES (400,33,2000000000,0,0,'');

INSERT INTO `character_instance`
    (`guid`,`instance`,`permanent`,`extendState`)
VALUES (100,400,1,2);

INSERT INTO `character_battleground_data`
    (`guid`,`instanceId`,`team`,`joinX`,`joinY`,`joinZ`,`joinO`,`joinMapId`,
     `taxiStart`,`taxiEnd`,`mountSpell`)
VALUES (100,0,0,1,2,3,4,0,0,0,0);

INSERT INTO `channels`
    (`name`,`team`,`announce`,`ownership`,`password`,`bannedList`,`lastUsed`)
VALUES ('Migration',0,1,1,NULL,'100 ',2000000000);

INSERT INTO `character_arena_stats` (`guid`,`slot`,`matchMakerRating`)
VALUES (100,0,1500);

INSERT INTO `gm_survey` (`surveyId`,`guid`,`mainSurvey`,`comment`,`createTime`)
VALUES (1,100,0,'migration fixture',2000000000);

INSERT INTO `petition` (`ownerguid`,`petitionguid`,`name`,`type`)
VALUES (100,500,'Migration Guild',9);

INSERT INTO `petition_sign`
    (`ownerguid`,`petitionguid`,`playerguid`,`player_account`,`type`)
VALUES (100,500,101,2,9);
