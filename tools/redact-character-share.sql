-- Clear private content in a DISPOSABLE TrinityCore characters sharing copy.
-- Run: mysql --skip-force chars_share < tools/redact-character-share.sql
-- Keep all writers stopped. Do not run on production or your cleaned migration copy.
-- Stock TC 92127cd6252edb96fbfa36540db0eba17d0031fa; custom fields are untouched.
-- Uses the database selected by mysql; no database, procedure or archive is created.
-- On error, mysql --skip-force exits and disconnect rollback undoes earlier updates
-- for InnoDB tables. Do not use --force or run this inside an existing transaction.

START TRANSACTION;

-- Channel passwords, private correspondence and written item text.
UPDATE channels SET password = '' WHERE password IS NOT NULL;
UPDATE mail SET subject = IF(subject IS NULL, NULL, ''), body = IF(body IS NULL, NULL, '');
UPDATE item_instance SET text = '' WHERE text IS NOT NULL;

-- Friend, staff and guild notes; retain all membership and relationship rows.
UPDATE character_social SET note = '';
UPDATE character_banned SET bannedby = '', banreason = '';
UPDATE guild SET info = '', motd = '';
UPDATE guild_member SET pnote = '', offnote = '';
UPDATE guild_bank_tab SET TabName = '', TabIcon = '', TabText = IF(TabText IS NULL, NULL, '');
UPDATE guild_rank SET rname = '';

-- Calendar, support tickets, surveys and bug reports.
UPDATE calendar_events SET title = '', description = '';
UPDATE calendar_invites SET text = '';
UPDATE gm_ticket SET description = '', comment = '', response = '';
UPDATE gm_survey SET comment = '';
UPDATE gm_subsurvey SET answerComment = '';
UPDATE bugreport SET type = '', content = '';

-- Client caches may contain macros. Keep their keys, empty data and reset cache time.
UPDATE account_data SET data = '', time = 0;
UPDATE character_account_data SET data = '', time = 0;

-- Other editable labels/comments; names and structured gameplay fields stay intact.
UPDATE character_equipmentsets SET name = '', iconname = '';
UPDATE worldstates SET comment = '' WHERE comment IS NOT NULL;

COMMIT;
SELECT 'Character sharing copy redacted' AS result;
