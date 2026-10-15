-- Read-only follow-up for itemEntry=0 instances referenced as inventory bags.
-- Run against a stopped preparation copy with SELECT-only credentials.
-- Replace trinity_characters in a copy if the preparation schema differs.
-- Reports references, not proof of a valid bag, ownership or safe deletion.
-- An absent character/item remains visible; no replacement item entry is inferred.

SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;

SELECT
    contents.bag AS container_guid,
    container.owner_guid AS recorded_container_owner,
    contents.guid AS inventory_character_guid,
    (c.guid IS NOT NULL) AS inventory_character_exists,
    contents.slot AS content_slot,
    contents.item AS contained_item_guid,
    (i.guid IS NOT NULL) AS contained_item_exists,
    i.itemEntry AS contained_item_entry
FROM trinity_characters.character_inventory contents
JOIN trinity_characters.item_instance container
    ON container.guid=contents.bag
LEFT JOIN trinity_characters.characters c ON c.guid=contents.guid
LEFT JOIN trinity_characters.item_instance i ON i.guid=contents.item
WHERE contents.bag<>0 AND container.itemEntry=0
ORDER BY contents.bag,contents.guid,contents.slot,contents.item;

ROLLBACK;
