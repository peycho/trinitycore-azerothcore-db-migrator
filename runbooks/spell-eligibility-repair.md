# Reviewed ordinary spell eligibility repair

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
