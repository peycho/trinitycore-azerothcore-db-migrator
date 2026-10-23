# Reviewed talent ownership repair

This separate preparation policy treats existing `character_talent` selections
in **both** specs as authoritative. It can archive/remove conflicting spell rows
**including enabled spells**, deliberately changing availability. Old disabled
history policies retain their original restrictions. Use only on a stopped,
backed-up preparation copy; no staff exemption or migration bypass is introduced.

## Opt-in selected direct passive ranks

`tc-selected-direct-passive-authority-v1` corrects a saved direct passive rank
that disagrees with the character's selected lower talent. It covers only
Improved Charge, Deflection, Divine Intellect, Improved Vampiric Embrace and
Blade Barrier, using verified DBC rank order and matching effective TC/AC
mechanics. For example, Divine Intellect `20209` is rank 4 and `20208` is rank 5;
numeric spell ID order is never used as rank order.

```bash
python3 console plan talent-ownership --migration-inspection latest --selected-direct-passives --preview
python3 console plan talent-ownership --migration-inspection INSPECTION_ID --selected-direct-passives --expect-rows SELECTED_ROWS
```

Use the current inspection and the preview's `selected_rows`, then the normal
prepare/status/review/apply/status workflow below. Fresh imports get fresh
sessions, inspections and calculated selections, not old GUID lists or counts.
Review `selected-passive-review.json`, `selected-rows.tsv`,
`selected-passive-native-proof.json` and every deferred reason.

Every retired row must be an enabled higher **direct** passive rank, unselected
in both specs. The active spec must select a verified lower rank of that same
talent. Both saved builds and their ranks remain unchanged; any selected rank
already stored must have consistent flags. Talent prerequisites are checked.
Non-passive talents, learned children, scripts, independent/default/skill-reward
routes, malformed or mismatching metadata, foreign classes, online characters,
invalid selections and pending native resets defer. Earlier ownership policies
keep their existing anchor requirements.

This deliberately corrects the passive effect to the selected rank. TC does
**not** recursively restore lower direct talent ranks, and its talent loader
records ownership without casting a missing selected spell. AC's protected
`_LoadTalents -> addTalent -> _addTalentAurasAndSpells` path casts the exact
active selected passive, subject to native stance/state gates; it does not add
a persistent spellbook row or a trainable higher rank. Other specs keep their
own selected effects. No SQL spell insertion, flag rewrite, talent/skill/cap,
profession-slot or login-flag change occurs. Keep TC stopped between this repair
and migration: the prepared source is not a repaired running TC realm.

Both read-only worlds, DBC directories and reviewed core source directories
are required. Explicitly configure TC `PlayerStart.AllSpells=0` and AC
`PlayerStart.CustomSpells=0` through the existing preparation configuration
assertions. Do not assume the target setting merely from an expected default.
The existing two-world archive transaction protects complete custom originals,
exact fractional fingerprints, full captured scope, metadata/layout/code and
expected results. Apply/checkpoint commit together; interruption rolls back;
reruns verify committed state. Exact restore refuses later drift. The source
writer needs the existing explicit `INSERT, DELETE` privileges on
`character_spell`; no grants are added automatically. Preserve prior toolkits
for prior archives and restore later batches first.

The console supplies acknowledgements. Direct SQL additionally needs:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';
SET @direct_passive_ack='SELECTED_LOWER_DIRECT_PASSIVES_AUTHORITATIVE';
SET @eligibility_tc_all_spells=0;
SET @eligibility_ac_custom_spells=0;
```

Review codes are stable report values:

| Code | Meaning |
| --- | --- |
| `DEFER_SELECTED_DIRECT_PASSIVE_CONTRACT` | Outside the five exact contracts, a retired rank is selected in either spec, its flags are unsupported, or the verified lower active selection/paired metadata is absent. Do not infer a replacement. |
| `DEFER_SELECTED_DIRECT_PREREQUISITE` | A selected talent prerequisite is missing or insufficient in that same group. No prerequisite or talent points are granted. |
| `DIRECT_PASSIVE_ACK_INVALID` | The console's sealed authority acknowledgement differs. Review the package rather than bypassing it. |
| `DIRECT_PASSIVE_POLICY_DRIFT` | Selector, ownership consumer or acknowledgement changed since planning. Use the retained original toolkit for that archive, or generate a new candidate. |

No core pins, protected manifests, migration policy or v1 profile change for
this preparation policy. Protected consumer tests use mocked catalogs/state;
full gameplay stays **NOT TESTED** and release approval **UNREVIEWED**. Staging
must check the exact selected passive effects in each spec, native stance gates,
save/relog/restart, points, professions and skills.

## Opt-in already-known selected passive ranks (v5)

`tc-selected-known-passive-rank-rekey-v5` addresses a different state: the
active selected talent has an enabled higher passive child stored, but its
correct lower child is absent from persistence. TC already reconstructs that
lower rank when loading the higher row. Deleting the higher row alone would
remove the source anchor. This policy updates its `spell` key to the exact
selected **lower** child instead.

Only the existing Primal Fury, Will of the Necropolis, On a Pale Horse and
Blood Gorged contracts qualify. Each chain must have exactly one enabled
`active=1, disabled=0` child anchor, an absent destination that is a verified
strict predecessor, and the active selected parent already enabled in the
spellbook. Parents alone never justify a missing child. Both selected builds
remain unchanged, including a higher rank selected in the inactive spec; native
AC activation restores that build's exact children. No direct talent rank,
higher child, recipe or unrelated spell is inferred.

```bash
python3 console plan talent-ownership --migration-inspection latest --native-passive-rekey --preview
python3 console plan talent-ownership --migration-inspection INSPECTION_ID --native-passive-rekey --expect-rows SELECTED_ROWS
```

These commands use the same sealed inspection and prepare/status/review/apply/
status workflow as other ownership policies. `--expect-rows` is the preview's
`selected_rows`; it counts **key changes**, not deletions. Review
`spell-rekeys.tsv` and `ownership-native-proof.json`: each old anchor, known
predecessors, active selected owner, destination, both selections and retained
flags are recorded. Missing/disabled/inactive anchors, multiple stored children
in a chain, destination collisions, unsupported metadata/routes, invalid builds,
online characters and pending resets defer the entire family. Earlier modes
retain their exclusions.

The source `character_spell` table must contain exactly the stock four columns.
Custom spell-specific columns are blocked rather than moved to a different
spell ID without a reviewed interpretation. Custom fields on other archived
tables remain preserved and fingerprinted. SQL updates only `spell`; row counts,
flags, talent selections, spec count, skills/caps, profession slots, login flags
and unrelated data remain unchanged. Unsupported higher spell availability is
retired deliberately; the selected lower child was already known before repair.

Preparation archives all affected originals. Apply and its checkpoint commit
in one transaction. Expected mappings, complete expected rows, source/world
content and layout, DBC/core/selector hashes and fractional values are guarded.
Reruns verify the committed result. Restore updates each new key back to its
original key and requires the complete affected result to remain unchanged.
Keep the original toolkit for restoration; restore later batches first.

The source writer needs only this additional column privilege for this policy;
substitute its actual account and schema, using a database administrator:

```sql
GRANT UPDATE (`spell`) ON `preparation_characters`.`character_spell` TO 'cleanup'@'localhost';
```

No source grant is added automatically. The console supplies acknowledgements;
direct SQL also requires:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';
SET @talent_native_rekey_ack='ONLY_ALREADY_KNOWN_SELECTED_LOWER_PASSIVES';
```

Fresh imports use new sessions and calculated selections/counts, never old
mapping files or approvals. This policy does not change the core pins, semantic
manifests, migration rejection rules or **UNREVIEWED** release status. Native
consumer tests use mocked catalogs/state; gameplay remains **NOT TESTED**.

## Opt-in reviewed paladin area-aura aliases (v4)

`tc-unselected-reviewed-aura-alias-retirement-v4` retires isolated, unselected
talent history for Improved Devotion Aura, Improved Concentration Aura,
Sanctified Retribution and Swift Retribution. It explicitly permits enabled-row
retirement under the existing selected-talents-authoritative choice. Neither
specialization may select any rank in the family. Earlier modes keep their
script-alias exclusions.

These four stock script names are registered aliases of the protected
`spell_pal_improved_aura` class, with specific constructor arguments. They are
not missing script implementations. The exact registration, enum/helper ID and
protected `ScriptMgr.h` constructor-forwarding consumer are checked. Its area
aura helpers must match the reviewed effect/target/aura mechanics, be absent
from the stored spellbook and have no learning, skill, script or ownership
routes. Unknown aliases, selected families, modified mechanics, independent
routes and the usual pending-reset/online/skill/default protections still defer.

```bash
python3 console plan talent-ownership --migration-inspection latest --reviewed-aura-aliases --preview
python3 console plan talent-ownership --migration-inspection INSPECTION_ID --reviewed-aura-aliases --expect-rows SELECTED_ROWS
```

Use the normal prepare/status/review/apply/status sequence below. Inspect
`ownership-native-proof.json`: `script_alias`, `implementation`,
`constructor_argument`, `area_aura_helper`, empty selected ownership and exact
retained flags explain every accepted family. SQL inserts no spells, rewrites
no flags and preserves all `character_talent` rows in both specs, skills/caps,
profession slots, character/login state and unrelated data. Complete custom
originals, exact fractional source/world hashes, DBC/code/layout guards, atomic
apply/checkpoint, interrupted rollback, reruns and exact restoration apply.

The console supplies acknowledgements. Direct SQL additionally requires:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';
SET @talent_aura_alias_ack='UNSELECTED_REVIEWED_AURA_ALIASES_ONLY';
```

Fresh imports need new sessions and newly generated selections/counts. After
source edits, capture fresh evidence locally before planning; offline derived
evidence is not a substitute for the live planning guard. No exported bundle is
required after every known batch during development. Preserve earlier toolkits
for their exact restores. Core pins, manifests, metadata profile, migration
policy and **UNREVIEWED** approval remain unchanged. Native factory/callback
tests use recording sinks; full gameplay is **NOT TESTED**.

## Opt-in retained native passive prefixes (v3)

`tc-selected-native-passive-prefix-repair-v3` addresses disabled lower passive
rows that conflict with an already enabled, authorized higher rank. It uses only
the existing reviewed contracts for Primal Fury, Will of the Necropolis, On a
Pale Horse and Blood Gorged. Neither earlier ownership mode gains this exception.

```bash
python3 console plan talent-ownership --migration-inspection latest --native-passive-prefixes --preview
python3 console plan talent-ownership --migration-inspection INSPECTION_ID --native-passive-prefixes --expect-rows SELECTED_ROWS
```

The exact selected roots and both builds remain authoritative. Every retired
authorized prefix must be a disabled **non-talent** predecessor of a retained
enabled higher anchor in that same verified family. The anchor itself must
already be authorized in the active spec and cannot be another retirement
candidate. TC `AddSpell` reconstructs its predecessors; this policy does not
assume that `_LoadTalents` or `_LoadSpells` casts a learn-effect talent to restore
a missing child. Missing/disabled anchors, wrong selected-root flags, unsupported
families, independent/default/skill/shared/script routes, malformed metadata,
pending resets and online characters still defer the entire family.

After that proof, the policy also retires other conflicting history in the same
family, including **enabled higher children outside both selected builds**.
Review that availability change separately from the disabled prefixes; it never
raises the selected talent rank or grants a higher rank. No direct talent rank
is expanded or removed. SQL inserts no spell, rewrites no flags and changes no
talent selection, skill/cap, profession slot, spec count or login flag.

Use the prepare/status/review/apply/status sequence below. `--expect-rows` is
the preview's total `selected_rows`, including any enabled history retirement.
`ownership-native-proof.json` records `prefix_restore_anchors`,
`retired_prefix_flags`, selected spell/groups, authorization masks and retained
flags. A `PREPARED` batch has archived complete originals and changed no source
rows. Apply removes only the sealed exact selection; it does not execute login.

The console supplies the three acknowledgements. Direct SQL additionally needs:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';
SET @talent_native_prefix_ack='RETAIN_AUTHORIZED_HIGHER_ANCHORS';
```

Complete custom originals, exact fractional source/world fingerprints, layouts,
DBC assets and selector/numeric/world-reader fingerprints protect preparation,
apply and restore. Apply/checkpoint are atomic; failed or disconnected operations
roll back, reruns verify committed state, and exact restore refuses later drift.
Retain the original toolkits for previous archives. On a fresh import, start a
new session and capture new evidence; never replay an old package. Core pins,
protected manifests, migration reconstruction and **UNREVIEWED** approval stay
unchanged. Protected consumer tests use mocked state; full gameplay is still
**NOT TESTED**, including effects after spec switches, save, relog and restart.

## Opt-in unselected foreign-class families (v2)

`tc-unselected-foreign-talent-retirement-v2` is a separate, narrower mode:

```bash
python3 console plan talent-ownership --migration-inspection latest --foreign-class-families --preview
python3 console plan talent-ownership --migration-inspection INSPECTION_ID --foreign-class-families --expect-rows SELECTED_ROWS
```

Use the normal prepare/status/review/apply/status sequence below with the new
candidate ID. Preview creates no SQL package or active batch. `--expect-rows`
means **selected_rows**, including enabled and disabled removals. This explicitly
retires foreign spell availability; it does not reset or infer a talent build.

Every direct talent rank in a qualifying family must belong exclusively to the
same other playable class. Neither specialization may select that family.
Full rank/learning/requirement closures must pass all existing independent-route,
skill/reward, profession/riding, custom-start, shared-owner, script and metadata
guards. Invalid selections, pending resets, online characters and unsupported
character state still defer. Same-class families stay outside this v2 mode;
default v1 retains its foreign-class exclusion.

**A foreign talent relationship does not make a shared spell invalid.** For
example, Dual Wield (`674`) is independently available to warriors and rogues
and is also taught by a shaman talent. V2 retains the skill/reward exclusions
and cannot remove that shared spell through its foreign shaman relationship.

`ownership-native-proof.json` records the character class, exclusive foreign
class mask, complete family talent ranks, empty selected ownership and exact
retained source state. Both selected builds, skills/caps, profession slots,
login flags and unrelated data remain unchanged; no spell is inserted and no
flag is rewritten. Complete originals, exact fractional source/world hashes,
metadata layouts, DBC assets and guard/selector fingerprints protect the batch.
Apply and checkpoint commit together; interruption and late failures roll back.
Exact restoration is available before gameplay or later conflicting edits.

The console supplies acknowledgements. Direct SQL also requires:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';
SET @talent_foreign_family_ack='UNSELECTED_FOREIGN_FAMILIES_ONLY';
```

No new server setting is required. Custom-start routes remain excluded even
when their configuration is disabled. Retain earlier toolkits for earlier
archives. This preparation policy changes neither core pins/manifests nor
migration validation; native gameplay remains **NOT TESTED**, release approval
**UNREVIEWED**. A fresh final migration preflight must cover all characters;
saved context only covers the GUIDs named by its earlier blocker report.

## Preview and apply

Install the complete toolkit, retaining prior toolkits and archives. Continue
the current session; capture fresh context after source edits. An old report
supplies GUID scope only:

```bash
python3 console inspect-migration-blockers --report /path/to/spell-state-blockers.tsv --bundle
python3 console plan talent-ownership --migration-inspection latest --preview
```

Preview creates no SQL package or active batch and changes no database rows.
Inspect `talent-ownership-review.json` in the operation directory. It reviews
complete captured spellbooks, including conflicts hidden behind first failures;
counts may exceed old report examples. Candidates include deferred/unsupported
representations and are not all proven corrupt. Use **selected_rows**, not
reviewed_candidate_rows, as the exact expectation:

```bash
python3 console plan talent-ownership --migration-inspection INSPECTION_ID --expect-rows SELECTED_ROWS
```

Review the generated README, manifest, selected rows, ownership review,
relationship review/edges, `ownership-native-proof.json` and SQL. Native proofs
record exact selected spell/groups, authorization masks, retained flags and each
active child's retained source anchors. Use the new exact batch ID:

```bash
python3 console prepare --batch BATCH_ID
python3 console status --batch BATCH_ID
python3 console apply --batch BATCH_ID
python3 console status --batch BATCH_ID
```

PREPARED means selected rows remain stored and complete originals are archived.
APPLIED means exact selected rows are absent, not that a login/reset completed.
Failed or disconnected transactions roll back deletion/checkpoint together;
status and reruns verify the committed state.

The administrator creates a fresh archive. The writer needs source SELECT and
character_spell DELETE for apply, INSERT for exact restore. Source write grants
are never added automatically. Console actions supply the policy acknowledgement;
for direct SQL, set both before each action:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @talent_ownership_ack='SELECTED_TALENTS_AUTHORITATIVE';
```

## Representation and exclusions

`tc-selected-talent-ownership-repair-v1` removes exact conflicting rows. SQL
inserts no spells, rewrites no flags and changes no selected talents, points,
specs, skills/caps, profession slots or character/login fields. Unrelated tables
and action buttons are not rewritten. Retired trained history loses its stored
future respec/retraining state; retain the archive.

Unselected families require isolated verified TC rank/learning/requirement
closures and no independent learning, skill reward, custom default, profession
or riding route. Scripts/metadata must pass protected checks. Skill effects and
skill-modifying auras are excluded, including on absent members.

`NO_SPELLBOOK_MUTATION` alone is insufficient for this policy. Script classes
also require the exact protected TC implementation with no skill, profession,
talent-ownership or database-write calls in the class body. Unknown aliases and
unreviewed implementations defer. This check supplements the pinned-source
review; it is not a claim to prove arbitrary transitive C++ behavior.

Selected families require an already-enabled stored active selected root.
V1 supports isolated direct talents, reviewed native passive families (Primal
Fury, Will of the Necropolis, On a Pale Horse, Blood Gorged) and exact Fiery
Payback selected-child relationships. Spec masks merge by bitwise OR. Legitimate
TC lower passive prefixes and eligible stored trained ranks are preserved.
Native loading restores only authorized children from existing correct anchors;
it never raises a selected talent to match stale higher history.

TC `_LoadSpells` uses `loading=true` and does not recast non-passive learn-effect
talents. A retained parent alone is therefore insufficient: every active
authorized child must remain known through a retained enabled child row or
verified predecessor prefix. Missing child anchors defer. AC native selected
child loading is tested separately and cannot substitute for this source proof.

Missing active roots/child anchors, inconsistent owned-child flags, selected
prerequisite dependencies, unreviewed selected learning routes, pending reset bit 4, online
characters, unsupported race/class/level, foreign-class families, invalid
selections, cycles, shared ownership and metadata drift defer. No excessive
talent-point allocation is silently corrected. Source TC restoration evidence
does not establish target compatibility; normal two-world/DBC migration checks
still apply.

## Integrity, restore and repetition

Planning rechecks the complete captured semantic scope, including deferred
characters. Prepare/apply/restore verify full affected character/talent/spell/
skill originals including custom fields, exact selections, source/archive
schemas, world content/layout and result digests. Same-count drift is rejected.
The sealed package includes its selector hash; retain that toolkit and metadata.

Before gameplay or further edits:

```bash
python3 console restore --batch BATCH_ID
```

The inverse restores full removed rows, including binary/custom fields, refuses
affected-state drift and retains archives. Restore later batches first, in
reverse application order. After incompatible edits/gameplay, use the untouched
baseline rather than weakening guards.

For a fresh import, keep the old workspace/archives, restore the baseline, start
a **new session**, audit, capture fresh evidence and generate new plans:

```bash
python3 console init --label fresh-import
python3 console audit --scope all
```

Never replay old approvals onto a fresh import. Source edits require a new
migration with fresh target/control schemas. In-place target repair is separate.

## Validation and gameplay

Synthetic tests cover old-converter failure, both specs/different ranks, exact
children, preserved TC prefixes, no higher grant, immutable inputs and unsafe
routes. MySQL 8.4 covers custom originals, preview/count/deferred-scope and world
drift, SQL acknowledgements, late/disconnect rollback, reruns and exact restore
while talents, skills and unrelated data remain unchanged. Protected C++
consumers use mocked catalogs/state/database sinks.

Staging must still check talent effects/points in both specs, ordinary
ranks/trainers, casts, action buttons, professions/recipes/riding and skills/caps.
Repeat after save, relog and AC restart; inspect deletion/correction logs.
Gameplay remains **NOT TESTED** and release approval **UNREVIEWED** until the
existing acceptance gates actually pass.
