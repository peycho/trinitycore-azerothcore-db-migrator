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
| Shared class/weapon skill spell also taught by another class's talent | Preserve ordinary availability only with matching native TC/AC skill-reward relationships and eligible trainable race/class skill metadata; keep applicable talent ownership restrictions and all skill-preservation checks |
| Complete/overlapping chains | Merge by `(guid,spell)` with deterministic proofs and bitwise-OR masks |
| TC inactive lower rank | Preserve known state when both cores represent it as superseded |
| Inactive unsupported state | Block instead of silently activating it |
| Disabled talent-based spell | Preserve only when inactive-spec ownership explains it and agrees with the active group |
| Disabled ordinary spell or conflicting ownership | Block; no archive override |
| Talent-unlocked trained ranks | Apply verified owner masks and intersect prerequisite eligibility; never infer untrained higher ranks |
| Direct talent ranks | Keep existing selections; never grant preceding talent ranks; follow AC's `addToSpellBook` marker |
| Native temporary talent spells | Record runtime ownership; omit persistent rows that would outlive the owning talent |
| Known non-passive profession research | Preserve only reviewed research IDs with matching existing professions and exact load-safe effects; never execute research or infer recipes |
| Hidden/passive runtime child with an AC-only predecessor prefix | Delegate only the exact authorized learned child to native AC talent loading when TC has no predecessor obligation. Do not persist the child or grant target-only predecessors. |
| TC dependent learned spells | Reconstruct only verified native-compatible dependencies; unsupported world-only learning relationships block |
| Profession/riding tiers | Preserve existing skill lines, values and caps; block missing skills, incompatible effects or cap/value increases |
| Recipes and other ordinary spells | Preserve legitimate stored availability; do not infer recipes from trainer catalogs |
| Unknown IDs, conflicting/gapped chains, cycles, unsupported corrections/scripts | Block with an explicit reason |

Talent metadata is an authorization source, not evidence of training additional
ability ranks. Derived rank traversal ends at the legitimate known anchor.
Talent-dependent classification uses the complete verified learn catalog, not
only selected talents. An unselected hidden/passive child must not fall through
to ordinary mask `3`. Pet-target teaching does not authorize a player child.
Ordinary prerequisites may be satisfied by a verified predecessor that TC
would restore from a stored higher rank: for example, stored Dire Bear Form
`9634` establishes known Bear Form `5487` for Challenging Roar `5209`. Both
cores must agree on that rank prefix; an absent prerequisite without a known
anchor still blocks. This check does not grant any new higher rank or talent.
Pet teaching effects do not authorize player spells. Conditional learned spells
and temporary ranked/mixed learn-effect representations that cannot be proved
safe are rejected. Profile correction rules contain reviewed integer updates,
bounded effect-field copies and conservative guards for unsupported conditional
corrections. Enum values come from protected shared, spell and aura definitions;
no C++ text
is executed. Unknown or spellbook-mutating spell scripts require review.
The reviewed `spell_murmur_sonic_boom_effect` handler only adjusts hit damage;
its complete native source files are protected in both core manifests. Other
encounter handlers remain unreviewed unless separately covered by the profile.
Named native script registrations inherit the implementation's mutation policy;
for paired spell/aura handlers, either implementation can force rejection. This
includes the native Judgement of Justice/Light/Wisdom aliases.

The reviewed TC legacy constructor alias `spell_pal_seal_of_corruption` follows
the protected Seal of Vengeance implementation with its actual Blood Corruption
and Seal of Corruption Damage template arguments. Unreviewed legacy constructor
aliases remain blocked, even when their class name is recognized. Murmur's Sonic
Boom handler triggers its damage spell; the reviewed Teron Shadow of Death aura
handles absorption and temporary summon/possession effects. Neither handler
changes persistent spell ownership. Complete encounter source files are
protected; other handlers in those files are not implicitly approved.

Bounded constant `SpellFamilyFlags[0..2]` corrections are represented explicitly,
including Ebon Plague's word-2 `0x10` assignment. Conditional, dynamic/out-of-range
and copied indexed accesses remain guarded.

The reviewed `spell_gen_profession_research` remains classified as a script that
learns spells. A separate cast-only contract accepts known `60893` (Alchemy) and
`61177`/`61288` (Inscription), with exact effects `[157,77,0]`, the matching DBC
skill association and an existing positive profession skill. Both protected
player loaders leave these non-passive, non-talent research spells uncast.
Passive, hidden-with-stance, teaching/effect changes, other attached IDs and
missing professions still block. The migration preserves current recipes,
values, caps and slots; it does not execute discovery, add recipes or update
crafting skill. Provenance records this load contract and its required skill.

Research casts after migration use native AC behavior. In the reviewed code,
TC's first Northrend Inscription Research can discover three recipes, while
AC's handler discovers one and updates crafting skill. Preserving the current
known recipe set does not emulate TC's future research behavior.

Fiery Payback illustrates a representable runtime-only rank difference: TC may
have no `44440 -> 44441` chain while AC does. Native AC talent loading adds the
exact selected talent's learned child with `_addSpell`, without lower-rank
reconstruction. If that child is hidden/passive and TC has no predecessor
obligation, it is runtime-owned only; the transform grants no additional rank.
If TC does require a predecessor, as with Primal Fury's `16958 -> 16961`, the
temporary-rank guard remains. Do not persist temporary predecessors to work
around their missing native restoration; they can outlive talent ownership.
The actual Fiery Payback talent ranks are `64353` and `64357`; their learned
children are respectively `44440`/`64350` and `44441`/`64349`. Stored disabled
children without selected ownership retain the blocking policy. Rank mismatch
reports include original flags and selected learned-spell owners.

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

The console prints reason counts and the full blocker-report path. The current
audit records the first failure per character; these counts describe affected
characters, not an exhaustive list of bad rows. A script/correction guard can
mean that compatibility has not been reviewed; it does not prove corrupt data.
Rank disagreements report both predecessor prefixes. Unowned spell reports
include stored flags, rank root and selected ranks from the same talent family,
so disabled history can be distinguished from an unexplained enabled grant.
`INVALID_TALENT_OWNERSHIP` is separate: a talent-entry ID stored instead of a
rank spell ID cannot be repaired by guessing which rank was selected. Disabled
direct talent spells without matching selected ownership also remain blocked
under the current policy. Do not turn these records into active AC spell rows,
delete them, or infer replacement talent selections as part of rank completion.
The TC `disabled` flag controls availability even when `active=1`; the active
flag alone does not establish an enabled grant. AC can load/save a zero-mask
row, but the current conversion contract does not authorize such history. A
zero-mask policy needs separate review of resets, relearning and reverse
conversion; accepting the SQL value alone is insufficient.
In particular, AC's `_addSpell` can enable an existing persistent zero-mask
row without changing it to `PLAYERSPELL_TEMPORARY`. Its subsequent
`removeSpell(..., onlyTemporary=true)` refuses to remove that non-temporary
row. A blanket zero-mask copy of temporary talent children can therefore
leave a child available after talent removal. This source-review finding does
not classify every disabled history row as corrupt or every zero-mask use as
unsafe; trained talent abilities and runtime children need separate policies.
`MISSING_SPELL_PREREQUISITE` distinguishes an ordinary missing prerequisite
from talent ownership. Its detail includes required and known prerequisite
IDs. It grants nothing and remains a blocker, including for historical GM
spells. `RESEARCH_SKILL_MISSING` likewise blocks research without its existing
profession instead of adding one.

`spell-state-v3` corrects a shared-spell classification boundary: Dual Wield
(`674`) is taught by shaman talent `30798`, but also has an ordinary skill-reward
route for warriors, hunters, rogues and death knights. Membership in the global
talent-learn catalog does not make it talent-only for every class. The converter
requires a matching skill reward in both effective metadata catalogs, explicit
eligible class masks, matching race/class skill information and no applicable
or unknown talent owner. A not-trainable skill route cannot bypass ownership.
This check authorizes only already reached known spells; it does not scan skills
to grant new spells. Missing or insufficient skill values/caps still block.

Provenance records `ORDINARY_SKILL_AUTHORIZATION` and both native ability and
race/class skill row IDs in `independent_skill_routes`, together with the skill,
acquisition method, threshold and flags. Shamans retain selected-spec talent
authorization; disabled ordinary rows and unowned hidden children remain
blocked. Installing this correction changes policy/toolkit hashes and requires
a fresh migration toolkit, target/control schemas and run. Keep the cleaned TC
source and its cleanup archives.

TC's reviewed `spell_chapter1_runeforging_credit` handler is also accepted.
Its protected chapter script only casts quest-credit spell `54586` for
incomplete quest `12842`. Known Runeforging item-enchantment spells remain
uncast during native loading; migration grants no enchantments or quest credit.
The existing Runeforging skill must be `1/1`, with matching mono skill metadata
in both cores. Native skill loading normalizes this skill to `1/1`; other stored
values/caps block instead of relying on a correction. Only this named handler
is accepted from that chapter file; other chapter handlers are not implicitly
approved. Add a staging check that known Runeforging enchantments remain
available after relog and that loading does not award quest credit.

Use the retained report to review representative failures before another run:

```bash
awk -F '\t' 'NR==1 {print; next} n[$3]++ < 3 {print}' \
  "$RUN_REPORTS/spell-state-blockers.tsv"
```

| Blocker family | Required review; current behavior |
|---|---|
| Invalid or unowned talents | Compare stored talent rank spell IDs, selected groups and TC flags. Block; never guess a rank from a talent-entry ID or activate a disabled unowned talent. |
| Script or core correction guards | Review the actual protected implementation and metadata. A guard can indicate incomplete compatibility coverage, not corrupt character data. |
| Incompatible or temporary rank chains, learned-spell dependencies | Compare both worlds, DBC relationships and native runtime ownership. Block unsupported representations; never copy a source-only dependency blindly. |
| Missing/incompatible skills, skill-step teaching spells | Check native loader behavior, profession slots, recipes and existing skill values/caps. Block any unproved skill change. |
| Inactive/disabled spell states | Compare stored anchors, flags, selected talents and both cores' visibility rules. Block when representability is not established. |

Resolving one blocker can expose another for the same character. A successful
focused regression does not clear every record in a production-sized source.

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
