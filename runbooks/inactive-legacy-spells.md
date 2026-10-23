# Reviewed inactive legacy spell retirement

This is a separate **opt-in source preparation policy**, not a migration
exception or blanket inactive-spell cleanup. Use only a stopped preparation
copy. `tc-inactive-legacy-bloodthirst-retirement-v1` archives/removes unavailable
old Bloodthirst spellbook history while retaining every active stored spell,
current talent selection, skill/cap, profession slot and character/login flag.

## Exact boundary and tradeoff

The retirement catalog contains only `23892`, `23893`, `23894`, `25251` and
`30335`. Neither reviewed world links these IDs as a current rank chain. The
policy **does not invent those links**, infer a replacement or grant a missing
rank. Each member must remain a singleton with the exact reviewed ordinary
warrior/rage/damage mechanics in both effective catalogs. Skill/recipe,
profession/riding, talent/aura ownership, teaching, prerequisites, scripts,
AC trainer entries, trigger references and custom-start routes exclude the catalog.
Matching but unreviewed changes in both worlds are insufficient.

A character qualifies only when:

- race/class/level and both talent groups are valid, class is warrior, the
  character is offline and native talent reset bit 4 is clear;
- every stored catalog row has `active=0,disabled=0` or `active=1,disabled=0`;
- at least one catalog row is already active and remains untouched;
- each retired row is exactly `active=0,disabled=0`.

The active retained member is an existing spell, not authority to select a
higher rank or to assume a historical chain. Other inactive spells, unexplained
passive states and professions remain outside this policy. Disabled catalog
history defers to its own reviewed policy. Current Bloodthirst talent `23881`
is outside the retirement list, and both selected builds remain unchanged.

TC `HasSpell` includes these inactive/non-disabled rows, whereas
`HasActiveSpell` and the initial client spellbook exclude them. A normal player
cast request requires the active state. Deletion therefore **discards unavailable
known-spell and future reactivation/retraining history deliberately**; it does
not claim the source records were corrupt or preserve `HasSpell` membership.
Native book-independent casting overrides are not rewritten. TC/AC differences
in those overrides remain outside this repair. All active spells and normal
spellbook casting remain unchanged under the reviewed consumers.

## Configuration and review

Configure the normal cleanup console with both DBC directories, both core
checkouts and SELECT-only TC/AC world inputs. Verify and assert the effective
custom-start settings; the policy does not change server configuration:

```ini
[source]
player_start_all_spells = 0

[target]
world = ac_world_snapshot
player_start_custom_spells = 0
```

After source edits or toolkit/profile changes, capture fresh local evidence
before planning. A report export is not required after every known batch while
developing the complete workflow. For a new production snapshot, start a new
session and calculate its own candidates; do not replay old GUIDs or counts.

```bash
python3 console plan inactive-legacy-spells --migration-inspection latest --preview
python3 console plan inactive-legacy-spells --migration-inspection INSPECTION_ID --expect-rows SELECTED_ROWS
```

`SELECTED_ROWS` is this preview's `selected_rows`, not a historical count or the
number of first failures in the old report. Inspect `inactive-legacy-review.json`,
`selected-rows.tsv`, `excluded-rows.tsv`, `relationship-review.tsv` and
`inactive-legacy-native-proof.json`. Proofs record exact inactive removals,
retained active members, the known-history tradeoff and `rank_links_inferred=false`.

```bash
python3 console prepare --batch BATCH_ID
python3 console status --batch BATCH_ID
# Review the exact archived originals and selection before applying.
python3 console apply --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Prepare archives complete affected character, talent, spell and skill rows,
including custom fields, without changing source data. Apply commits exact
inactive-row deletion and its checkpoint together. Both worlds/DBC assets,
source/archive layouts, core/selector fingerprints, complete input scope and
full expected result are guarded, including same-count and fractional drift.
Reruns verify the committed result. Unrelated data and active spells are not
rewritten. No source write privilege is added automatically: apply needs
`DELETE` and exact restore needs `INSERT` on source `character_spell`.

The console supplies the explicit policy acknowledgements. Direct SQL also
requires these before each action:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @inactive_legacy_ack='RETIRE_ONLY_INACTIVE_LEGACY_BLOODTHIRST';
SET @eligibility_tc_all_spells=0;
SET @eligibility_ac_custom_spells=0;
```

## Restore, fresh imports and acceptance

Before later edits/gameplay, restore through the sealed batch:

```bash
python3 console restore --batch BATCH_ID
```

The guarded inverse restores the exact removed rows and custom fields and
verifies the complete original state. Restore later batches first. Keep each
archive and its original toolkit. Restoring baseline dumps for another rehearsal
requires a new session, current metadata, new exact selections and fresh
migration target/control schemas. See the
[complete fresh-snapshot workflow](source-preparation.md#repeat-the-complete-preparation-and-migration).

Automated checks cover normal casting and client book preservation, both specs,
no current-talent or skill mutation, unsafe routes, explicit counts, full custom
archives, world/source drift, late/disconnected rollback, reruns and exact inverse
on disposable MySQL 8.4. Protected consumers use mocked state, targets and packet
sinks. They are separate from gameplay acceptance.

Staging must verify the retained active Bloodthirst/current talent and action
buttons in both specs, ordinary ranks/trainers, casts, professions/recipes/riding,
skills/caps and save/relog/restart persistence. The five migration gameplay gates
remain **NOT TESTED**; release approval remains **UNREVIEWED**.
