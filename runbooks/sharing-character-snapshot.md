# Redact a private character snapshot for investigation

Use this when sharing a TrinityCore characters dump for migration debugging.
The dump is private diagnostic evidence, not repository content or a production
migration source. Names can remain public while mail, channel passwords and
other free text are removed. This is content redaction, not anonymization:
character/account GUIDs, relationships, timestamps, names and gameplay history
remain identifiable.

Keep the existing cleaned preparation copy, its toolkit, sessions and cleanup
archives. Restore a **separate disposable sharing copy**, with all game servers
and other writers stopped against it. A new production snapshot contains the
old blockers again; redaction does not replay talent/item/skill cleanup or fix
migration blockers. That is useful for reproduction. Never apply old sealed
cleanup batches to a fresh import; new cleanup work needs a new session/audit.

## Scope

[`tools/redact-character-share.sql`](../tools/redact-character-share.sql) creates
`migrator_redact_character_share(mode, acknowledgement)` in the selected schema.
It is independent of the migrator and cleanup console and never changes profile
approval. Its policy, `tc-character-share-v1`, inventories all 91 tables and 677
columns in the pinned TC `92127cd6252edb96fbfa36540db0eba17d0031fa` character schema.
It requires MySQL 8.4 and a database name ending in `_share`.

| Cleared content | Fields |
| --- | --- |
| Channel secrets | `channels.password` |
| Mail and written items | `mail.subject`, `mail.body`, `item_instance.text` |
| Player and staff notes | `character_social.note`, `guild_member.pnote/offnote`, `character_banned.bannedby/banreason` |
| Guild text and labels | `guild.info/motd`, `guild_bank_tab.TabName/TabIcon/TabText`, `guild_rank.rname` |
| Calendar text | `calendar_events.title/description`, `calendar_invites.text` |
| GM support and reports | `gm_ticket.description/comment/response`, `gm_survey.comment`, `gm_subsurvey.answerComment`, `bugreport.type/content` |
| Client caches, including macros | `account_data.data`, `character_account_data.data`; their cache `time` is reset to zero |
| Other editable labels | `character_equipmentsets.name/iconname`, `worldstates.comment` |

Only these 32 fields change. Nullable fields stay NULL where already NULL; other
selected text/blob content becomes empty. All rows, keys, links and nonselected
fields remain. In particular: character/pet/guild/arena/channel names, accounts,
deleted-character metadata, spell flags, both talent groups, pending reset flags,
skills/caps, professions, riding, quests/reward history, items/enchantments,
inventory, mail attachments, guild ranks, bans and channel banned GUIDs remain.
Structured strings such as taxi masks, explored zones, pet actions, instance
state and allowed-player lists are retained. Empty cache content is supported by
TC `WorldSession::LoadAccountData`; caches contain client preferences/macros, not
authoritative spell/talent/skill ownership.

The procedure refuses APPLY/VERIFY if tables/columns are missing, have changed
data types, or are unreviewed; if tables are nontransactional; or if triggers,
views, events or other routines are present. PREVIEW lists object/column names,
not their values. **Custom tables/columns are never silently erased or approved.**
Exclude unrelated custom objects from the sharing copy after reviewing the list,
or obtain a specific redaction rule for fields that need to remain. Do not remove
gameplay-relevant custom data just to make verification pass. This rule also
catches numeric custom fields, which can encode addresses or other private data.

Review retained schema comments/defaults, update paths and structured/custom
payloads before sharing: a stock column name does not prove that historical or
custom contents never carried private material. The procedure does not search
for secrets inside retained gameplay serialization, remap identifiers, or certify
arbitrary custom schemas as safe to disclose.

## Run on the disposable sharing copy

Use a local administrative MySQL option file with complete metadata visibility
(including triggers, events and routines), CREATE ROUTINE/EXECUTE, CREATE
TEMPORARY TABLES, SELECT and UPDATE on this disposable schema. Do not use the read-only migrator role. Keep
the option file private; do not include it in the shared package. Run each command
as a fresh batch connection. Routine installation performs DDL; do not install
or call it inside an existing transaction. Use the same account for all steps.

Example: restore your retained character snapshot into a **new** database:

```bash
set -euo pipefail
umask 077
SHARE_CLIENT=/secure/mysql-share-client.cnf
SHARE_OUTPUT=/secure/character-share
mkdir -p "$SHARE_OUTPUT"

mysql --defaults-extra-file="$SHARE_CLIENT" --skip-force \
  -e 'CREATE DATABASE tc_characters_share CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'
gzip -dc /secure/characters-private.sql.gz | \
  mysql --defaults-extra-file="$SHARE_CLIENT" --skip-force --database=tc_characters_share
```

The input dump must contain this database's tables only, **without CREATE
DATABASE/USE statements** that redirect the restore. Inspect it locally first.
Keep the original dump private. Do not import cleanup archive schemas, auth, world
or other databases into this sharing schema. A fresh matching world snapshot is
useful separately for compatibility diagnosis; it needs its own disclosure review.

From the toolkit checkout, install the procedure once and preview:

```bash
mysql --defaults-extra-file="$SHARE_CLIENT" --skip-force --database=tc_characters_share \
  < tools/redact-character-share.sql
mysql --defaults-extra-file="$SHARE_CLIENT" --skip-force --batch --database=tc_characters_share \
  -e "CALL migrator_redact_character_share('PREVIEW','');" \
  > "$SHARE_OUTPUT/preview.tsv"
cat "$SHARE_OUTPUT/preview.tsv"
```

`PREVIEW_ONLY` lists nonempty counts for reviewed fields and changes no character
data. `REVIEW_REQUIRED` lists unknown or incompatible objects and changes no
character data. Resolve that inventory in the sharing copy before proceeding.
No raw secret value appears in the report. Do not use `--force`, which can hide
failures. Reuse the installed procedure for subsequent calls; import a fresh
copy to start over.

Apply all redactions transactionally, then verify from another connection:

```bash
mysql --defaults-extra-file="$SHARE_CLIENT" --skip-force --batch --database=tc_characters_share \
  -e "CALL migrator_redact_character_share('APPLY','DISPOSABLE_SHARE_COPY_WRITERS_STOPPED');" \
  > "$SHARE_OUTPUT/applied.tsv"
mysql --defaults-extra-file="$SHARE_CLIENT" --skip-force --batch --database=tc_characters_share \
  -e "CALL migrator_redact_character_share('VERIFY','');" \
  > "$SHARE_OUTPUT/verified.tsv"
cat "$SHARE_OUTPUT/applied.tsv" "$SHARE_OUTPUT/verified.tsv"
```

Expect `REDACTED`, then `VERIFIED`, and zero `nonempty_after` for every rule.
APPLY automatically commits only after all reviewed fields verify empty. An SQL
error rolls back its redactions and returns a failing exit status; no REDACTED
success is emitted. Repeated APPLY changes zero rows. There is deliberately no
archive of private content in the sharing database. Undo by restoring the retained
private input into another disposable sharing copy.

## Export only the redacted characters schema

Keep writers stopped through verification and export:

```bash
mysqldump --defaults-extra-file="$SHARE_CLIENT" \
  --single-transaction --quick --hex-blob --no-tablespaces \
  --set-gtid-purged=OFF --skip-routines --skip-events --skip-triggers \
  tc_characters_share | gzip > "$SHARE_OUTPUT/characters-redacted.sql.gz.partial"
mv "$SHARE_OUTPUT/characters-redacted.sql.gz.partial" "$SHARE_OUTPUT/characters-redacted.sql.gz"
gzip -t "$SHARE_OUTPUT/characters-redacted.sql.gz"
sha256sum "$SHARE_OUTPUT/characters-redacted.sql.gz" > "$SHARE_OUTPUT/SHA256SUMS"
```

The shell's `set -euo pipefail` prevents a failed dump from being renamed as a
complete export. Share only `characters-redacted.sql.gz`, `SHA256SUMS` and the
redaction reports after your review. No auth dump, credentials, original dump,
cleanup archives or `--all-databases` export is needed. Excluding routines,
events and triggers also omits the helper procedure from the dump. Do not put
the dump or generated reports in Git, public issues or repository fixtures.

For an additional independent check, restore the resulting dump into a second
fresh `_share` database, install the same procedure and run VERIFY there. The
automated disposable test performs this actual dump/restore check with synthetic
secret sentinels; it does not inspect your live/staging data or establish native
gameplay acceptance.

## Local regression

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 REHEARSAL_MYSQL_PORT=33317 \
  python3 tests/character-share-mysql-tests.py
```

This requires a dedicated disposable localhost MySQL 8.4 server. It checks all
91 stock row sets and every retained column, metadata refusals, read-only modes,
acknowledgement/schema guards, late-error rollback, idempotency and dump/restore.
The full rehearsal entrypoint includes it. Profile approval remains UNREVIEWED.
