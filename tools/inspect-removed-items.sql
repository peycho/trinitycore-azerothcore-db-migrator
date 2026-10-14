-- Read-only inspection: one complete source item instance per removed item type.
-- Run before target worldserver writes change the source/target comparison:
--   SOURCE tools/inspect-removed-items.sql;
-- MIN(guid) selects a reproducible sample; this is not a random sample.
-- Output includes player-generated item text; retain it privately.

WITH removed_types AS (
    SELECT
        i.itemEntry,
        MIN(i.guid) AS sample_guid,
        COUNT(*) AS removed_instances,
        SUM(i.`count`) AS removed_quantity
    FROM trinity_characters.item_instance i
    LEFT JOIN acore_characters.item_instance t ON t.guid=i.guid
    WHERE t.guid IS NULL
    GROUP BY i.itemEntry
), bag_refs AS (
    -- bag has no dedicated index: aggregate each inventory once rather than
    -- running one full inventory scan for every sampled item.
    SELECT ci.bag AS item_guid, 'SOURCE' AS side
    FROM trinity_characters.character_inventory ci
    JOIN removed_types r ON r.sample_guid=ci.bag
    WHERE ci.bag<>0
    UNION ALL
    SELECT ci.bag AS item_guid, 'TARGET' AS side
    FROM acore_characters.character_inventory ci
    JOIN removed_types r ON r.sample_guid=ci.bag
    WHERE ci.bag<>0
), bag_counts AS (
    SELECT item_guid,
           SUM(side='SOURCE') AS source_bag_refs,
           SUM(side='TARGET') AS target_bag_refs
    FROM bag_refs
    GROUP BY item_guid
)
SELECT
    r.removed_instances,
    r.removed_quantity,
    w.name AS item_name,
    (sc.guid IS NOT NULL) AS owner_in_source,
    (tc.guid IS NOT NULL) AS owner_in_target,
    (sa.id IS NOT NULL) AS owner_account_in_source,
    EXISTS(
        SELECT 1 FROM trinity_characters.character_inventory ci
        WHERE ci.item=i.guid
    ) AS source_inventory_ref,
    EXISTS(
        SELECT 1 FROM trinity_characters.character_inventory ci
        JOIN trinity_characters.characters c ON c.guid=ci.guid
        WHERE ci.item=i.guid
    ) AS source_inventory_character_exists,
    COALESCE(b.source_bag_refs,0) AS source_bag_refs,
    EXISTS(
        SELECT 1 FROM trinity_characters.mail_items mi
        WHERE mi.item_guid=i.guid
    ) AS source_mail_link,
    EXISTS(
        SELECT 1 FROM trinity_characters.mail_items mi
        JOIN trinity_characters.mail m ON m.id=mi.mail_id
        WHERE mi.item_guid=i.guid
    ) AS source_mail_exists,
    EXISTS(
        SELECT 1 FROM trinity_characters.auctionhouse a
        WHERE a.itemguid=i.guid
    ) AS source_auction_ref,
    EXISTS(
        SELECT 1 FROM trinity_characters.guild_bank_item g
        WHERE g.item_guid=i.guid
    ) AS source_guild_bank_ref,
    EXISTS(
        SELECT 1 FROM acore_characters.character_inventory ci
        WHERE ci.item=i.guid
    ) AS target_inventory_ref,
    COALESCE(b.target_bag_refs,0) AS target_bag_refs,
    EXISTS(
        SELECT 1 FROM acore_characters.mail_items mi
        JOIN acore_characters.mail m ON m.id=mi.mail_id
        WHERE mi.item_guid=i.guid
    ) AS target_mail_ref,
    EXISTS(
        SELECT 1 FROM acore_characters.auctionhouse a
        WHERE a.itemguid=i.guid
    ) AS target_auction_ref,
    EXISTS(
        SELECT 1 FROM acore_characters.guild_bank_item g
        WHERE g.item_guid=i.guid
    ) AS target_guild_bank_ref,
    i.*
FROM removed_types r
JOIN trinity_characters.item_instance i ON i.guid=r.sample_guid
LEFT JOIN trinity_world.item_template w ON w.entry=i.itemEntry
LEFT JOIN trinity_characters.characters sc ON sc.guid=i.owner_guid
LEFT JOIN acore_characters.characters tc ON tc.guid=i.owner_guid
LEFT JOIN trinity_auth.account sa ON sa.id=sc.account
LEFT JOIN bag_counts b ON b.item_guid=i.guid
ORDER BY r.removed_instances DESC, i.itemEntry;

-- For a smaller first review, add LIMIT 20 before the final semicolon.
-- All target_*_ref fields and owner_in_target should be zero for these samples.
-- Source references can survive to a missing character or mail header; inspect
-- source_inventory_character_exists and source_mail_exists before interpreting them.
