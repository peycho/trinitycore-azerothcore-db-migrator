-- Reviewed TrinityCore -> AzerothCore staging-source cleanup.
-- Keep the original production dump. Apply only to the stopped staging clone.
-- Run in an interactive MySQL session:
--   SOURCE tools/cleanup-staging-source.sql;
-- Check the three affected-row counts before issuing COMMIT or ROLLBACK.
-- This leaves the transaction open for that decision.
-- If these rows were already cleaned, no further cleanup is needed.

USE `trinity_characters`;
START TRANSACTION;

-- Native AzerothCore auction-win flags; retain mail and its attachment.
UPDATE `mail`
SET `checked` = 4
WHERE `checked` = 1092
  AND `messageType` = 2 AND `stationery` = 62
  AND `id` IN (
    6108840,6108842,6109002,6109003,6109004,6109005,
    6109007,6109091,6109207,6109232,6109233
  );
SELECT ROW_COUNT() AS updated_auction_mails; -- Expect 11

-- Native AC GM-mail behavior; the original TC NOT_RETURNABLE flag is omitted.
UPDATE `mail`
SET `checked` = 0
WHERE `checked` = 512
  AND `messageType` = 0 AND `stationery` = 61
  AND `id` IN (6109033,6109263);
SELECT ROW_COUNT() AS updated_gm_mails; -- Expect 2

-- Approved re-castable effects; remove only the four reviewed aura records.
DELETE FROM `character_aura`
WHERE `casterGuid` = 0 AND `itemGuid` = 0 AND `effectMask` = 1
  AND (`guid`, `spell`) IN (
    (188774,45102),
    (266254,19727),
    (266282,38096),
    (267172,38096)
  );
SELECT ROW_COUNT() AS removed_auras; -- Expect 4

-- If the counts are 11, 2, and 4:
-- COMMIT;
-- Otherwise:
-- ROLLBACK;
