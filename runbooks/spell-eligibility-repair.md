# Reviewed ordinary spell eligibility repair

Forbidden Wolf Riding `825` with stored skill `149` uses the separate
[coupled riding retirement](obsolete-riding-repair.md). Ordinary eligibility
policies continue to defer stored skills and riding effects.

This separate preparation policy retires ordinary spell families that AC rejects
for the character's race/class, **including enabled TC rows**. It deliberately
changes unsupported source spell availability. It is not a general cleanup,
talent reset, staff exemption or migration override. Use a stopped restored
preparation copy and retain its backup, complete originals and prior toolkits.

## Why these rows block

Pinned AC `Player::CheckSkillLearnedBySpell` checks existing `SkillLineAbility`
associations against `SkillRaceClassInfo`. Any eligible skill suffices; zero
race/class masks are unrestricted. The ability's own masks alone are insufficient.
Missing skill-line definitions are ignored by this consumer; a spell with no
applicable associations passes this particular check.

With native validation enabled, `_LoadSpells` rejects a failing stored row and
explicitly deletes it by **character GUID and spell ID**. TC's stored-row loader
has no equivalent gate. For example, Thrown on a mage and Conjure Water on a
paladin fail. Legitimately omitted predecessor ranks are a separate issue.
These findings do not establish how an old record arose or prove corruption.

Migration keeps blocking these states. This policy prepares exact-row retirement
for review instead of letting AC delete rows at first login. Neither core nor
its validation setting is changed.

## Configure and preview

Install the complete toolkit, keeping the current source session if its source
identity/endpoint is unchanged. Edit existing INI entries without duplicating
sections or keys; add the optional target section:

```ini
[source]
; Keep existing source settings. Verify effective TC PlayerStart.AllSpells.
player_start_all_spells = 0

[target]
world = acore_world
; Verify PlayerStart.CustomSpells in the effective AC worldserver configuration.
player_start_custom_spells = 0
```

TC calls this `PlayerStart.AllSpells`; AC calls it `PlayerStart.CustomSpells`.
These are **operator assertions**, not server configuration changes. Both must
be verified as zero so custom starting-spell routes cannot reactivate retired
rows. Unknown/enabled values block planning. Target world must use the same
MySQL endpoint and differ from every source schema. Set the existing `ac_dbc`
and `ac_source` paths. Both cores must match the protected manifests. Pins and
`PROFILE_APPROVAL=UNREVIEWED` remain unchanged.

Audit and writer roles need SELECT on AC's seven DBC overlay tables plus
`spell_ranks`, `spell_required`, `spell_script_names`, `spell_custom_attr` and
`trainer_spell`. The writer reads metadata for direct SQL guards. No world writes
are granted. Existing archive/source grants follow the [console guide](cleanup-console.md).

Use a current sealed migration inspection. After source edits, an old blocker
report supplies GUID scope for a fresh read-only capture without another full
audit or preflight. Skip capture if the latest inspection matches unchanged data:

```bash
python3 console inspect-migration-blockers --report /path/to/spell-state-blockers.tsv
python3 console plan spell-eligibility --migration-inspection latest --preview
```

Preview examines complete captured spellbooks, including failures hidden behind
the first error. It writes `spell-eligibility-review.json` in the operation
directory, creates no SQL package/active batch and changes no database rows.
It records exact selected/deferred rows, rank eligibility proofs, configuration
assertions and target fingerprints. It is not live full-row verification or
permission to delete every ineligible row.

## Selection boundaries

`tc-ineligible-ordinary-spell-repair-v1` requires both effective catalogs,
including AC database overrides, to agree on the complete rank chain, skill
associations and race/class restrictions. Missing native skill-info rows defer;
absence of metadata is not a verified ordinary-class restriction. Every member must be ineligible in
both. The whole stored family is selected or deferred; absent ranks receive no
grant. Same-count metadata drift is rejected.

Both selected talent builds and all talent/aura families are protected. Incoming
and outgoing learning/prerequisite routes, cycles, scripts, unknown corrections,
skill-learning effects and skill-modifying auras defer. Only class and weapon
skill categories are supported; professions, riding, languages and pet/other
categories defer. **Any associated stored skill** defers the family, preserving
ownership, values, caps and skill rewards. Weapon proficiency can therefore be
retired only when its associated stored skill is already absent.

Online characters, pending reset bit 4, unsupported character/spec state,
malformed flags, invalid/foreign talent ownership and catalog disagreement
defer. Older disabled-history policies keep their restrictions. SQL inserts no
spells and rewrites no flags, talents, points, skills, profession slots, glyphs,
action buttons, items, custom fields or character fields. Retired abilities stop
being known; unchanged action buttons may reference them until updated.

## Review, apply and restore

Use preview **selected_rows**, not its reviewed count or the saved report count:

```bash
python3 console plan spell-eligibility --migration-inspection INSPECTION_ID --expect-rows SELECTED_ROWS
```

Planning rechecks the entire captured source scope, including deferred characters,
then fingerprints full affected rows including custom fields. Review the new
batch README, manifest, selected/excluded rows, `relationship-review.tsv`,
`eligibility-native-proof.json`, both metadata snapshots and SQL:

```bash
python3 console prepare --batch BATCH_ID
python3 console status --batch BATCH_ID
python3 console apply --batch BATCH_ID
python3 console status --batch BATCH_ID
```

PREPARED archives full character/spell/talent/skill originals without source
changes. APPLIED commits exact spell deletion and its checkpoint atomically.
Reruns verify committed state; incomplete/disconnected transactions roll back.
Source and both world layouts/content are guarded, including direct calls.
New eligibility batches hash FLOAT/DOUBLE through their round-trip double text
and DECIMAL through exact decimal text; binary columns retain their bytes.
MySQL `HEX(number)` alone rounds fractions and is insufficient. The new numeric
contract and reader hash are sealed without changing historical batch definitions.
Console actions supply acknowledgements. Before each direct SQL action use:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @spell_eligibility_ack='RETIRE_VERIFIED_INELIGIBLE_SPELLS';
SET @eligibility_tc_all_spells=0;
SET @eligibility_ac_custom_spells=0;
```

The writer requires source `character_spell` DELETE for apply and INSERT for
restore; source writes are never granted automatically. Each batch has a new
archive. Before gameplay/later edits, exact restoration is:

```bash
python3 console restore --batch BATCH_ID
```

It reinstates complete removed rows including custom/binary fields and rejects
drift. Restore overlapping batches in reverse order using original toolkits.
Older policies retain their historical numeric hash scheme, which can miss
fractional-only drift. Do not rely on those older guards after edits/gameplay;
restore only against the unchanged stopped preparation state or use the baseline.
For a fresh baseline import, retain old evidence, `console init` a new session,
capture fresh context and create new plans. Never reuse old SQL. After preparation,
migrate into fresh target/control schemas; other blockers can remain.

## Validation and gameplay

Fast regressions keep old policies/conversion as failing controls and verify
whole families, eligible controls, both specs, no grants, protected skills/talents,
metadata/route/flag/reset exclusions and deterministic counts. Disposable MySQL
8.4 exercises the real console with restricted users: preview/config/count/full
scope drift, both world/overlay/layout guards, direct SQL assertions, late-error
and disconnect rollback, reruns, unrelated data and exact custom-row restoration.
Fractional position/DECIMAL changes and both cores' floating DBC overrides are
negative controls, including same-count changes that collide under old `HEX`.

`tests/spell-eligibility-runtime-tests.py` compiles protected AC lookup/check/load
functions with mocked catalogs/player/DB sinks. It checks race/class alternatives,
zero masks, missing metadata behavior, accepted masks and GUID-scoped deletion.
An optional private review JSON exercises captured cases without embedding
player evidence in public tests. This is consumer verification, not gameplay.

Record the existing five [staging gameplay gates](spell-reconstruction.md)
individually. Include retired abilities/action buttons, retained legitimate
weapon/class spells, both specs, unchanged skills/caps/professions and
save/relog/restart logs. Gameplay remains **NOT TESTED** until performed; release
approval remains **UNREVIEWED**.

## Opt-in absent single-child teachers (v2)

`--absent-teachers` selects the separate
`tc-ineligible-ordinary-absent-teacher-repair-v2` preparation policy. The v1
default still defers every learning/prerequisite relationship. V2 permits only
the exact stock Conjure Water and Summon Doomguard incoming teachers, when
**every teacher is absent from the complete character spellbook**, including
disabled history. A missing teacher is not a reason to grant its child.

```bash
python3 console plan spell-eligibility --migration-inspection latest --absent-teachers --preview
python3 console plan spell-eligibility --migration-inspection INSPECTION_ID --absent-teachers --expect-rows SELECTED_ROWS
```

The selector verifies the explicit parent/child pairs, singleton teacher ranks,
flags, pure single-child learn effects, targets and gates in both catalogs.
Teachers must have no script, skill association, talent/aura ownership or incoming
learning/prerequisite route. Their only outgoing edge must teach the reviewed
child. Additional or changed routes, cycles, multi-child stance teachers and
skill teachers defer. Both custom-start settings must still be explicitly off.
The child family retains every v1 eligibility, skill, ownership, metadata,
character-state and pending-reset check. No teacher is removed, executed or
inserted. No pet spell, skill, talent, profession or login flag changes.

Native TC `_LoadSpells` adds only stored spells; its dependent-learn loop is
entered when adding that parent. An absent isolated teacher therefore cannot
recreate the retired child during spell loading. This is a load-time proof,
not a claim that an item, quest or future command can never teach a spell.
The policy deliberately retires the existing wrong-class child availability.

Review `absent_teacher_contract` in `eligibility-native-proof.json`, exact
selected rows and complete originals. Prepare/status/apply/restore are unchanged.
The console supplies an additional acknowledgement; direct SQL also requires:

```sql
SET @eligibility_absent_teachers_ack='VERIFIED_TEACHERS_ABSENT';
```

Complete source spellbooks, both world contents/layouts, DBC assets, selector,
configuration and numeric fingerprints are sealed and rechecked. Adding even a
disabled teacher after planning invalidates the batch. Transaction, rerun and
exact restoration guarantees are unchanged. Keep original toolkits for restoring
earlier policies. On a fresh baseline import, create a new session, capture
fresh inputs and regenerate the plan; never reuse old approvals or SQL. After
preparation, migrate with fresh target/control schemas and a new run.

Fast tests retain v1 as a rejecting control and cover known teachers, modified
effects, skills, extra/cyclic routes, scripts and eligible class controls.
`tests/absent-teacher-runtime-tests.py` compiles the protected TC stored loader
and dependent-learn loop with recording sinks. It tests all ten absent/present
teacher pairs and disabled/auto-learn controls. AC's existing compiled
eligibility/load/delete harness separately verifies child rejection. The real
console MySQL 8.4 v2 suite adds teacher-presence/route drift and extra SQL
acknowledgement controls to the existing interruption/rerun/exact-restore suite.
These are isolated consumer tests, not gameplay. Core pins, global manifests,
spell reconstruction and UNREVIEWED approval remain unchanged. All five staging
gameplay gates still require individual results.

## Opt-in fixed wrong-race racials v3

`--reviewed-racials` uses the separate
`tc-ineligible-reviewed-racial-spell-repair-v3` policy. It covers only these stock
singleton spells, using exact reviewed mechanics and race/class skill metadata
in both effective catalogs:

| Spell | Racial | Eligible race |
| --- | --- | --- |
| 20597 | Sword Specialization | Human |
| 28875 | Gemcutting | Draenei |
| 59224 | Mace Specialization | Dwarf |
| 59539 | Shadow Resistance | Draenei |

This explicitly retires a wrong racial, including its bonus. Gemcutting's +5
Jewelcrafting bonus is separate from the stored skill value and cap: protected
TC/AC aura and skill-bonus consumer tests verify that distinction. The repair
preserves stored skills; it does not compensate for the removed bonus.

The character must fail the **race** mask in both catalogs. A class-only mismatch
is insufficient. Every existing eligibility guard remains: associated stored
racial skills, pending resets, invalid character/talent state, scripts, learning,
requirements and talent/aura ownership defer. A changed fixed catalog also defers.
Languages, shields, old riding skills and other racial spells are outside this
mode. No replacement racial is granted and no race field is changed.

After pulling the complete toolkit, use the latest unchanged inspection, or
capture current source state using the existing saved blocker TSV:

```bash
python3 console plan spell-eligibility \
  --migration-inspection latest --reviewed-racials --preview

# Copy INSPECTION_ID and selected_rows from that preview; do not reuse old counts.
python3 console plan spell-eligibility \
  --migration-inspection INSPECTION_ID --reviewed-racials --expect-rows SELECTED_ROWS
```

Review the generated README, exact rows and `eligibility-native-proof.json`, then
use the existing explicit `prepare --batch BATCH_ID`, `apply --batch BATCH_ID`,
`status --batch BATCH_ID` and `restore --batch BATCH_ID` procedure. Preview and
planning do not change source rows. The v1 and v2 defaults remain unchanged;
`--reviewed-racials` cannot be combined with `--absent-teachers`.

The console supplies the additional direct-SQL acknowledgement
`@eligibility_racials_ack='RETIRE_ONLY_REVIEWED_WRONG_RACE_RACIALS'`. Missing or wrong
acknowledgements reject the operation. Catalog, source, both worlds, DBCs and
protected reader fingerprints remain guarded at every action. Keep the original
complete toolkit for restoring an earlier batch.

Tests cover native AC eligibility/loading and exact character-scoped deletion,
TC/AC Gemcutting bonus consumers with recording state, opt-in selection and
negative controls, and isolated MySQL archive/apply/restore with custom fields,
metadata drift, late failure and disconnect rollback. Full gameplay remains
**NOT TESTED** and migration approval remains **UNREVIEWED**.

On a fresh import, create a new session and regenerate inspections, selections,
counts and archives using this policy. Old batch IDs and SQL packages belong to
their original source snapshot.
## Opt-in inactive foreign Swipe (v4)

`--inactive-foreign-swipes` selects the separate
`tc-inactive-foreign-swipe-retirement-v4` contract. It retires only existing
inactive/non-disabled (`active=0, disabled=0`) ranks of Swipe (Bear), whose root
is `779`, on a verified non-druid. It does not activate spells or add Bear Form.
Every stored rank in that family must be inactive/non-disabled, Bear Form `5487`
must be completely absent from the spellbook (including disabled history), and
Feral Combat skill `134` must be absent. Druids, enabled/disabled siblings,
pending talent resets and unsupported character/talent state defer.

The fixed catalog seals the complete reviewed rank order, spell mechanics,
abilities and skill eligibility in both cores. TC has no prerequisite edge for
this family; AC has exactly `5487 -> 779` in `spell_required`. That prerequisite
is a requirement, not a grant of Bear Form. Only this exact absent-prerequisite
case is allowed. Added learning, requirement, talent, aura or script routes,
changed masks and unknown metadata remain blocked. All other eligibility modes
retain their behavior; the new flag is mutually exclusive with their flags.

```bash
python3 console plan spell-eligibility \
  --migration-inspection latest --inactive-foreign-swipes --preview
python3 console plan spell-eligibility \
  --migration-inspection INSPECTION_ID --inactive-foreign-swipes --expect-rows SELECTED_ROWS
```

Use the actual preview selection, then review the candidate README,
`selected-rows.tsv` and `eligibility-native-proof.json`. Use the existing explicit
prepare/status/apply/status/restore sequence above. Complete originals, custom
columns, numeric fingerprints, both-world metadata, configuration assertions and
all affected source state remain guarded. SQL removes only selected spell rows;
both talent builds, skills/caps, items and login flags stay unchanged. No absent
rank, prerequisite, skill or replacement ability is granted.

Direct SQL additionally requires
`@eligibility_swipe_ack='RETIRE_ONLY_INACTIVE_FOREIGN_SWIPE_ABSENT_BEAR_FORM'`.
Missing/wrong acknowledgement, changed catalog, newly stored Bear Form or changed
prerequisite inputs reject the sealed batch. Retain original toolkits for earlier
archives. Fresh imports need new sessions, inspections, selections and archives.

The migrator reports only the first failure for each character. Retiring a
reviewed row can expose a different blocker on the same character, so the number
of blocked characters may stay unchanged. A pending native-reset flag likewise
does not prove its reset has executed or that other blockers will disappear.
Local native-reader and disposable SQL checks are separate from gameplay, which
remains **NOT TESTED**. Approval remains **UNREVIEWED**.
