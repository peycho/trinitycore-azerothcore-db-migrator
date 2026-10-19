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

For repeated cleanup from the Linux shell, use the
[cleanup console guide](cleanup-console.md). It wraps the audit and reviewed
talent/item/skill policies and scoped pending native resets with one private config file, per-import sessions, archived
originals, execution/error reports and guarded apply/restore commands. The raw
audit command below remains available for standalone inspection.

After a full audit, `python3 console inspect-spell-history` produces a read-only
review of direct talent history against both talent groups, using the existing
config and retained audit. It separates other selected ranks, disabled history,
enabled conflicts and pending native resets. It creates no deletion batch;
see the [console history review](cleanup-console.md#review-direct-talent-spell-history).
The subsequent [disabled-history archive policy](cleanup-console.md#archive-eligible-disabled-direct-talent-history)
can generate a candidate for eligible disabled direct ranks. It excludes selected
families, enabled conflicts and alternate/dependent learning routes, archives
complete affected state and supports exact restoration. It does not delete every
history finding or change migration reconstruction rules.
Its explicit `--include-reviewed-scripts` mode accepts only families whose every
effective TC binding has the protected `NO_SPELLBOOK_MUTATION` contract. Other
learning-route, dependency, skill and ownership exclusions still apply. After
an earlier cleanup, use a new audit/inspection and retain the earlier archives.
The separate `--include-inert-relations` v3 mode can also archive disabled trained
ranks and learned/prerequisite dependants in an isolated group. It defers a whole
character/family group if any related spell is enabled, a talent is selected,
another route reaches it, or metadata/skills/scripts cannot be reviewed safely.
Its manifest separates direct roots from related rows and reports every absent
rank as no grant. Review that wider exact selection before prepare/apply.
The explicit `--include-reviewed-routes` mode adds exact Berserk/Blast Wave
teaching-wrapper contracts and a shaman-only, single-rank `30798` history rule.
It preserves shared Dual Wield spell `674` and all skill `118` state; preserved
ownership problems still require separate migration review. `--audit AUDIT_ID`
can create a fresh sealed inspection during planning, using the retained full
audit without another full scan or migration preflight.
For disabled direct ranks where another rank is selected, the separate
`--selected-rank-history` v5 policy uses existing selections in both groups as
authority. It removes only eligible unselected disabled ranks, preserves selected
spell flags and all ownership/point/skill state, and records missing counterparts
without granting them. Enabled unselected siblings, learning/skill dependencies,
ambiguous metadata and pending resets defer cleanup. Review
`selected-rank-review.tsv` and exclusions; do not combine this mode with the
earlier policy flags. Native loading of retained builds still needs acceptance.
For disabled trained talent abilities whose direct roots are absent, v6 uses
`--migration-inspection` with a sealed blocker context. It reviews wholly disabled
rank/dependency groups against both existing talent builds and all learning/skill
routes, then rechecks the entire captured semantic scope live. See the
[history policies](cleanup-console.md#archive-eligible-disabled-direct-talent-history).
Absent roots are not granted; selected families, enabled related rows and pending
resets remain deferred. Complete affected originals are archived before apply.

## Run a standalone read-only audit

For private reproduction outside your environment, use the separate
[character snapshot redaction procedure](sharing-character-snapshot.md).
It clears channel passwords, mail/support text, notes and client caches only in
a disposable `_share` copy. It preserves migration-relevant rows and reports
unreviewed custom fields; it does not replace the audit/cleanup process below.

If migration preflight remains blocked across multiple spell categories, use
the [saved blocker context command](cleanup-console.md#review-a-saved-migration-blocker-report)
to collect complete spell/talent/skill state for every reported character in one
read-only inspection. It retains TC world inputs and DBC fingerprints alongside
the report, without making a cleanup selection. Do not infer migration readiness
from a falling source-audit count or treat compatibility gaps as corrupt rows.

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
| Skill value exceeds cap or profession/riding mismatch | Review native skill state and configuration. Preserve by default. An explicitly approved [skill clamp](cleanup-console.md#clamp-explicitly-reviewed-over-cap-skills) reduces only audited values to existing positive caps, with full originals and exact restore; it never chooses higher caps, changes profession slots or removes recipes. |
| Missing parent or duplicated item placement | Establish the exact valid owner and all inventory/mail/guild/auction roots. Do not delete an item simply because its recorded character owner is absent. |
| Missing item template | Preserve item instances by default, including custom items absent from client DBCs or the supplied world templates. Report for review; template absence alone does not authorize removal. |
| Missing quest template | Review matching source-world data, retained custom definitions and historical content. Do not erase quest history in bulk. |
| Migration-only script, correction or chain guard | Fix/review compatibility coverage in the migrator. This is not a source-cleanup instruction. |

Custom items need not appear in client DBCs. The audit's
`ITEM_TEMPLATE_MISSING` finding compares `item_instance.itemEntry` against the
supplied source world's `item_template.entry`, not an item DBC. It is a
`REVIEW` finding, not a cleanup requirement. Entry `0` remains visible for
review and is not automatically changed or removed. Investigate independently
invalid ownership or placement under the separate reference policy above;
missing templates alone must not decide an item's fate.

For zero-entry instances referenced as containers by `character_inventory.bag`,
use the read-only [container inspection](../tools/inspect-zero-entry-containers.sql)
on the preparation copy. It lists contained-item references and whether their
characters and item instances exist, including dangling references. Preserve
these contents while investigating; a container GUID does not establish its
original item entry, bag capacity or a safe replacement placement.

In both pinned cores, inventory loading handles a missing container differently
from an item that fails an equipment or storage check. If the container cannot
be found in the loaded bag maps, the loader deletes the contained item's
inventory reference and continues without adding it to the recovery-mail
queue. The item instance is not deleted by that branch, but its inventory
placement is lost. Do not assume login will mail these contents back. Any
separately reviewed recovery must preserve the existing item GUIDs, quantities
and attributes, archive original placements and provide an exact rollback.

Preserving a character-database item row does not make it usable in the target
core. Both reviewed cores delete inventory items on load when their runtime
item template is missing. Retained custom items therefore need compatible
target-world definitions to survive that load; otherwise native removal can
occur after login. Source preparation and migration do not need to pre-delete
these items or trigger logins to clean them. Changes to custom world definitions
remain a separate reviewed task; the migrator keeps world schemas read-only.

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

An audit finding is not approval for such a batch. For verified non-rank talent
values, use the [invalid talent planner](talent-cleanup.md) to generate narrow,
reviewable archive/apply/restore SQL from the exact audit keys. The planner is
offline and never connects to a database. It supports only that reason code;
other categories still need their own reviewed policies and batches. This is
not a generic database cleaner.

Repeat both audit scopes after preparation, comparing against the untouched
baseline and retained archive. Feed the prepared source into a **new migration
run with fresh target/control schemas**; never resume checkpoints captured
before source edits. The [migration guide](migration-guide.md) and
[spell reconstruction gates](spell-reconstruction.md) remain mandatory.
Database `READY` and a clean audit do not approve production cutover. The
compatibility profile remains `UNREVIEWED` until its acceptance gates pass.
