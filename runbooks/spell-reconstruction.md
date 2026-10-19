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

AC `trainer_spell.SpellId` is read and fingerprinted as exclusion evidence for
native passive ranks, including wrapped learned spells. Trainer entries never
authorize a grant. Missing required metadata stops conversion.

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
| Reviewed ranked passive talent children | Use AC's exact selected temporary children for Primal Fury, Will of the Necropolis, On a Pale Horse and Blood Gorged, under the bounded native contract below; never persist superseded internal passive predecessors in AC |
| Known non-passive profession research | Preserve only reviewed research IDs with matching existing professions and exact load-safe effects; never execute research or infer recipes |
| Hidden/passive runtime child with an AC-only predecessor prefix | Delegate only the exact authorized learned child to native AC talent loading when TC has no predecessor obligation. Do not persist the child or grant target-only predecessors. |
| Nurturing Instinct helpers | Delegate exact selected-rank helper to native aura/temporary ownership (`AURA`); never persist the helper or reconstruct its predecessors |
| Feral Swiftness world-learned helpers | Under the v8 contract, map TC's inactive dependent helper to AC's selected-talent/form aura (`AURA`); retain exact rank/spec ownership, with no persistent helper or inferred form |
| Runeforging native skill rewards | Delegate only verified `53428 -> 53341/53343` dependencies (`SKILL`), with existing skill `776` exactly `1/1` and matching eligible native reward metadata |
| Flight Form's TC world dependency | Materialize `33943 -> 34090` and its verified riding predecessors as persistent ordinary rows only with an explicit active TC world edge and existing riding `762` at `225/225`, or `300/300` with an already known Artisan Riding anchor. Never infer Artisan Riding from Flight Form. |
| TC dependent learned spells | Reconstruct only verified native-compatible dependencies; unsupported world-only learning relationships block |
| Hidden dual-spec teacher `63680` | Under v10, retain its original stock row as control disposition `TEACHER` and persist only verified TC-known buttons `63644`/`63645`; require existing two-spec ownership and Generic skill `183`; never cast the wrapper, purchase a spec or infer an absent reverse wrapper |
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
temporary-rank guard remains unless the reviewed native-passive contract below
applies. Persisting temporary predecessors can make them outlive talent ownership.
The actual Fiery Payback talent ranks are `64353` and `64357`; their learned
children are respectively `44440`/`64350` and `44441`/`64349`. Stored disabled
children without selected ownership retain the blocking policy. Rank mismatch
reports include original flags and selected learned-spell owners.

The migrator changes no talent selections, skill rows, skill caps or profession
slots. Profession/riding spell effects are checked against existing skills;
native runtime slot/tier behavior must also pass the gameplay gate below.

### Feral Swiftness world helpers

`spell-state-v8` supports a specific native representation difference, not a
general permission to ignore TC world dependencies. TC's explicit inactive,
non-autolearned edges are `17002 -> 24867` and `24866 -> 24864`. `AddSpell`
restores the helper with `active=false`, `dependent=true`, `disabled=false`
when the enabled selected parent loads; `_SaveSpells` omits dependent rows.
The hidden helper's Cat/Bear/Dire Bear stance flags let TC's native shapeshift
loop cast it even though it is inactive in the client spellbook.

AC has no equivalent learn edge. Its protected `spell_dru_feral_swiftness`
callback checks `HasTalent` in the active spec and casts only that rank's
helper. It is attached to both talent ranks and Bear/Dire Bear form spells;
the native talent stance loop applies the Cat talent aura. Removal clears both
helper auras. The helper is an aura, not an AC temporary or persistent known
spell. Migration records `AURA` with the exact selected owner's mask. It never
adds Bear Form, Dire Bear Form, Cat Form or a talent selection.

The bounded `world_talent_auras` profile contract checks both ranks of talent
family `807`, druid class ownership, exact inactive TC edges, absence of AC
learn edges, script bindings on both parents and both Bear forms, singleton
helper chains, effect types/amounts, targets, exact attributes, stances and visibility. Skills,
trainers, extra teachers, prerequisites, helper scripts and outgoing helper
dependencies cannot provide alternative authorization. Paired metadata changes
are rejected when they depart from the reviewed effect contract. A changed
contract reports `INCOMPATIBLE_WORLD_TALENT_AURA`.

Both specs may select different ranks, or share a rank. Availability remains
the exact union of selected owner masks; an inactive spec never authorizes an
active-spec helper. Existing enabled/disabled parent checks still apply.
Explicitly persisted helper rows block as `UNSUPPORTED_AURA_HELPER_SPELL_ROW`,
including disabled rows and rows without ownership; this policy does not delete
or reinterpret them. Overlapping Nurturing Instinct world relationships and
other world-only dependencies require their own review.

In reverse migration, retain both talent groups and persist only the active
selected direct parent as required by TC's reviewed loader. TC then restores
its inactive dependent helper natively; no helper row is persisted and no
lower or higher direct talent rank is inferred. Inactive groups retain their
talent ownership for native spec activation.

Provenance records `TC_WORLD_TALENT_AURA` derivations and
`authorization.world_talent_aura`: exact parent, TC active/dependent semantics,
AC script/form callbacks, lifetime and target representation
(`AC_SELECTED_TALENT_AURA` or `TC_NATIVE_DEPENDENT_RESTORE`). Expected-set and
runtime-owner validation reject persistent helpers and changed spec ownership.
The policy/profile enter existing input, expected-result and checkpoint hashes;
transaction, resume and rerun behavior is unchanged.

Both v2 manifests additionally protect `SpellAuraEffects.cpp`, including native
stance loops. The configured consumers match the retained TC/AC pins; neither
revision is substituted. Keep v1 and `PROFILE_APPROVAL=UNREVIEWED` unchanged.
Use a new migration toolkit/run with fresh target/control schemas. Retain
earlier preparation toolkits with their archives for their original restoration
contracts; this change requires no additional preparation SQL.

The focused harness executes protected TC dependency/stance bodies and AC
talent/stance/apply/remove bodies with mocked state/aura dispatch. Synthetic
fixtures cover ranks, specs, missing ownership, drift, stored helpers and
semantic round trips. This is consumer verification, not gameplay acceptance.
In staging check Cat/Bear/Dire Bear with rank 1, rank 2 and no selected talent;
switch specs in and out of form, relog, save and restart. Verify movement/dodge
effects, removal of stale helpers, unchanged talents/skills/profession slots
and no helper spell deletion/correction logs. Record every unexecuted check
as NOT TESTED alongside the five acceptance gates below.

### Flight Form and existing riding

`spell-state-v7` requires riding skill `762` to have the native secondary
category `9` in both effective catalogs. The former class-category `7` check
rejected the real Flight Form dependency despite a valid relationship and
stored skill. Synthetic riding fixtures now use category `9` too; categories
`7` and `11`, and source/target category disagreements, are rejected. Both
native `IsPrimaryProfessionSkill` functions exclude secondary skills from
primary profession slots. The category is recorded in dependency provenance;
all existing skill-value/cap and higher-anchor restrictions remain. Start a
fresh migration run with new target/control schemas after this policy/profile
change, and retain the old preparation toolkit and archives for restoration.

`spell-state-v5` includes a narrow reviewed world-dependency contract. Pinned
TC `AddSpell` restores non-autolearned `spell_learn_spell` children during
loading, including the active `33943 -> 34090` edge when present in the actual
source world. Its known Flight Form anchor may itself be a verified predecessor
of stored Swift Flight Form. Neither a trainer entry nor a skill row alone
authorizes this dependency; an absent world edge derives no riding spell.

AC lacks this world learn map. The transform persists Expert Riding `34090`
and the agreed `33388 -> 33391 -> 34090` prefix. The rule requires an ordinary
druid anchor and ordinary riding ranks in both specs, reviewed effects/visibility,
matching source/target rank and skill metadata, and an existing riding skill at
`225/225`. An existing `300/300` skill also qualifies only with an independently
known higher riding anchor `34091`; that anchor is never inferred from the form.
Missing, insufficient or nonstandard skill states block. Existing talent,
script, cycle, race/class, skill-cap and profession-slot checks still apply.

The protected loaders use the maximum of existing and learned riding values/caps;
the reviewed SKILL cast handler has no additional skill write. Lower riding rows
therefore reconstruct known TC state without raising these existing values/caps.
`spell-reconstruction.tsv` and committed provenance retain the world parent,
child, path, stored skill and `TC_WORLD_LOAD_PERSISTENT_RIDING` contract. Reverse
conversion preserves these ordinary chains through the existing exact expected
set checks. No source cleanup or talent reset is required for this contract.

Use a fresh migration toolkit copy, run ID and new target/control schemas after
this policy/profile change. Do not resume an earlier run with changed code.
Retain the old preparation toolkit and all cleanup archives for guarded restore;
its sealed inspections are tied to their original metadata profile. This change
does not itself normalize temporary talent predecessors or complete native
gameplay acceptance. Profile approval stays `UNREVIEWED`.

### Reviewed native passive talent ranks

`spell-state-v6` adds a separately reviewed representation policy for four
talent families: Primal Fury (801), Will of the Necropolis (1959), On a Pale
Horse (2039) and Blood Gorged (2034). The profile enumerates every selected
parent, exact learned child and all seven passive chains. It does not apply
to ordinary trained spell ranks or arbitrary temporary chains.

TC can retain superseded lower internal passive spell entries. AC adds only
the exact selected child temporarily, removes it on talent/spec removal and
excludes it from `_SaveSpells`. Same-caster passive ranks do not stack; the
selected exact child supplies the active aura. This policy explicitly accepts
AC's native internal representation while preserving selected talents and their
specialization ownership. It does not claim identical TC/AC `HasSpell` results
for superseded internal IDs. Ordinary trained rank reconstruction is unchanged.

Both cores must agree on the reviewed talent identities, rank ordering,
self-targeted learn children, selected effect data, stance/aura-state gates and
proc effects. All chain members must remain hidden passive aura-only spells,
without skills/professions/riding, extra teachers/dependencies, prerequisite
consumers or trainer offerings. The explicit Will of the Necropolis parent
`[DUMMY, LEARN, NONE]` stores the threshold read by its reviewed aura callback;
its full selected effect data must agree. Other parent effect changes block.
Unknown scripts, mixed child effects, cycles and incompatible metadata block.

Each spec authorizes its exact passive child independently. A higher passive
rank is not authorized merely because the lower rank is selected. The verified
TC prefix supplies a separate source-state mask for checking stored TC flags;
valid superseded predecessor rows are omitted from the AC spellbook and retained
with their original flags in the owning child's provenance. Disabled conflicts,
unowned higher ranks and unexplained inactive states remain blockers. No source
rows, talent selections, points, skills/caps or profession slots are changed.

Reverse migration stores active exact children and active direct talents.
TC restores the passive prefix itself; inactive children remain runtime-owned
through the unchanged talent groups. Persisting an inactive higher child could
disable a lower active rank during TC loading, so it is deliberately excluded.
This preserves safe native spec switching without guessing disabled rank rows.

`spell-native-passive-ranks.tsv` is regenerated from committed control data.
It records exact owners/masks, TC known masks, source predecessor flags, native
lifetime and target representation. Exact persistent-set and runtime-owner
validation also reject leaked passive rows and broadened talent masks. Profile
and policy hashes bind expected sets, checkpoints, resume and reruns. Both
unapproved v2 manifests now also protect `SpellAuras.cpp`; pins and v1 remain
unchanged. Existing migrations require fresh target/control schemas and a new
run. Native gameplay, save/relog/restart and release gates remain mandatory.

## Reviewed cooldown, proc and encounter callbacks

The metadata reader resolves TC's reviewed template registrations by exact
implementation and argument tokens: PvP trinket/WotF shared cooldown aliases
use `72752`/`72757`; the two T4 warlock aliases use `37378`/`37379`.
These callbacks cast cooldown/proc spells rather than learning spellbook rows.
Unknown template aliases stay blocked; mismatched reviewed arguments or
implementations and mutating implementations stay unsupported. The general
legacy-constructor and ordinary registration policies are unchanged.

AC's `spell_black_template_free_friend` is reviewed separately. It prevents
the default hit effect and removes control-impairing auras from a present target.
Only this handler is approved from the newly protected Black Temple instance
file. Other handlers in that file remain unreviewed. The complete file matches
the retained pin and AC staging reference; the pins are unchanged.

AC's `spell_teron_gorefiend_shadowy_construct` (`40326`) is also reviewed
from the already protected Teron encounter file. Its `Load` accepts creatures
only; applying the aura sets immunities, combat/threat and casts stun `41421`.
It neither learns nor removes spells. The supplied spell is a non-passive dummy
aura, without teaching effects. Preserve only an otherwise eligible stored
`40326`; never grant the stun or additional encounter abilities. Other Teron
handlers still require their own review. The complete file matches the retained
AC pin and staging reference. A compiled harness executes its exact load/apply
bodies with recording sinks, including null, friendly and hostile player
references; this does not establish gameplay parity.

The supplied DBCs make known WotF non-passive, the T4 set bonus a passive dummy
aura with a proc callback, and Free Friend non-passive. Native loading does not
execute the WotF/Free Friend cast callbacks or a T4 combat proc. Migration
preserves the legitimate stored spells and existing racial skill; it grants no
cooldown/proc spells, talents or encounter abilities from these callbacks.
Existing race/class, missing-skill and disabled-state guards still apply.
This is spell ownership/load compatibility, not full gameplay parity of cooldown
or set-bonus mechanics. Compiled callbacks use recording sinks, not a worldserver.

## Native aura and skill representations (`spell-state-v4`)

Nurturing Instinct (`33872`/`33873`) has a reviewed contract for the
`spell_dru_nurturing_instinct` binding in both worlds. TC casts helper aura
`47179`/`47180`; AC adds that exact helper temporarily and removes only temporary
spells when the owning aura ends. Expected rows use disposition `AURA` and
record the selected owner, specialization mask, exact helper and script mode.
They produce no persistent `character_spell` rows in either direction. Parent
selection remains in `character_talent`; reverse conversion retains only its
active direct talent in TC's stored spellbook where required.

Casting alone does not call TC's spell-learning reconstruction. In script-only
worlds, selecting rank 2 therefore does not establish a known helper rank 1.
The additional TC world-learning case is covered separately below. Different
selected ranks in the two specs retain independent AC masks.
Stored Nurturing helper rows block as `UNSUPPORTED_AURA_HELPER_SPELL_ROW`;
these need separate review instead of being silently deleted or enabled.
Mismatched bindings or effective parent/helper effects, visibility, stance or
talent ranks also block. Other scripts are not approved by this exception.

### Nurturing Instinct world helpers (`spell-state-v9`)

Some TC worlds also have the exact inactive, non-autolearned edges
`33872 -> 47179` and `33873 -> 47180`. This is a second mechanism alongside
the scripts above. TC's `AddSpell()` learns helper rank 1 before rank 2, with
inactive visibility and dependent persistence flags. Its stance loop can cast
both known hidden ranks in Cat Form. The protected same-rank aura exclusion
prevents these non-passive healing-received helpers from stacking.

AC's Nurturing script adds only the exact selected helper as temporary state.
Its native stance gate/loop applies that helper in Cat Form; native removal
and saving remove/omit the temporary entry. The converter delegates only that
exact rank as `AURA`, preserving the selected owner's mask. Rank 2 alone never
creates an AC rank-1 entry. Differing ranks in two specs keep separate masks;
the callback's internal mask `3` does not confer ownership in the other spec,
because only the active talent aura owns its temporary lifetime.

The profile verifies the whole two-rank family: talent/class identity, both
script bindings, exact TC edges/flags, helper rank order, attributes, stance,
aura gates, effect magnitudes/targets, duration, item requirements and family
masks. Unexpected learning, prerequisites, skills, trainers or scripts on a
helper block, including on the lower TC-only predecessor. Partial or changed
world routes block as `INCOMPATIBLE_WORLD_TALENT_AURA`; unrelated dependencies
retain `UNSUPPORTED_DEPENDENT_LEARN`. Script-only worlds retain their prior
cast-only behavior.

Provenance records `TC_WORLD_NATIVE_RANKED_TALENT_AURA`, the exact selected
owner/mask, TC dependent flag and known predecessor list, native lifetime and
direction-specific representation. No helper is persisted in either direction.
Reverse conversion stores only the active selected direct parent; unchanged
talent rows retain the other spec and TC restores its native dependent prefix.
Stored helper rows remain blocked, including unowned or disabled rows; they
need a separately reviewed preparation policy. Skills, caps, profession slots
and talent ownership are preserved.

This policy changes metadata/checkpoint hashes. Use a new migration run with
fresh target/control schemas; retain old cleanup toolkits and archives for
their original guarded restoration. Isolated consumer and MySQL tests do not
establish gameplay acceptance. On staging, test both selected ranks, different
ranks in each spec, Cat entry/exit, spec switches and relogs: only the active
selected healing-received helper should apply, without stacking a lower rank.
Repeat after save/restart and confirm unchanged talents, skills and profession
slots. These checks and the five general gameplay gates remain **NOT TESTED**
until performed against the target worldserver. Approval remains **UNREVIEWED**.

TC's enabled Runeforging dependencies `53428 -> 53341` (Cinderglacier) and
`53428 -> 53343` (Razorice) can be restored by both native skill loaders. The
converter delegates only these reached children as `SKILL`: the known parent,
existing Runeforging skill `776` exactly `1/1`, eligible class/race, acquisition
method `1`, threshold `1`, no superseding spell, matching TC/AC ability rows and
reviewed effects must all agree. Both specs retain ordinary availability.
Native TC restores dependent spells; AC restores temporary spells from skills.
Neither child needs a persistent row in either direction. Provenance records
the parent and both native ability IDs. A child already stored and one derived
from the parent merge deterministically without additional grants.

This is not a general recipe or skill-reward scan. Missing Runeforging skills,
nonstandard values/caps, other world-only dependencies (including riding),
unknown scripts and incompatible metadata retain their blockers. Migration
inserts no skill and changes no profession slots, recipes or caps. Native skill
loading remains responsible for its normal rewards.

`spell-state-v4` changes policy/toolkit hashes and adds control dispositions.
Use a new toolkit, fresh target/control schemas and a new run. Keep the cleaned
source and its retained cleanup archives. An in-place staging repair remains a
separately reviewed task.

## Dual-spec teaching wrapper (`spell-state-v10`)

TC can retain hidden teaching wrapper `63680` in `character_spell` while omitting
its dependent spec-switch buttons `63645` and `63644`. Its non-autolearned load
map restores those buttons. The reviewed AC `_addSpell()` refuses persistent
spells containing learn effects, so copying the wrapper would lose the buttons.
This is a verified representation conversion, not a general learn-spell bypass.

For an enabled, active stored TC `63680` anchor, the converter verifies the exact
two self-target learn effects, effective load edges, attributes, effect values,
targets, no rank/talent/script/prerequisite dependencies, and both buttons'
ordinary Generic skill associations. The character must already have exactly
two specs and existing Generic skill `183`. Missing skills, single-spec state,
or non-native Generic values/caps block. The character's level is fingerprinted;
the existing skill must equal native `level × 5` for both value and cap at a
verified level from 1 through 80, with matching native always-max skill ranges.
The converter preserves those rows; it never repairs or clamps them. Unsupported
disabled/inactive wrapper history, changed mechanics and unexpected routes block.
Equal source/target mutations do not satisfy the explicit profile contract.

The target receives only the two persistent buttons, with ordinary mask `3`.
They contain cast-only activate-spec effect `162`; loading them casts neither
button. The migration never executes learn, activate-spec or spec-count effects,
and never derives purchase spell `63624` (effect `161`). Talent groups, active
spec, selected talents, action bars and all skill values/caps retain their normal
preservation checks. The pinned AC trainer consumer recognizes the wrapped
teaching state through both known buttons, without a stored wrapper.

The original stock wrapper key and flags are retained as committed control
disposition `TEACHER`, together with the exact children, existing spec/skill
context and `effects_executed=false`. It emits no target spell row. Report
`spell-consumed-teachers.tsv` is regenerated from committed provenance alongside
`spell-reconstruction.tsv`; both commit with the corresponding GUID checkpoint.
Dedicated validation requires the exact persistent buttons and existing dual-spec
context, and rejects leaked wrappers or incorrect masks. General exact talent,
skill and unrelated-data validation remains required.

Reverse conversion preserves the two ordinary buttons. It does not infer that
AC ever stored `63680`, and never grants that wrapper back to TC. A stored AC
wrapper remains blocked because the reviewed loader cannot legitimately retain
it. Thus the semantic round trip is canonical button state, not a byte-for-byte
restoration of the original wrapper row. Its original stock row remains in the
forward control/report evidence; source databases remain unchanged. Unsafe or
unreviewed teaching spells retain the blocking policy; no blanket archive
override is added.

The new control enum, metadata and policy require a fresh migration run with
fresh target/control schemas. Existing staging targets need a fresh migration;
in-place repair is separately reviewed. Keep old preparation toolkits/archives
for their original restoration guards. Approval remains **UNREVIEWED**.

On staging, check both pre-owned specs: both switch buttons work, active builds,
talent points and action bars remain correct, and no purchase/count spell is
triggered. Confirm unchanged Generic/other skills and repeat after save, relog
and restart; inspect logs for teaching-spell rejection or skill corrections.
These checks, and the five general gameplay gates below, remain **NOT TESTED**
until performed on the actual target worldserver.

## Checkpoints, evidence and validation

Preflight streams numeric character spell/talent/skill state in GUID order and
captures input hashes. Relevant world layouts/rows and DBC bytes are fingerprinted.
Same-count changes are detected. Every later command rechecks captured spell
inputs before accepting a completed phase or resuming work. Changed inputs or
toolkit identity require fresh targets/control and a new run.

Control tables retain immutable expected rows, input/expected hashes and
committed provenance. Each GUID chunk commits target spell rows, provenance
and completed checkpoints in one transaction. Validation checks exact persistent
spell rows/masks, target talent ownership for `AURA`, and the unchanged skill
plus verified known parent for `SKILL`. Native dispositions are checked separately
from stored-row counts. A pre-commit failure rolls all
three back; a post-commit interruption can resume without duplicate rows.

Private reports include:

- `spell-fingerprints.tsv`: metadata and source-input SHA-256 evidence.
- `spell-expected.tsv`: preflight reconstruction and original flags/proofs.
- `spell-state-blockers.tsv`: incompatible character keys, reason codes and details.
- `spell-script-review.json`: all script bindings on stored spell and selected
  talent IDs of existing source characters, with per-ID character counts for
  each source category, per-binding review status/reason and input fingerprint.
  It scans both cores independently of the first character failure, including
  all bindings on an ID. Selected groups count once per character. A
  `COMPLETE` report means this limited inventory finished; it excludes
  derived-only IDs and does not establish ownership, satisfy correction/skill
  guards, approve cleanup or make the migration ready. Failed reads leave
  `INCOMPLETE`. Produced on successful and blocked preflights without extra
  database queries; the migrator copies it before discarding temporary files.
- `spell-metadata-errors.tsv`: failed query input, reason code and database error;
  no spell compatibility conclusion was possible.
- `spell-reconstruction.tsv`: committed rows, masks, derived/runtime dispositions
  (including `AURA` and `SKILL`, which intentionally emit no spellbook row)
  and source-anchor paths; regenerated from control data. Provenance names the
  rank root, talent owner IDs/masks, prerequisites and mask policy, alongside
  original source flags, so specialization reductions have an explicit reason.
- `spell-drift-fingerprints.tsv`: observed input evidence when a snapshot changes.

The console prints reason counts and the full blocker-report path. The current
codes and their next investigation steps are documented in the
[spell reason-code reference](spell-reason-codes.md), including the distinction
between temporary runtime spells and temporary diagnostics. The current audit
records the first failure per character; these counts describe affected
characters, not an exhaustive list of bad rows. A script/correction guard can
mean that compatibility has not been reviewed; it does not prove corrupt data.
Use the script inventory to review bindings hidden behind earlier failures
without repeatedly running preflight to discover one more stored script.
For several remaining categories, the preparation console's
[saved blocker context command](cleanup-console.md#review-a-saved-migration-blocker-report)
captures all spell flags, both talent groups, skill state and TC world metadata
for every reported GUID together. It makes no source changes and is not another
migration preflight. It cannot establish target overlay compatibility, exhaustive
failures or a cleanup selection; it supplies the full context needed to review
first-character failures in groups.
Print unresolved bindings from the saved JSON (replace the path):

```bash
python3 - /path/to/report/spell-script-review.json <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
print('inventory_status:', report['status'])
for row in report['bindings']:
    if row['status'] == 'REVIEW_REQUIRED':
        print(row['core'], row['spell'], row['script'], row['stored_characters'],
              row['talent_characters'], row['reason_code'], sep='\t')
PY
```

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

A clean `audit --scope talents` does not validate `character_spell` ownership.
These stored-spell blockers do not mean the earlier invalid `character_talent`
cleanup failed. An unowned-talent reason must be split by the original `disabled` flag. Disabled
history is unavailable in TC; enabled unowned rows may affect current abilities.
A different stored direct rank than the selected rank is also a separate conflict.
None authorizes assigning new talent points or masks. Enabled stored Nurturing
helpers without selected owners remain unsupported; they are not the legitimate
omitted lower ranks addressed by this migration.

The first-failure report is not an exhaustive source cleanup selection. The
source audit reviews direct talent rows, but does not replace a complete semantic
review of indirect talent children and their rank chains. The current cleanup
console has no blanket spell-history deletion policy. Any such repair needs
its own exact selection, full-row archives, ownership/skill preservation evidence,
reviewed apply/restore and current source fingerprints. The migrator keeps its
blocking policy and performs no source cleanup.

A separate source-preparation policy now implements those safeguards for a
conservative subset of disabled, unselected **direct** talent ranks. See
[disabled-history archives](cleanup-console.md#archive-eligible-disabled-direct-talent-history).
It defers selected families, enabled conflicts, indirect/runtime dependencies,
alternate routes, unreviewed scripts and pending native resets. The default v1
policy defers every scripted family; explicit v2 `--include-reviewed-scripts`
accepts only complete families with the protected `NO_SPELLBOOK_MUTATION`
contract and no other exclusion. Both modes record exact selected/deferred rows
and preserve talent ownership, skills and login flags. Separate v3
`--include-inert-relations` can archive isolated wholly disabled direct/rank/
dependent groups, with no enabled related spell, selected talent, conflicting
incoming route, profession/skill effect or unsupported metadata. It records
direct and related removals separately; it does not resolve enabled unowned
spells or pending resets. Explicit v4 `--include-reviewed-routes` adds exact
Berserk/Blast Wave teaching wrappers and the inert shaman `30798` root-only
exception. It preserves shared spell `674` and skill `118` in every state;
remaining shared availability is still subject to normal migration ownership
and skill guards. This changes no migration
rejection rule and never activates a disabled spell. Use the retained original
source plus these archives for rollback; migrate edited preparation data only
into fresh target/control schemas.

Separate preparation policy v5 `--selected-rank-history` can archive disabled
direct ranks selected by neither group when another rank of that family is
selected. It treats existing talent ownership as authority, preserving selected
spell flags, talent points and skills. It never chooses the highest rank or
inserts missing selected counterparts. Enabled unselected siblings, dependencies,
skill effects and ambiguous metadata defer the family. TC's direct-rank removal
before the disabled return makes this an explicit ownership-based repair;
identical behavior to the conflicting source spellbook is not asserted. It is
not ordinary lower-rank reconstruction and does not relax migration checks.

Resolving one blocker can expose another for the same character. A successful
focused regression does not clear every record in a production-sized source.

Preparation policy v6 `tc-disabled-unselected-trained-talent-history-v6` addresses
disabled trained ranks whose direct talent roots are absent from persistence.
It uses sealed full-context evidence and verified TC rank/dependency groups,
preserves both selected builds, enabled availability and skills, and records
absent roots without grants. It retains all route/script/skill/cycle guards and
rechecks complete captured semantic state before producing exact-row archives.
This is source history cleanup; it does not relax the migrator's rejection of
unsupported temporary ranked talent children or other unsafe representations.

The final report summarizes persistent, runtime-owned, direct-talent, native
aura and native skill-reward rows separately.
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

Also test each Nurturing Instinct rank in its owning spec: change forms, switch
specs, remove the talent and relog. Verify the native helper effect follows the
owner and never survives removal. Verify Cinderglacier/Razorice availability and
use after relog/restart, unchanged Runeforging `1/1`, and no loading quest credit.
Record these native checks separately from the compiled handler results.

Retain reports and the untouched source for rollback. No existing staging or
production database is repaired automatically. Native smoke tests and two
production-sized isolated rehearsals remain mandatory before profile approval.
