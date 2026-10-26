# Replay preparation from an original snapshot

The input is a stopped restored original snapshot. Retain an untouched baseline;
the runner changes only the configured preparation copy. A partially cleaned
database is not required. For final cutover, freeze all source writers before
taking the final consistent snapshot; no live delta synchronization is provided.

The runner combines existing reviewed policy operations. It generates fresh
counts, selections, archives and checkpoints from current data. Historical GUID
lists, expected counts, batch SQL and migration checkpoints are never replayed.
The example recipe is a list of policy choices to review for the installation;
its existence does not grant production approval.

```bash
cp config/preparation-recipe.example.json preparation-recipe.json
python3 tools/replay-source-preparation.py \
  --config cleanup.ini --recipe preparation-recipe.json --output replay-review
```

Without `--apply-reviewed-recipe`, this prints the registered policies without
connecting to MySQL or creating an output directory. Remove unwanted policy IDs
from the recipe; arbitrary commands, unknown policies, duplicates and automatic
character resets inside the recipe are rejected. Individually reviewed unavailable-spec resets use the separate explicit CLI option below. Keep the order of the retained policies.

After reviewing the policy choices and stopped-copy configuration:

```bash
python3 tools/replay-source-preparation.py \
  --config cleanup.ini --recipe preparation-recipe.json \
  --output replay-01 --apply-reviewed-recipe \
  --migration-config migration.env
```

The output directory must be new. Credentials remain in the private configuration
files. Recipe execution uses the existing audit/write/admin roles and source
grants; it does not grant source privileges or import/drop databases. A new
cleanup session is created, and a private replay journal plus per-command logs
are retained. Omit `--migration-config` for a preparation-only rehearsal.

## Sequence and stopping conditions

1. Run character-state audits for talent/skill/history evidence. This scope
   includes characters, both talent groups, spells, skills and the effective TC
   spell catalog. It intentionally does not certify auth relationships, items,
   quests or other relational checks. No account rows are invented.
2. For each selected policy, capture fresh evidence over **all source characters**
   as required. `PREPARATION_SCOPE` entries in whole-source captures are review
   markers, not migration failures. Existing bounds remain: 40,000 characters
   and 5,000,000 captured semantic rows; excessive inputs stop without truncation.
   Inventory requirements are read for every policy candidate, with the existing
   per-character and total item bounds retained.
3. Derive exact counts from current evidence or the policy's preview. Verify the
   resulting policy, prepare originals, apply the batch and require SQL status
   `APPLIED`. All existing source/world/DBC/native, configuration, equipment,
   numeric and restoration guards remain active.
4. Invalidate cached evidence after every applied batch. Repeat the chosen
   policies until one whole pass makes no changes. The default limit is four
   passes, configurable up to ten. A pass limit is not a successful fixed point.
5. When both world inputs are configured, run the same reconstruction function
   as preflight over all source characters and retain its current blocker report.
   This diagnostic writes no expectation SQL and does not certify gameplay.
   Run a new **full audit**. Missing coverage, unsupported states and guard errors
   remain visible. Deferred cases are retained, including pending native resets,
   online/invalid characters and ambiguous items or ownership.
6. Only at a fixed point with a COMPLETE full audit without coverage limitations,
   and an explicit migration configuration, start the existing migration phases:
   `preflight` -> `archive-unsupported` -> `assemble` -> `load-auth` ->
   `load-characters` -> `sanitize-target` -> `validate` -> `report`.

The migration configuration must identify the same endpoint, source auth,
characters and world, target world, and TC-to-AC direction as preparation.
Target auth, target characters and control schemas must be fresh and table-free.
The runner creates a fresh migration run ID; it does not drop old schemas or
reuse their checkpoints. Preflight retains its own blocker/archive gates. Any
phase failure stops subsequent phases.

Exit 0 means the complete requested database rehearsal reached SQL `READY`.
Gameplay remains **NOT TESTED** and release approval **UNREVIEWED**. A
preparation-only run, pass limit, incomplete final audit or failed phase exits
nonzero and keeps its evidence. `POLICY_FIXED_POINT` means only that the chosen
rules made no further eligible changes; it does not mean all blockers are gone.

## Repairs while a native talent reset is pending

A queued reset is not a completed reset. The following separate policies retain
`at_login` bit 4 and every selected talent in both groups. They never allocate
points, perform a login, execute native unlearning, or clear the flag.

| Recipe policy | Allowed change |
| --- | --- |
| `pending-generic` | Insert absent Generic 183 only from existing enabled 2382, under the verified native reward catalog. |
| `pending-talent-history` | Retire only wholly disabled talent families selected by neither group. Enabled siblings and unsupported routes defer the entire family. |
| `pending-ordinary-defaults` | Retire only wholly disabled Dash/Death Pact history with inactive custom defaults and retained skills/flags. |
| `pending-professions` | Activate only verified already-known ordinary profession rows; preserve skills/caps and the pending reset. |
| `pending-death-coil` | Retire verified disabled Death Coil training history; explicitly allow native rank 1 from existing Unholy, as in the reviewed ordinary policy. |
| `pending-talent-ownership` | Retire verified conflicting history, including enabled rows, against existing selected talents. All original native anchor, family, class, script and skill guards still apply. |
| `unavailable-dual-spec-teacher` | Retire fixed teaching wrappers 63680/63706/63707 only with one configured spec, absent Generic skill/switch buttons and a pending reset. Explicitly discard its future learning action; grant no buttons or second spec. |

These are explicit preparation corrections before the eventual native reset,
not reset implementations. Their SQL guards require the flag to remain set,
full state fingerprints preserve all other flags and ownership, and protected
native reset consumers are pinned. Normal policies still defer pending resets.
Gameplay validation must exercise the target login and reset afterward.

## Missing native racial skills

`native-racial-skills` restores only absent native racial skills 101, 125, 126
and 754, from fixed already-enabled anchors 2481, 20572, 20582 and 20597.
Both catalogs must verify the character's race/class and the complete frozen
racial reward set. The native always-max value and cap are `level * 5`.
Existing skills, spells, selected builds, items and all flags remain unchanged.

This explicitly permits native skill loading to restore missing stock racial
abilities. The proof lists the exact reward IDs, including missing modern
racials; SQL itself inserts no spells. Inactive/disabled stored racial rewards,
unknown rewards, changed metadata/scripts, unsupported dependencies, invalid
character state or insufficient native skill slots defer the repair. Pending
resets remain pending. Validate the resulting racial actions during gameplay.

## Native-invalid equipment during specialization review

`specialization-native-items` and `specialization-parent-native-items` extend
the existing verified specialization policies only for exact native-invalid
equipment: a wholly missing instance, or entry zero without a template in either
world. They retain every reference and instance unchanged. Every valid item is
still checked; unknown nonzero templates, partial missing data, duplicate slots
and affected requirements defer. Both worlds must lack template zero throughout
planning, preparation, apply and restoration. This does not repair item
corruption or bypass the migration's item validation.

`obsolete-horse-riding` applies the separate fixed 824/148 catalog to forbidden
legacy Horse Riding. It requires an existing matching modern Riding skill and
enabled rank, absent old teacher/default routes, and complete item requirements
in both worlds. It changes no modern riding, mounts or items. The two original
Wolf Riding policies retain their original selections and acknowledgements.

## Ineligible families with reviewed cast callbacks

`ineligible-cast-scripts` considers only scripted ordinary families rejected
for race/class in both catalogs. Every callback must have the protected
`NO_SPELLBOOK_MUTATION` review and pass its native metadata checks. This permits
reviewed combat callbacks; it does not permit an unknown script, research or
learning callback. All ordinary eligibility guards still apply, including
associated skill absence, matching rank/ability metadata, valid selected talent
ownership, absent dependencies and no pending reset. Source skills and selected
builds remain unchanged. The batch proof records each core's callback bindings.

## Complete forbidden skill families

`foreign-skill-families` reviews complete related spellbook families together
with any corresponding stored skills. Both native catalogs must forbid the
skill for the character's race/class and agree on its classification. The
review covers weapon, class, armor and language skills, including fixed pet
skill categories found incorrectly in a player's spellbook. Professions,
racial skills and riding are excluded.

Pure self-teaching routes and known rank/dependency links are grouped before
selection. A shared exposure, retained selected talent, mixed learning route,
unreviewed callback, changed native metadata or matching default route defers
the family. Both selected builds and every pending-reset flag remain unchanged.
All owned, inventory and mail item requirements are checked in both worlds;
equipped proficiency conflicts defer rather than move an item. Only previously
reviewed exact missing/zero item records may remain inert and unchanged.

The proof separately lists removed spell rows and removed native skill rows.
`--expect-rows` counts spellbook rows, not the physical deletion total. The
transaction archives complete affected originals, retires only the sealed
spell/skill keys, and supports a guarded exact inverse. SQL inserts no skills
or spells, changes no item, and executes no native unlearn, login or reset.
This is a separate coupled correction; the older spell-only policies retain
their original behavior. Native gameplay acceptance remains required.

## Unselected Shaman Dual Wield with an occupied off-hand

`shaman-offhand` is a separate equipment-aware policy. Neither selected build
may own Dual Wield talent 30798. It retires spell 674 and skill 118 together;
retaining the skill would restore the spell at login. It retains a verified
shield backed by Shield skill 433. A verified singleton off-hand weapon moves
to the first empty backpack slot, or an ordinary bank slot if the backpack is
full. No item is deleted, stacked, mailed or replaced.

The batch archives the complete affected inventory and its exact slot inverse,
alongside spell, skill, talent and character originals. Both-world item shapes,
ownership, placement counts, item-linked auras, native storage bounds and main
hand compatibility must pass. Unknown or duplicate items, occupied destination,
full storage and selected Dual Wield defer or invalidate the batch. Source
`UPDATE(slot)` on `character_inventory` is needed for moves; grants are never
changed automatically. A pending talent reset remains pending. Review the
`inventory_moves` proof before applying; restore before gameplay or later edits.
Native reader tests are separate from gameplay acceptance.

## Exceptions, interruption and restoration

Character-specific talent resets and zero-container recovery require their own
reviewed evidence and permissions. For an individually reviewed character with
one configured spec, active group zero and unavailable group-one history, pass
`--reviewed-unavailable-spec-reset GUID`. This invokes the existing guarded
single-character procedure after the explicitly included `invalid-talents`
bootstrap policy and before the remaining policy sweep: archive unavailable group one,
retain active ownership, and queue the free native active reset for next login.
It does not complete the reset. A new valid second spec or other changed
precondition stops the run; absence of group-one rows is a no-op. The option is
never inferred from staff status, historical batches or the recipe registry.
Historical character IDs are not generalized into recipe policies. Pending resets need native-server validation;
this runner never clears their flags or impersonates a completed login/reset.
Custom features remain separate from stock migration.

On failure, inspect `replay.json`, the failing command log and the batch status.
Applied batches remain applied; the runner does not undo them automatically or
retry an uncertain operation. Use existing `console status --batch BATCH_ID` to
reconcile it. Restore in reverse application order with each batch's original
complete toolkit, before gameplay or further edits. For a clean full rehearsal,
restore the original into another preparation copy and run a new session,
output directory and set of archives.

The replay does not supply missing auth data or a running native game server.
Full account validation and native gameplay acceptance remain separate evidence
requirements. See [the migration guide](migration-guide.md) and
[fresh-snapshot cutover workflow](source-preparation.md#repeat-the-complete-preparation-and-migration).

`foreign-training-actions` is a separate extension for pure native training
actions whose complete taught families are forbidden for the caster in both
catalogs, including absent child rows. It discards the future teaching action;
it never inserts or casts a child spell. Exact self/training targets, both
metadata catalogs, selected talents, defaults, item requirements, proficiency
and atomic spell/skill inverse guards remain required.

## Fixed native action policies

`native-redundant-teachers` retires only fixed redundant ordinary training actions
whose taught children are already known through retained enabled native rank
anchors. Skill values/caps stay unchanged. Old Lockpicking step 242 is never
reinterpreted as skill 633 or inserted.

`native-unusable-specializations` retires only inactive specialty history backed
by an existing skill value below the stock minimum, plus a fixed enabled teacher
whose child is absent. Every active specialization, ordinary rank and stored
recipe remains. This discards known-specialty history; it grants no replacement.

`native-obsolete-teachers` discards fixed Tiger Riding training action 6745 when
its child is absent and modern Riding is already 300/300 with the retained
enabled anchor. Both old and modern stored skills remain unchanged.

`native-transient-combat` removes fixed Ebon Plague/Borrowed Time combat aura IDs
from the player spellbook. Native combat mechanics create those auras; rank
chains in the two cores are deliberately different. Character aura records and
selected talents remain untouched; the migrator's rank checks remain strict.

`native-forbidden-pairs` retires fixed native-forbidden Raptor/Undead riding or
mixed Dual Wield families and their exact stored skills. Both native eligibility
catalogs, a retained modern riding anchor where applicable, absent matching
defaults/teachers and all owned item requirements must agree. An occupied valid
Dual Wield off-hand defers. No mount, skill, item or talent is granted.

Every policy regenerates a complete affected source archive, exact native catalog
and source proofs, item evidence, a distinct acknowledgement and a guarded exact
inverse. Skill deletion keys are separate from spellbook keys. Pending reset
flags are preserved; no login, native unlearn cast or reset is simulated.

`native-forbidden-pairs-stowing` is the separate equipment-aware variant for
fixed native-forbidden Dual Wield 674/42459. It stows a fully verified second
weapon to the first free backpack or ordinary bank slot and archives complete
inventory placement. Unknown gear, requirement conflicts or full storage defer.
It requires explicit `UPDATE(slot)` permission on `character_inventory`; the
console grants no source privileges. Exact skill, spell and inventory inverse
checks run in the same atomic transaction.

An individually reviewed active reset may be supplied as
`--reviewed-active-reset GUID:12284`; an unavailable second-spec reset uses
`--reviewed-unavailable-spec-reset GUID`. Neither option belongs in a generic
policy recipe. Both call the existing guarded planners and archive originals.
Active ownership stays present until native login consumes the queued free
reset. A missing already-retired foreign row is a no-op only if a native reset
is already pending; it never authorizes inferring a completed reset.
