# Reviewed player-side pet-teaching retirement

This preparation policy archives and removes exact **player** `character_spell`
rows for reviewed old pet-teaching wrappers, including enabled rows. Retiring
these actions deliberately loses their old pet-training availability. Actual
pets, their `pet_spell` rows, talent selections in both specs, skills/caps,
profession slots, items and login flags remain unchanged. No replacement spell
or pet ability is granted. It does not make a blocked migration pass by override.

## Why AC cannot retain these rows

TC `Player::AddSpell` stores ordinary non-passive learn-effect wrappers. Pet
learn effects are auto-learned in the spell manager and are not player-child
restoration routes during source loading. AC `Player::_addSpell` explicitly
refuses persistent `SPELL_EFFECT_LEARN_SPELL` rows. Its temporary fallback adds
children to the **player**, without using the pet target. Neither copying the
wrapper nor marking it temporary preserves a safe player spellbook.

The repair covers only nine explicit stock families: Cower, Bite, Scorpid
Poison, Lightning Breath, Avoidance, Warp and the reviewed resistance wrappers.
`lib/cleanup_pet_teaching.py` records every permitted wrapper/child pair. A spell
name, trainer row, or existing pet spell never authorizes a player grant.
Unknown wrappers remain outside this policy.

## Configure, preview and apply

Use the complete current toolkit on the stopped restored preparation copy,
keeping its backup and previous toolkits/archives. Continue the current source
session if its baseline/endpoint is unchanged. The existing eligibility
configuration is reused:

```ini
[source]
; Keep existing source entries; assert effective TC PlayerStart.AllSpells=0.
player_start_all_spells = 0

[target]
world = acore_world
; Assert effective AC PlayerStart.CustomSpells=false (the reviewed default).
player_start_custom_spells = 0
```

Edit existing keys; do not duplicate sections. These are operator assertions,
not server configuration changes. Both world schemas are read-only, on the
same MySQL endpoint and disjoint from the character/auth source schemas.
Existing `tc_source`, `ac_source`, `tc_dbc` and `ac_dbc` paths are required.
Audit/writer SELECT permissions on target metadata match the
[eligibility repair](spell-eligibility-repair.md#configure-and-preview).

Use a sealed current migration inspection. After source edits capture current
context from an existing saved report, or reuse a capture of unchanged data:

```bash
python3 console inspect-migration-blockers --report /path/to/spell-state-blockers.tsv --bundle
python3 console plan pet-teaching --migration-inspection latest --preview
```

Preview writes `pet-teaching-review.json`, including selected/deferred rows,
configuration assertions, native pair proofs and both world/DBC fingerprints.
It changes no database rows, creates no SQL package and selects no active batch.
Its candidate count can exceed the first-failure report because it reviews the
complete captured spellbooks. It is not a full current migration preflight.

Use **selected_rows**, not candidate rows or affected-character count:

```bash
python3 console plan pet-teaching --migration-inspection INSPECTION_ID --expect-rows SELECTED_ROWS
python3 console prepare --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Review the batch README, manifest, selected/excluded rows, relationship review,
`pet-teaching-native-proof.json`, metadata and SQL. Preparation archives complete
original character, spell, talent and skill rows, including custom fields;
source rows remain stored. After review:

```bash
python3 console apply --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Apply removes only exact selected `(guid,spell)` pairs and commits its checkpoint
in the same transaction. Reruns check the committed result; failed/disconnected
transactions roll back. The writer needs DELETE on source `character_spell` for
apply and INSERT for restoration. No source write grants are added automatically,
and no write privilege on pet tables is needed.

## Selection and integrity boundaries

`tc-pet-teaching-wrapper-retirement-v1` accepts only offline hunters with valid
character/spec state and existing valid selections in both groups. Pending
native reset, unknown IDs, foreign/duplicate talent ownership and invalid flags
defer or block. There is no staff exemption.

Both catalogs must agree on the complete explicit wrapper rank identity. The
selector verifies each known prefix through the highest stored wrapper against
its exact stock child, pet-only target, pure learn effect, non-passive flags,
unconditional gates, numeric spell metadata and supported corrections. Absent
higher wrappers receive no grant or execution. Legacy Avoidance has missing
children on unlearned higher ranks: they cannot authorize removal when reached,
but do not invalidate a verified lower-only stored anchor.

The entire stored family is selected or deferred. Parent/child scripts, selected
talent/aura routes, skill associations/effects, player-learning dependencies,
requirements, incoming routes, unknown mappings and mixed effects defer. A pet
ability found in the player spellbook also defers its teacher. Actual pet rows
are never deletion candidates. Scripted child cases intentionally remain outside
this version, even if another migration script contract recognizes their names.

Planning rechecks **all captured semantic inputs**, including deferred characters,
then full affected originals and source/world layouts. Strong fractional numeric
fingerprints cover FLOAT/DOUBLE, exact DECIMAL and binary/custom fields. Both
world contents, assets, selector/metadata-reader hashes, configuration contract,
expected result and template are sealed. Direct SQL calls retain the guards.
The console supplies these acknowledgements before each action; direct calls need:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @pet_teaching_ack='RETIRE_VERIFIED_PET_TEACHERS';
SET @pet_teaching_tc_all_spells=0;
SET @pet_teaching_ac_custom_spells=0;
```

## Restore and repeat

Before gameplay or further edits, restore with the retained original toolkit:

```bash
python3 console restore --batch BATCH_ID
```

The inverse reinstates exact removed rows and refuses affected-state drift;
archives remain. Restore overlapping later batches first. Historical policies
keep their original behavior and numeric-hash limitations; do not weaken their
guards after gameplay. Use the untouched baseline if restoration no longer fits.

For a freshly imported baseline, retain the old workspace/archive evidence,
start a new `console init` session, capture fresh inputs and regenerate plans.
Never replay old SQL or approvals. After preparation, migrate with a new run
and fresh target/control schemas. This policy does not repair an existing AC
staging database in place. Core pins, reconstruction policy, manifests and
`PROFILE_APPROVAL=UNREVIEWED` are unchanged.

## Validation and gameplay acceptance

Fast regressions prove old conversion fails, whole stored families merge
predictably, both specs retain selections, absent higher ranks receive no grant,
and unsafe routes/flags/metadata defer. The real console MySQL 8.4 suite exercises
restricted grants, preview/count/full-scope drift, both world layouts/content,
fractional data, direct-SQL assertions, late-error/disconnect rollback, reruns and
exact binary/custom restoration. Native pet rows and unrelated data are checksum
controls. Protected AC insertion/save functions verify rejection and the unsafe
temporary fallback with mocked catalogs/state/DB sinks, separately from gameplay.

Record all five existing [staging gameplay gates](spell-reconstruction.md#validation-and-staging-gameplay-gate)
individually: trainers/ranks; casting; both specs/relog; talent points, pets,
professions/recipes/riding and skills/caps; save/relog/restart and logs. Include
retained pet abilities and removal of retired player-side pet-training actions.
These remain **NOT TESTED** until executed; approval stays **UNREVIEWED**.
