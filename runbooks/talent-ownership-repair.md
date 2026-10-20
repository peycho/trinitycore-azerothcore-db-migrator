# Reviewed talent ownership repair

This separate preparation policy treats existing `character_talent` selections
in **both** specs as authoritative. It can archive/remove conflicting spell rows
**including enabled spells**, deliberately changing availability. Old disabled
history policies retain their original restrictions. Use only on a stopped,
backed-up preparation copy; no staff exemption or migration bypass is introduced.

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
