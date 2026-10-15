# Character spell reconstruction

This is a migration transform, not a staging repair command. Use the normal
[migration guide](migration-guide.md) with fresh target/control schemas.
Existing staging databases need a new migration. Repairing a database that has
already accepted player writes requires a separately reviewed repair with its
own backup, ownership and rollback evidence. No core patch or CleanCharacterDB
setting is used. The v2 profile remains **UNREVIEWED**.

## Why stored row counts were insufficient

At reviewed TC `92127cd6252edb96fbfa36540db0eba17d0031fa`,
`Player::_LoadSpells()` calls `AddSpell()`. Its non-talent branch recursively
adds preceding ranks as dependent spells. `_SaveSpells()` excludes dependent
spells. `HasSpell()` includes inactive ranks but excludes disabled ones.
Consequently a valid source spellbook can store only its highest trained rank.

At reviewed AC `1cd97629ed6ef49f5c70dec39316846381d2e450`,
`PlayerStorage::_LoadSpells()` calls `addSpell()` for stored spell rows without
equivalent predecessor reconstruction. `HasSpell()` checks presence and the
active specialization bit; `Trainer::GetDefaultSpellState()` checks it for both
direct trainer spells and wrapped learned spells. Previously, copying rows with
mask `3` passed count/mask validation while leaving lower ranks unknown to trainers.

The separate invalid `character_talent` investigation is not the explanation
for legitimately omitted predecessor ranks. Spell/talent ownership blockers
are reported distinctly from derived ranks.

## Required read-only inputs

For nonempty character spell/talent conversion, configure:

```bash
SOURCE_WORLD_SCHEMA=trinity_world
TARGET_WORLD_SCHEMA=acore_world
TRINITYCORE_DBC_DIR=/secure/path/tc-dbc
AZEROTHCORE_DBC_DIR=/secure/path/ac-dbc
```

Reverse direction swaps the world schemas; core-specific asset directories
retain their meaning. Each directory must contain `Spell.dbc`, `Talent.dbc`,
`TalentTab.dbc`, `SkillLine.dbc`, `SkillLineAbility.dbc`,
`SkillRaceClassInfo.dbc` and `SkillTiers.dbc` in the pinned WDBC layouts.
Python 3 with its standard library is a runtime dependency.

Both world schemas require SELECT only. Worlds must be distinct and may not
overlap writable target/control schemas. The migrator never imports world SQL
or alters DBC assets. Empty spell/talent input can omit spell metadata; existing
reverse respawn checks still have their own source-world requirement.

The reader follows TC's additive `spell_dbc` policy: replacing an existing DBC
ID is rejected, as TC's reader would abort. AC numeric DBC database overrides
are applied using the pinned layouts. Rank/talent chains, spell requirements,
learned-spell effects, skill effects, race/class eligibility, relevant core
corrections and spell scripts are audited before target assembly.

World metadata rows are read without a server-side row sort, ordered in Python,
and hashed in full, including localized text and duplicate rows. This avoids
sorting every column of wide DBC overlay tables inside MySQL's sort buffer.
Character input remains streamed in GUID order. No global or session sort-buffer
increase is required by the world metadata reader.

If a database query fails (for example, access denial, a disconnect or MySQL
error 1038), conversion stops with `spell-metadata-errors.tsv`. This is a read
failure, not evidence of incompatible character spells. No expected snapshot or
spell rejection is committed from that attempt. Resolve the reported database
error before retrying with unchanged inputs and toolkit. Installing a reader
fix changes toolkit identity and requires a fresh toolkit copy, target/control
schemas and run ID; do not replace code underneath an existing run.

## Reconstruction and blocking policy

| Representation | Policy |
|---|---|
| Ordinary known higher rank | Preserve it and reconstruct only its verified predecessor prefix; mask `3` |
| Complete/overlapping chains | Merge by `(guid,spell)` with deterministic proofs and bitwise-OR masks |
| TC inactive lower rank | Preserve known state when both cores represent it as superseded |
| Inactive unsupported state | Block instead of silently activating it |
| Disabled talent-based spell | Preserve only when inactive-spec ownership explains it and agrees with the active group |
| Disabled ordinary spell or conflicting ownership | Block; no archive override |
| Talent-unlocked trained ranks | Apply verified owner masks and intersect prerequisite eligibility; never infer untrained higher ranks |
| Direct talent ranks | Keep existing selections; never grant preceding talent ranks; follow AC's `addToSpellBook` marker |
| Native temporary talent spells | Record runtime ownership; omit persistent rows that would outlive the owning talent |
| TC dependent learned spells | Reconstruct only verified native-compatible dependencies; unsupported world-only learning relationships block |
| Profession/riding tiers | Preserve existing skill lines, values and caps; block missing skills, incompatible effects or cap/value increases |
| Recipes and other ordinary spells | Preserve legitimate stored availability; do not infer recipes from trainer catalogs |
| Unknown IDs, conflicting/gapped chains, cycles, unsupported corrections/scripts | Block with an explicit reason |

Talent metadata is an authorization source, not evidence of training additional
ability ranks. Derived rank traversal ends at the legitimate known anchor.
Pet teaching effects do not authorize player spells. Conditional learned spells
and temporary ranked/mixed learn-effect representations that cannot be proved
safe are rejected. Profile correction rules contain reviewed integer updates
and conservative guards for unsupported conditional corrections; no C++ text
is executed. Unknown or spellbook-mutating spell scripts require review.

The migrator changes no talent selections, skill rows, skill caps or profession
slots. Profession/riding spell effects are checked against existing skills;
native runtime slot/tier behavior must also pass the gameplay gate below.

## Checkpoints, evidence and validation

Preflight streams numeric character spell/talent/skill state in GUID order and
captures input hashes. Relevant world layouts/rows and DBC bytes are fingerprinted.
Same-count changes are detected. Every later command rechecks captured spell
inputs before accepting a completed phase or resuming work. Changed inputs or
toolkit identity require fresh targets/control and a new run.

Control tables retain immutable expected rows, input/expected hashes and
committed provenance. Each GUID chunk commits target spell rows, provenance
and completed checkpoints in one transaction. A pre-commit failure rolls all
three back; a post-commit interruption can resume without duplicate rows.

Private reports include:

- `spell-fingerprints.tsv`: metadata and source-input SHA-256 evidence.
- `spell-expected.tsv`: preflight reconstruction and original flags/proofs.
- `spell-state-blockers.tsv`: incompatible character keys, reason codes and details.
- `spell-metadata-errors.tsv`: failed query input, reason code and database error;
  no spell compatibility conclusion was possible.
- `spell-reconstruction.tsv`: committed rows, masks, derived/runtime dispositions
  and source-anchor paths; regenerated from control data. Provenance names the
  rank root, talent owner IDs/masks, prerequisites and mask policy, alongside
  original source flags, so specialization reductions have an explicit reason.
- `spell-drift-fingerprints.tsv`: observed input evidence when a snapshot changes.

The final report summarizes persistent, runtime-owned and direct-talent rows.
Validation compares exact spell IDs/masks or TC flags, rejects unexpected grants,
checks committed provenance and preserves the existing unrelated-data checks.
Approved orphan cleanup is accounted for by retained character identity rather
than subtracting the number of stored TC rows. Database `READY` is not native
gameplay acceptance or release approval.

Reverse migration reconstructs TC enabled/disabled state for supported masks.
Only the active direct talent rank enters TC's spellbook, avoiding its removal
of alternate direct ranks during `AddSpell()`. Talent-group ownership remains
unchanged. TC may again stop persisting dependent lower ranks after a native save;
the semantic known state, not historical stored-row equality, is the contract.

## Validation and staging gameplay gate

Run [development checks](development.md). Synthetic fixtures exercise paladin,
priest and warlock chains, overlapping/complete rows, specialization ownership,
inactive/disabled states, professions/riding, unsupported relationships, rollback,
interruption before/after commit, resume, reruns and input immutability. The trainer
test executes the protected AC `GetDefaultSpellState()` function with mocked
getters against migrated rows, including direct/wrapped spell checks in both specs.
It proves that consumer behavior only; it does not run a worldserver or client.

After a fresh isolated migration, record each check as `PASS`, `FAIL` or `NOT TESTED`:

1. Audit paladin Devotion Aura `48942`, Holy Light `48782` and Hammer of Justice
   `10308`, plus representative priest/warlock chains. Previously known lower ranks
   must be learned at trainers; unlearned higher ranks must remain unlearned.
2. Cast highest and supported lower ranks; check spellbook/action-bar behavior.
3. Switch both specs and relog in each. Talent-unlocked ranks and temporary spells
   must exist only for their owning specs; ordinary trained spells remain available.
4. Compare talent selections/points, profession slots, recipes, riding tier,
   skill values and caps with the source runtime baseline.
5. Save, relog and cleanly restart AC. Repeat spell/trainer/spec and profession
   checks; inspect logs for deleted spells, skill corrections and talent errors.

Retain reports and the untouched source for rollback. No existing staging or
production database is repaired automatically. Native smoke tests and two
production-sized isolated rehearsals remain mandatory before profile approval.
