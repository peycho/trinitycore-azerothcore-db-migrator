# Inspecting and preparing an old TrinityCore source

Old character records can contain real historical damage, valid native state,
and representations that the target core handles differently. These need
different decisions. A missing persisted lower spell rank is normal when TC
restores it from a known higher rank; an unreviewed spell script is not evidence
that its character row is corrupt. Do not clean the database by deleting every
row named in a migration blocker report.

Keep the original backup and an untouched restored baseline. Restore a separate
preparation copy for any reviewed changes, with matching auth, characters,
world metadata and the DBC assets used by the source core. Keep game servers
stopped against that copy. Preserve the existing migration staging databases.
This guide introduces no production or existing-staging repair command.

## Run a standalone read-only audit

Use `tools/audit-tc-source.py` from the repository checkout. It does not require
an approved migration profile, target databases or a control schema. It uses
the bundled profile's TC DBC layouts as diagnostic metadata; it cannot approve
or start a migration. A dedicated account needs **SELECT only** on the three
input schemas. Store connection credentials in a private MySQL option file.

For the first pass, audit all talent rows. Unlike migration preflight, the audit
collects multiple findings per character and does not stop at its first blocker.
Replace the example paths and schema names with the preparation copy's values:

```bash
MIGRATOR_CHECKOUT=/srv/src/trinitycore-azerothcore-db-migrator
SOURCE_AUDIT_ROOT=/secure/source-audits

audit_status=0
python3 "$MIGRATOR_CHECKOUT/tools/audit-tc-source.py" \
  --characters-schema tc_characters_prep \
  --auth-schema tc_auth_prep \
  --world-schema tc_world_snapshot \
  --tc-dbc /secure/path/tc-dbc \
  --scope talents \
  --output "$SOURCE_AUDIT_ROOT/talents-01" \
  --mysql --defaults-extra-file=/secure/path/audit-client.cnf \
  --host=127.0.0.1 --port=3306 --protocol=TCP --user=source_auditor \
  || audit_status=$?
printf 'Audit exit status: %s\n' "$audit_status"
```

Then run the same command with `--scope all` and a **new** output directory,
such as `$SOURCE_AUDIT_ROOT/full-01`. Existing output directories are refused,
so earlier evidence is retained. Each report directory is private (mode 0700;
files 0600). Connection arguments and option-file contents are not reported.
Use the metadata assets that match the source snapshot, not arbitrary client
files; a catalog mismatch can produce false invalid-ID findings.

The full scope adds spell IDs/flags and talent-history checks, skill IDs and
value/cap consistency, and reviewed reference checks across characters,
accounts, inventory, mail, pets, guilds and auctions. It also checks item/quest
template references and item instances appearing in multiple ownership roots.
It preserves recipes, quest history and character data; it does not repair them.
Large databases still require a substantial read scan. Progress is printed by
check and periodically during character-state processing.

The data checks share a `REPEATABLE READ`, read-only consistent snapshot.
Both schema inventory and DBC hashes are checked for drift. The read view is
consistent for InnoDB; missing columns/tables and non-InnoDB inputs are reported
as coverage limitations. DDL or metadata drift can invalidate the audit.
See MySQL's [consistent-read documentation](https://dev.mysql.com/doc/refman/8.4/en/innodb-consistent-read.html).
Use a stopped restored copy for review and preparation even when a read-only
live inspection would be possible.

## Read the result correctly

```bash
cat "$SOURCE_AUDIT_ROOT/talents-01/audit.json"
cat "$SOURCE_AUDIT_ROOT/talents-01/summary.tsv"
head -30 "$SOURCE_AUDIT_ROOT/talents-01/findings.tsv"
cat "$SOURCE_AUDIT_ROOT/full-01/coverage.tsv"
```

| Result | Meaning |
|---|---|
| Exit 0 | Requested checks completed without findings; this is not comprehensive native-core or migration approval. |
| Exit 1 | Requested checks completed and produced findings for review. |
| Exit 2 | Incomplete audit or coverage limitations; inspect `audit.json` and `coverage.tsv`. Never interpret skipped checks as passes. |

Reports:

- `findings.tsv`: individual keys, reason codes, classifications and numeric
  evidence. Multiple findings can describe the same row; counts are findings,
  not necessarily distinct characters or removable rows.
- `summary.tsv`: counts by classification and reason.
- `cleanup-review.tsv`: grouped review work; it grants no deletion permission.
- `coverage.tsv`: checks performed and missing native tables/columns.
- `schema-inventory.tsv`: visible table types, engines, columns and keys.
- `audit-queries.sql`: the actual read-only audit statements, not repair SQL.
- `audit.json`: status, scope, server identity, input row counts, DBC/profile/tool
  fingerprints and the audited-result digest. That digest covers selected
  audit results, not every byte of the database or a backup.
- `SHA256SUMS`: checksums for the retained report files.

Verify retained evidence with:

```bash
(cd "$SOURCE_AUDIT_ROOT/talents-01" && sha256sum --check SHA256SUMS)
```

The tool is a logical character-data audit, not a disk-corruption check, schema
upgrade engine or exhaustive validator of every custom/serialized field. It
does not validate talent-point budgets, every talent prerequisite or every
configured skill cap. Matching the supplied metadata is necessary evidence,
not proof that a character is healthy. Keep the migration's schema,
representation, serialized-data and native-gameplay gates.

## Decide what can be prepared

| Finding | Preparation policy |
|---|---|
| Talent value is not a rank spell | Confirm against the actual source Talent DBC and TC loader. Review exact rows for full-row archive/removal. Never reinterpret the number as a talent-entry ID and guess its rank. |
| Wrong-class, out-of-range-group or conflicting talent selections | Review original history and native behavior. Preserve valid selections; do not choose a replacement spec or rank automatically. |
| Disabled unowned talent spell | Historical state requiring a representation decision. Do not activate it in AC or bulk-delete it as corruption. |
| Highest-rank-only spellbook or superseded inactive ordinary rank | Normal TC persistence can explain it. Retain it for the migration's semantic reconstruction. |
| Unknown spell or skill | Verify the matching world/DBC/custom data first. Custom definitions or snapshot mismatches may explain it. |
| Skill value exceeds cap or profession/riding mismatch | Review native skill state and configuration. Do not raise caps, reduce values, change profession slots or remove recipes automatically. |
| Missing parent or duplicated item placement | Establish the exact valid owner and all inventory/mail/guild/auction roots. Do not delete an item simply because its recorded character owner is absent. |
| Missing item/quest template | Review matching source-world data, retained custom definitions and historical content. Do not erase quest history or items in bulk. |
| Migration-only script, correction or chain guard | Fix/review compatibility coverage in the migrator. This is not a source-cleanup instruction. |

The existing `tools/cleanup-staging-source.sql` describes one older reviewed
dataset. Its hard-coded IDs and counts are not a general database cleaner.
Do not reuse it against another snapshot or adapt it by broadening predicates.
Do not enable `CleanCharacterDB`, mass-reset talents/skills, delete all
disabled/inactive spells, or mass-login characters as a substitute for review.

## Apply only a reviewed, reversible preparation batch

For each accepted cleanup category, prepare a dataset-specific SQL transaction
**and its restore transaction** before applying either. The batch must:

1. Identify the exact preparation schema, original backup and audit hashes.
2. Capture full original rows, including custom columns, under a unique batch
   ID in a separate owned archive. Record the reason and metadata hashes.
3. Guard each change by the complete reviewed key and original values. Refuse
   changed rows, unexpected counts or preexisting archive ownership conflicts.
4. Archive and change rows atomically. Test rollback, repeat execution and the
   exact inverse on a disposable copy before use on the preparation database.
5. Demonstrate preserved valid talents/points, spell availability, skills/caps,
   profession slots, recipes, item placement and unrelated data.

An audit finding is not approval for such a batch. The repository currently
provides the read-only inspector and review workflow, not a generic repair
applicator. After reviewing actual output, write a narrow batch for confirmed
records rather than guessing a rule from the first error message.

Repeat both audit scopes after preparation, comparing against the untouched
baseline and retained archive. Feed the prepared source into a **new migration
run with fresh target/control schemas**; never resume checkpoints captured
before source edits. The [migration guide](migration-guide.md) and
[spell reconstruction gates](spell-reconstruction.md) remain mandatory.
Database `READY` and a clean audit do not approve production cutover. The
compatibility profile remains `UNREVIEWED` until its acceptance gates pass.
