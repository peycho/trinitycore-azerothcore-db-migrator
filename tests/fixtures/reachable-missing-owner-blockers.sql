-- Apply to a target clone after load-characters and before sanitize-target.
-- Each row has a missing owner but remains reachable through a supported root;
-- sanitization must stop and report the corresponding root_mask.
INSERT INTO `item_instance`
    (`guid`,`itemEntry`,`owner_guid`,`count`,`enchantments`)
VALUES
    (979,6948,100,1,''), -- valid item stored inside the missing-owner bag
    (980,6948,999,1,''), -- inventory item: mask 1
    (981,6948,999,1,''), -- inventory bag: mask 2
    (982,6948,999,1,''), -- valid mail: mask 4
    (983,6948,999,1,''), -- auction: mask 8
    (984,6948,999,1,''); -- guild bank: mask 16

INSERT INTO `character_inventory` (`guid`,`bag`,`slot`,`item`)
VALUES (100,0,24,980),(100,981,0,979);

INSERT INTO `mail`
    (`id`,`sender`,`receiver`,`subject`,`body`,`has_items`)
VALUES (985,100,100,'root fixture','root fixture',1);
INSERT INTO `mail_items` (`mail_id`,`item_guid`,`receiver`)
VALUES (985,982,100);

INSERT INTO `auctionhouse` (`id`,`itemguid`,`itemowner`)
VALUES (986,983,100);

INSERT INTO `guild_bank_item` (`guildid`,`TabId`,`SlotId`,`item_guid`)
VALUES (940,0,0,984);
