# Restore the reviewed Weaponsmith parent

`tc-reviewed-weaponsmith-parent-repair-v2` is an explicit preparation repair for
one reviewed inconsistent branch: active Master Axesmith (`17041`) without its
Weaponsmith parent (`9787`), together with inactive Armorsmith (`9788`), Master
Swordsmith (`17039`) and Master Hammersmith (`17040`). It restores active
Weaponsmith and retires those three inactive competitors atomically. It changes
known-specialization eligibility, including recipe and item eligibility.

The existing [specialization retirement](specialization-retirement.md) remains
unchanged and still requires an already-known active parent. This separate
policy authorizes the parent restoration. It does not choose a new weapon
subspecialization or apply to ambiguous or missing active choices.

## Required evidence

Use a stopped preparation copy, its retained verified backup, the current sealed
migration inspection, the protected TC/AC sources and the configured DBCs. The
existing custom-start-off assertions and read-only target metadata access from
the [cleanup console guide](cleanup-console.md) apply. No source grant is added
by this command.

The selector requires all three competitor rows to be `active=0, disabled=0`,
Master Axesmith to be `active=1, disabled=0`, and complete absence of Weaponsmith,
including disabled history. Existing native Blacksmithing must meet the reviewed
weapon-specialization minimum (250), level must be at least 50 and at most 80,
and an existing enabled ordinary rank must prove the required ordinary ranks.
Both talent builds must be valid. Pending talent resets, online characters,
ambiguous flags, missing ordinary knowledge, low skills and changed native
catalogs defer. Known specialization teaching wrappers also defer.

The exact existing specialization/ordinary-rank catalogs are required in both
worlds. Stored spells requiring a retired specialty cause deferral; recipes are
never purged or passed through native unlearn effects. Retaining recipe rows does
not guarantee that a recipe gated by a retired specialty remains usable. The
retained Master Axesmith and restored Weaponsmith become authoritative.

Equipment, equipped bags and bank bags are checked against both worlds'
`item_template.requiredspell`. Requirements for any of the three retired spells,
unknown instances/templates, invalid entries and duplicate slots defer. All
item data and inventory placement remain unchanged. Unequipped items remain
stored; their future eligibility may change. The native-invalid-item allowance
from obsolete riding is not used here.

This version requires exactly the four native `character_spell` columns:
`guid`, `spell`, `active`, `disabled`. Extra spell-specific columns fail with
`UNSUPPORTED_PARENT_COLUMNS` for separate review. Custom columns in other
archived source tables remain covered by complete original snapshots and exact
fingerprints. No table or custom field is dropped or rewritten by the repair.

## Preview and apply

After source changes, refresh semantic context from the saved report. It supplies
GUID scope; a new full audit or preflight is not needed to create this capture.
Continue the existing session when its source identity is unchanged. On a fresh
database import, create a new session and recalculate selections and archives.

```bash
python3 console inspect-migration-blockers --report /path/to/spell-state-blockers.tsv
python3 console plan specialization-parent --migration-inspection latest --preview
```

Equipment is captured live during the preview. Use its actual `selected_rows`,
which counts **three original rows per selected character**, as `N`. The separate
`spell_rows_inserted` count is one parent per selected character. Never use an
old snapshot's count or force a provisional count past a deferral.

```bash
python3 console plan specialization-parent --migration-inspection INSPECTION_ID --expect-rows N
python3 console prepare --batch BATCH_ID
python3 console status --batch BATCH_ID
# Review README.md, manifest.json, selected-rows.tsv and specialization-native-proof.json.
python3 console apply --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Prepare archives complete affected character, talent, spell and skill originals.
Apply deletes the three reviewed inactive rows and inserts only `9787,1,0` for
each selected character. Skills/caps, ordinary profession ranks, stored recipes,
both talent builds, retained Master Axesmith, all items, profession slots and
login flags remain unchanged. No teaching or unlearn spell is cast.

Source permissions are SELECT plus DELETE and INSERT on `character_spell`.
UPDATE permission is not needed. Parent insertion, competitor retirement and the
APPLIED checkpoint share a serializable transaction. Failures and disconnections
roll back the complete change. Direct SQL additionally requires:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @specialization_retirement_ack='RESTORE_WEAPONSMITH_RETAIN_MASTER_AXESMITH_RETIRE_INACTIVE_COMPETITORS';
SET @eligibility_tc_all_spells=0;
SET @eligibility_ac_custom_spells=0;
```

The old retirement acknowledgement cannot apply this repair. Selected originals,
new parents, complete affected state, exact numeric fingerprints, layouts,
worlds, DBCs, equipped-item evidence, catalogs and readers are sealed. Drift
rejects both console and direct procedure calls. Concurrent item requirement
writes are blocked while the transaction holds its reviewed evidence.

## Exact restoration

```bash
python3 console restore --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Restore first verifies the exact applied state. It removes only the inserted
Weaponsmith parent and restores the original three rows from the archive in one
transaction, then verifies complete original affected state. Reruns verify the
committed phase. Native login or subsequent edits can invalidate exact restore;
retain the archive and the complete original toolkit. Earlier archives require
their own original toolkit.

Native consumer tests verify known-specialization and equipment eligibility;
SQL tests cover preview, drift, privileges, concurrent requirements, interrupted
transactions and exact restoration. These are separate from full gameplay,
which remains **NOT TESTED**. Migration approval remains **UNREVIEWED**. The
migrator still reports the first failure per character, so another blocker may
be exposed without reducing the affected-character count.
