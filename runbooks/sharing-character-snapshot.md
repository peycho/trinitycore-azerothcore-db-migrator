# Share a redacted character snapshot

Restore a fresh production character dump into a separate disposable database,
clear private content, then export it. Keep your existing cleaned preparation
copy and cleanup archives. Keep game servers and other writers stopped against
this sharing copy. Its contents remain private diagnostic evidence, outside Git.

With an empty `chars_share` database already created, run from the toolkit checkout:

```bash
mysql --skip-force chars_share < prod_chars.sql &&
mysql --skip-force chars_share < tools/redact-character-share.sql &&
mysqldump --single-transaction --quick --hex-blob --no-tablespaces \
  --set-gtid-purged=OFF --skip-triggers --skip-routines --skip-events \
  chars_share > chars_share.sql
```

Use your usual MySQL connection settings on each command. For a private client
file, put `--defaults-extra-file=/path/to/client.cnf` immediately after `mysql`
or `mysqldump`. The input dump should contain tables only, without CREATE
DATABASE/USE statements that would redirect the import to another database.
The `&&` operators stop the sequence if import or cleanup fails. A failed dump
can leave a partial file; share it only when mysqldump exits successfully.

[`tools/redact-character-share.sql`](../tools/redact-character-share.sql) is a
plain SQL transaction. It creates no procedures, databases, archives or approval
records. There is no required database-name suffix, preview mode or confirmation
parameter. The two UPDATE/import commands use `--skip-force` so an SQL error
stops the client; disconnect then rolls back uncommitted InnoDB updates. Do not
use `--force`, an interactive `SOURCE`, or nontransactional tables for cleanup.

It clears 32 fields in the reviewed TC character schema:

- Channel passwords; mail subjects/bodies; written item text.
- Friend, guild and officer notes; ban-author/reason text.
- Guild descriptions, bank-tab labels/text and rank labels.
- Calendar text, GM tickets/surveys, bug reports and administrative comments.
- Client settings/macros and their cache timestamps; equipment-set labels/icons.

Names, rows, IDs, relationships, spells/flags, talents, skills/caps, quests,
items/enchantments and mail attachments remain. Existing NULL values remain NULL.
The script can be rerun. To undo it, restore your private original into a new copy.
A fresh production snapshot contains the old migration blockers again; this
redaction clears sensitive content, not gameplay data or migration blockers.

**Custom tables and columns are left untouched.** Review those separately for
private content before sharing; omit unrelated custom tables with mysqldump's
`--ignore-table=chars_share.table_name` option. Stored code is excluded by the
export flags above; if this copy has custom triggers that alter updates, review
or remove them before running cleanup. Retained names, GUIDs, history, serialized
state and schema comments/defaults are not anonymized. This is targeted stock
content redaction, not a guarantee that arbitrary custom data contains no secrets.
No auth dump, credentials, private original dump or cleanup archives are needed.

Validation uses synthetic data on disposable MySQL 8.4. It checks every retained
stock column across 91 tables, custom-data preservation, late-error rollback,
reruns and actual dump/restore. Run it on a dedicated disposable server:

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 REHEARSAL_MYSQL_PORT=33317 \
  python3 tests/character-share-mysql-tests.py
```

This standalone sharing helper does not change the migration or cleanup-console
policies. Compatibility-profile approval remains UNREVIEWED.
