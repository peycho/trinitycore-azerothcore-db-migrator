-- Read-only follow-up for the custom transmog/enchant columns seen in source samples.
-- These are separate from the stock enchantments column.

SELECT TABLE_SCHEMA, COLUMN_NAME, COLUMN_TYPE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA IN ('trinity_characters','acore_characters')
  AND TABLE_NAME='item_instance'
  AND COLUMN_NAME IN ('transmog','enchant','enchantments')
ORDER BY TABLE_SCHEMA, ORDINAL_POSITION;

-- Check the entire source, separating removed from retained item instances.
-- Compare textual zero so unexpected nonnumeric custom values are also counted.
SELECT
    CASE WHEN t.guid IS NULL THEN 'Removed' ELSE 'Retained' END AS item_state,
    COUNT(*) AS item_instances,
    SUM(i.transmog IS NOT NULL AND CAST(i.transmog AS CHAR)<>'0') AS transmog_nonzero,
    SUM(i.enchant IS NOT NULL AND CAST(i.enchant AS CHAR)<>'0') AS enchant_nonzero
FROM trinity_characters.item_instance i
LEFT JOIN acore_characters.item_instance t ON t.guid=i.guid
GROUP BY item_state;
