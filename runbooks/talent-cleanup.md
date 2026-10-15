# Preparing an exact invalid talent cleanup

The [cleanup console](cleanup-console.md) is the practical shell entry point:
configure paths/credentials once, then run `python3 console audit`,
`python3 console plan talents --expect-rows N`, `prepare`, `apply` and `restore`.
It retains each audit/batch under a private session and supports reviewed item
recovery and single-character pending resets. This guide documents the
underlying offline planner and SQL policies.

Use this after the [read-only source audit](source-preparation.md). The offline
`tools/plan-talent-cleanup.py` generates a private SQL package for one reason:
`INVALID / TALENT_VALUE_IS_NOT_RANK_SPELL`. It does not connect to MySQL or apply
changes. It is separate from the migrator, whose source/world boundaries remain
read-only. Apply generated SQL only to a stopped restored preparation copy,
never production or an existing migration staging target.

## What this batch changes

The reviewed TC loader (`92127cd6252edb96fbfa36540db0eba17d0031fa`)
passes stored talent spell IDs to `Player::AddTalent()`, which recognizes talent
ownership through `GetTalentSpellPos()`. TC builds that lookup from Talent DBC
rank spell IDs. A raw talent-entry ID stored in the spell column does not
establish which rank was selected. Some such numbers are legitimate ordinary
spell IDs; do not delete their character_spell records.

The planner independently checks every selected audit key against all nonzero
Talent DBC rank spell IDs. A selectable rank is never included in this batch,
even if the report is incorrectly edited and re-sealed. Only the exact audited
three-column `(guid,spell,talentGroup)` rows can be archived and removed. No
replacement talents, lower ranks or ownership are inferred.

It preserves every unselected talent row, including selectable ranks with
separate class/group conflicts. Character fields, spell flags, talent groups,
glyphs, skills/caps, profession slots, items, custom item definitions, mail and
currency receive no writes. Removing these non-rank ownership records does not
reset talents or points; native talent-point and gameplay acceptance still need
their separate checks. Disabled/unowned spell history is not silently cleaned.

## Generate the candidate without database access

Use the toolkit version matching the audit producer/layout fingerprints and
the same DBC files. Both `--scope talents` and `--scope all` audits are accepted
only when status is COMPLETE without coverage limitations. The audit's seven
reports must pass SHA256SUMS verification. The source schema/server UUID, DBC
assets, toolkit reader, layout and exact selected keys are recorded in the
candidate. Unsupported/changed producer versions require a fresh audit.

For example, replace paths and the expected count with your actual reviewed
summary count:

```bash
python3 tools/plan-talent-cleanup.py \
  --audit-dir /secure/source-audits/all-01 \
  --tc-dbc /secure/path/tc-dbc \
  --expect-rows 10685 \
  --output reports/talent-cleanup-01
```

The fresh output directory is private (0700; files 0600), and existing outputs
are refused. Never use a partial package containing `INCOMPLETE`. Each package
has its own README, manifest, selected-rows.tsv, SHA256SUMS, and:

| File | Effect |
|---|---|
| `00-setup.sql` | Creates a new owned archive and guarded procedures. Source data is unchanged. |
| `01-prepare.sql` | Snapshots full affected character rows, all their talents and exact removal rows into the archive. Source data is unchanged. |
| `02-apply.sql` | Removes only the selected keys and commits APPLIED atomically after semantic checks. |
| `03-restore.sql` | Reinserts exact originals if the prepared character/talent state remains compatible. Retains archives. |
| `04-status.sql` | Reports provenance and archived original rows; SELECT only. |

The archive name defaults to `tc_talent_cleanup_` plus a digest prefix; an
optional `--archive-schema` selects another fresh name. It must differ from all
source/auth/world schemas. An existing archive is never reused by setup.
The same evidence/tool version produces the same SQL and manifest, independent
of output path. Keep private character keys and generated packages out of Git.

If a previous batch changed only item placement, the earlier talent audit can
still seed this candidate: preparation rechecks all exact selected keys and
the invalid talent set. It refuses a changed total talent count or changed
invalid set. The audit digest is provenance, not proof of every current valid
talent or character field. Preparation freezes the current full affected state
for review; later same-count changes within that state block apply/restore.

## Prepare, review, then apply

Follow the generated README, one step at a time. Use fresh batch clients with
`--skip-force`; never interactive SOURCE or a continuing-on-error client.
First retain the untouched baseline and verify the backup and preparation
endpoint. Keep every game server and other writer stopped. Setup uses an
administrator to create only the new archive and a parameterless read-only
metadata guard. That guard needs direct global SELECT/TRIGGER visibility to
detect triggers/foreign keys hidden from a restricted repair user.

Preparation can run with SELECT-only access to source characters/talents plus
archive DML/EXECUTE privileges. Review the prepared status, exact selected keys,
full original character rows and all retained talents. For apply, grant DELETE
only on the preparation character_talent table. Restore additionally needs
INSERT on that same table. No source UPDATE, spell/skill/item DML, auth/world
writes, service deployment or core C++ changes are required.

Apply checks the full prepared state, removes exactly the selected rows and
updates the archive checkpoint in one SERIALIZABLE transaction. Errors or a
killed client roll back an incomplete application. Repeating apply verifies
the already committed result without deleting again or changing timestamps.
Row counts alone are insufficient: affected character fields and all retained
talent keys must match the prepared snapshots. Catalog/manifest/schema drift,
source triggers, talent foreign keys, unsupported generated/invisible columns,
missing/online affected characters and conflicting archive state are blockers.

MySQL marks ordinary expression defaults, such as `TIMESTAMP DEFAULT
CURRENT_TIMESTAMP`, as `DEFAULT_GENERATED`. These columns are supported: full
snapshots copy their stored values explicitly, preserving old timestamps and
NULLs. Computed virtual/stored columns (with a generation expression) and
invisible columns remain blocked.

An earlier planner incorrectly matched `DEFAULT_GENERATED` as a computed
column. If preparation stopped for that reason, retain the failed candidate
and archive. Generate a new candidate with the corrected planner, the same
verified audit/DBC assets and a fresh output directory. The changed template
fingerprint produces a new default archive name. Run setup and prepare from
that new package; do not edit the source schema, disable the guard or reuse the
old archive. Failed preparation makes no source changes.

The original rows displayed by status after APPLIED come from the archive;
their continued presence there is expected. Keep the archive, SQL, original
audit and before/after reports. Exact restore is available before further
preparation or gameplay, and intentionally recreates the bad records. A restore
refuses changed character/talent state; repeat restore verifies the original
state without changing it. Apply after restore requires a new reviewed batch.

## Continue toward migration readiness

For a separately reviewed single-character reset, first archive the complete
character and both talent groups. An unavailable second group is distinct from
non-rank corruption: legitimate ranks can remain in TC's second physical group
even when the configured count is one. Neither those ranks nor an old account
date prove that dual specialization should be enabled.

The internal `tools/single-character-talent-reset.sql.in` template supports a
narrow policy: archive/remove an exact reviewed unavailable group and set only
`AT_LOGIN_RESET_TALENTS` (`at_login | 4`). Both pinned cores consume this bit on
login and perform a free native reset. Keep the active group's ownership rows
until then so the core can unlearn its talent spells and learned dependencies.
Deleting all talent rows first can leave enabled spells behind and bypass the
native reset's used-point processing. The template is not an automatic cleanup
command; it needs a case-specific reviewed package with fixed character,
account/name/level/class/spec state, server UUID, exact keys and source counts.

Setup freezes current native/custom column metadata; prepare archives full
current character and talent rows. The earlier audit is provenance, not a hash
of all character fields. Review prepared snapshots before apply. Apply changes
only the selected unavailable-group rows and the reset bit, preserving all
other login flags and the specialization count. It makes no spell, skill,
profession, glyph or action-bar writes. APPLIED means **reset pending**, not
that native reset or gameplay acceptance has happened. Pending reset does not
waive any migration compatibility or spell authorization check.

Exact restoration reinserts the archived group and restores the original login
flags only while character/talent state still matches the prepared result.
Restore batches in reverse order: later talent edits invalidate an older
batch's state checks until those later edits are restored. After native login,
save or gameplay, use the preserved baseline for rollback planning instead of
forcing an archive restore. Never silently re-enable dual specialization or
delete spell history to bypass a blocker.

After application, rerun the talent audit into a fresh directory. Confirm this
reason disappeared for live characters and inspect the remaining categories.
Some out-of-range-group findings may overlap removed non-rank rows; compare
exact keys rather than assuming every reason count stays constant.

| Remaining category | Next decision |
|---|---|
| Selectable rank in wrong class/group, conflicting selections | Inspect character/spec state and original ownership; prepare a separate policy. No guessed rank or specialization. |
| Disabled/unowned talent spell history | Review TC enabled/disabled persistence and target representation. History alone is not corruption or permission to activate/delete. |
| Unsupported script, correction, dependency or rank mapping | Review migrator compatibility coverage; do not delete player rows to bypass a coverage guard. |
| Skill values/caps, professions or riding | Inspect native state/configuration separately; no automatic cap/value/slot edits. |
| Orphan references | Use the existing reviewed target sanitation policies or a separately archived preparation batch. |
| Missing custom item/quest metadata | Preserve by default under the source-preparation policy. |

Repeat this audit → exact policy → generated/reviewed batch → archive → apply →
reaudit sequence for each accepted category. Run the full audit after all
preparation, preserve the prepared dump and archives, and start a **new migration
with fresh target/control schemas**. Source edits invalidate old checkpoints.

Audit completion, APPLIED and database READY are separate from native gameplay
and release acceptance. Check both talent specs and points, spell casts and
trainers, profession slots/recipes/riding/skills/caps, then save/relog and
restart in isolated staging. These checks remain NOT TESTED until actually
performed; `PROFILE_APPROVAL=UNREVIEWED` stays unchanged.
