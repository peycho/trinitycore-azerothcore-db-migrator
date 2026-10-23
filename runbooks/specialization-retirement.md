# Retire inactive competing profession specializations

`tc-inactive-competing-specialization-retirement-v1` is a separate opt-in
preparation policy. It archives/removes an existing `active=0, disabled=0`
specialization only when one verified active choice remains in the same branch.
It never activates a specialization, chooses between active competitors or
inserts a missing prerequisite.

**This changes known-specialization eligibility.** TC still regards an inactive,
non-disabled specialty as known. Removing it can affect specialty-gated crafting,
NPC options and item eligibility. Stored recipes remain in the database, but
keeping their rows does not promise that every recipe or unequipped item remains
usable after removing its required specialty. The reviewed active choice becomes
authoritative. This is not the ordinary profession activation policy.

## Preview using current evidence

Use a stopped preparation copy with its retained backup reference and current
private configuration. Both source trees, both DBC directories and both read-only
worlds are required. TC `PlayerStart.AllSpells` and AC `PlayerStart.CustomSpells`
must be `0`, asserted by `[source] player_start_all_spells=0` and
`[target] player_start_custom_spells=0`. These assertions do not change server
configuration.

After a source edit, refresh the inspection with the existing blocker report:

```bash
python3 console inspect-migration-blockers --report "$BLOCKER_REPORT"
python3 console plan specialization-retirement \
  --migration-inspection latest \
  --preview
```

If the current inspection was already captured after the last source change,
run only the preview. `latest` selects saved evidence; it does not recapture it.
There is no need for another preflight just to preview this policy. A historical
blocker report supplies scope, not a current whole-realm success/failure count.

The initial fixed catalog covers:

| Branch | Choices | Minimum retained skill |
| --- | --- | --- |
| Blacksmithing | Weaponsmith / Armorsmith | 225 |
| Weapon subspecialization | Sword / Hammer / Axe | 250 |
| Leatherworking | Dragonscale / Elemental / Tribal | 250 |
| Engineering | Gnomish / Goblin | 200 |
| Tailoring | Spellfire / Mooncloth / Shadoweave | 350 |

Both native catalogs and the protected specialization/equipment consumer sources
must match the reviewed contract. Arbitrary matching edits in both worlds do not
qualify. The selector requires a valid offline character, valid talents in both
specs, no pending native reset, exactly one enabled active specialty in the branch,
coherent existing skill value/cap, and verified ordinary-profession prerequisites. Weapon and
Leatherworking branches require level 50; Tailoring requires level 60 under the
reviewed NPC contracts.
Known ordinary lower ranks may be proved by an existing enabled higher ordinary
rank under its stock chain; no missing rank is inserted. Weapon subspecialties
additionally require an existing **active Weaponsmith 9787**. Axe Smithing does
not imply a missing Weaponsmith row.

Ambiguous active choices, mixed disabled family flags, missing skill/prerequisite
state, known teaching wrappers, dependent specialty spells and unsupported
metadata defer. The policy never purges recipes or invokes native unlearn casts.
There is no GM/staff exemption and no two-profession assumption.

## Equipped-item checks

Preview reads `character_inventory` and `item_instance`, and both worlds'
`item_template.entry, RequiredSpell`. The tables must use InnoDB and native
integer identifier/requirement fields. Custom columns remain present and their
layouts are sealed; no table or item is rewritten.

Equipment slots `0..18`, equipped bag slots `19..22` and bank bag slots
`67..73` with database `bag=0` are checked. A missing item instance/template, zero/unknown entry, duplicate
slot, or either world's `RequiredSpell` naming a specialty to retire defers that
character's affected branch. Custom items are retained; an unknown template is
not treated as proof that it has no specialty requirement. Required spells for
the retained choice are allowed. Backpack/bank items are not moved or deleted;
their future usability can change as explained above.

The relevant equipment links, item entries, both required-spell values and full
layouts are rechecked during planning and every prepare/apply/restore phase.
Equipment or requirement drift blocks the batch, including direct SQL calls.
This evidence is captured live for the policy; it is not inferred from an old
character-only export. Preview selects nothing automatically for execution.

## Create, prepare and apply a reviewed batch

Use the current preview's **selected_rows** as `N`; do not reuse an old count:

```bash
python3 console plan specialization-retirement \
  --migration-inspection latest \
  --expect-rows N
```

Review the candidate's `README.md`, `manifest.json`, `selected-rows.tsv`,
`excluded-rows.tsv` and `specialization-native-proof.json`. Proofs show each
retired row, retained active specialty, ordinary known anchors and preserved
skill. The manifest seals equipment evidence and native source hashes. Set
`BATCH` to the returned candidate ID:

```bash
python3 console prepare --batch "$BATCH"
python3 console status --batch "$BATCH"
# Review the prepared originals and exact selection before applying.
python3 console apply --batch "$BATCH"
python3 console status --batch "$BATCH"
```

Prepare archives complete affected character, talent, spell and skill originals,
including custom fields. Apply deletes only the selected inactive specialty rows.
The retained choice, all ordinary ranks, stored recipes, both builds, skills/caps,
items/inventory and login flags stay unchanged. Source permissions are SELECT
plus **DELETE, INSERT on character_spell only**; no source grants are added
automatically. Archive setup follows the existing console administrator contract.

The summary's `enabled_rows_removed` means non-disabled stored rows. All selected
rows are inactive: `active_rows_removed=0`. No active chosen specialty is removed.
Apply and checkpoint are one transaction. Reruns verify the committed result;
late failures and disconnected transactions roll back partial changes. Direct
stored-procedure calls additionally require:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @specialization_retirement_ack='RETIRE_INACTIVE_COMPETITORS_RETAIN_VERIFIED_ACTIVE_CHOICE';
SET @eligibility_tc_all_spells=0;
SET @eligibility_ac_custom_spells=0;
```

## Restore and repeat on a fresh import

Restore before native login or later edits, in reverse batch order:

```bash
python3 console restore --batch "$BATCH"
python3 console status --batch "$BATCH"
```

The guarded inverse reinserts exact original rows, including custom fields, and
verifies all four complete affected tables. Changed affected spell/skill/talent/
character state, equipment or metadata stops restoration rather than overwriting
later progress. Keep each archive and its original toolkit. Never modify sealed
SQL/evidence or weaken guards to reuse a batch.

A fresh production snapshot needs a new session, audit and inspection, fresh
preview counts/selections, batches, archives and migration target. Historical
GUIDs/counts are development evidence only. This opt-in policy does not silently
extend another cleanup mode or relax the migration's inactive-spell guard.

Automated validation covers frozen catalogs, native prerequisites, ambiguity,
reset/skill/equipment failures, original inactive rejection, both-direction
semantic reconstruction after deliberate retirement, no grants, no-op preview/
prepare, custom-row restoration, write grants, exact source and both-world drift,
equipment links/requirements/layout changes, atomic checkpoint/rollback,
connection termination and reruns. Pinned TC/AC equipment gates and TC specialty
NPC gates are compiled with recording state. Full game-server gameplay and
production acceptance remain **NOT TESTED**; compatibility pins and release
approval remain unchanged (**UNREVIEWED**).
