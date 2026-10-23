# Retire redundant skill-teaching wrappers

`tc-redundant-skill-teaching-wrapper-retirement-v1` is an explicit preparation
policy for old teaching actions stored in `character_spell`. It archives/removes
only enabled wrappers `1710`, `5785`, `19902` and `65286` under fixed reviewed
metadata. These cover old Felsteed/riding, First Aid and Jewelcrafting teachers.
It is separate from spell reconstruction and from pet-teaching retirement.

A teaching action can both teach a spell and reset its skill tier. The pinned
TC load path casts stored skill-step wrappers; its `EffectLearnSkill` can request
First Aid cap `300` even when the character stores `450`. AC rejects persistent
learn-effect wrappers. This policy deliberately discards the redundant teaching
action and its cap-reset effect, while preserving already-known taught spells
and the stored skill state. It does not cast, activate or replace a wrapper.

## Preview and create a reviewed batch

Use the current cleanup toolkit and the existing private configuration. Both
read-only world schemas, both DBC directories and compatible core source trees
are required. The effective TC `PlayerStart.AllSpells` and AC
`PlayerStart.CustomSpells` must both be `0`; record those assertions as
`[source] player_start_all_spells=0` and `[target] player_start_custom_spells=0`.
These settings are assertions, not changes to either server configuration.

```bash
python3 console plan skill-teaching \
  --migration-inspection latest \
  --preview
```

Preview makes no SQL package or active batch and changes no source rows. It
reviews every stored wrapper in the captured character scope, including cases
hidden behind another first-error blocker. No preflight is needed just to preview
this policy. After a source edit, first refresh the inspection using the existing
blocker report. If the toolkit rejects an older inspection's producer/profile,
refresh that read-only inspection rather than editing its sealed files.

Every taught child must already be known through a **retained enabled** ordinary
spell or a verified higher-rank anchor. For example, retained First Aid `45542`
proves the lower child `10846`; the missing child is not inserted by this repair.
Normal migration reconstructs supported lower ranks later. Both catalogs must
match the frozen mechanics, chains, abilities, learning/prerequisite relationships
and skill categories/race-class/tier metadata in
`lib/cleanup_skill_teaching_catalog.json`. Matching arbitrary modifications to
both worlds do not qualify.

Required guards include offline/valid character and talent state in both specs,
no pending reset, enabled wrapper flags, existing coherent skill values/caps,
compatible retained anchor skills, and a retained matching riding-tier anchor.
Wrong classes, missing or disabled child anchors, unsupported flags, metadata,
skill state or talent ownership defer. Unknown IDs never enter this catalog.
There is no staff/GM exemption and no equipment or item-template inference.

Use the preview's `selected_rows` as `N`; this counts **wrapper rows**, not
characters or taught children:

```bash
python3 console plan skill-teaching \
  --migration-inspection latest \
  --expect-rows N
```

Review the candidate's `README.md`, `manifest.json`, `selected-rows.tsv`,
`excluded-rows.tsv` and `skill-teaching-native-proof.json`. Each native proof
records retained child anchors, preserved skill value/cap, and the discarded
cast's step/cap. Use the exact candidate ID as `BATCH`:

```bash
python3 console prepare --batch "$BATCH"
python3 console status --batch "$BATCH"
# Inspect the prepared full originals and exact selected rows before apply.
python3 console apply --batch "$BATCH"
python3 console status --batch "$BATCH"
```

Prepare archives complete affected character, talent, spell and skill rows,
including custom columns, without source changes. Apply deletes only the exact
selected wrappers. Taught spells, recipes, all skill values/caps, both talent
builds, profession slots, items and login flags stay unchanged. Source write
privileges are only `DELETE, INSERT` on `character_spell`, in addition to read
privileges. No source grants are added automatically.

## Reruns and exact restoration

Apply/checkpoint are one transaction. A late failure or disconnected transaction
rolls back partial deletion. An apply rerun verifies the committed result. Status
reads the archive checkpoint; do not infer success or failure from a client
disconnect alone. Direct stored-procedure calls also require these assertions:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @skill_teaching_ack='RETIRE_ONLY_REDUNDANT_KNOWN_SKILL_TEACHERS';
SET @eligibility_tc_all_spells=0;
SET @eligibility_ac_custom_spells=0;
```

Restore before gameplay or subsequent edits, in reverse batch order:

```bash
python3 console restore --batch "$BATCH"
python3 console status --batch "$BATCH"
```

Restore inserts the exact archived wrapper rows including custom values and
verifies the full original affected state. Source/world/DBC/catalog/reader drift,
later skill or recipe changes, altered selections or archive tampering refuse
restoration. Retain the original toolkit for each archive; do not weaken guards
or drop/reuse archive schemas to force a restore.

For a freshly imported production snapshot, create a new cleanup session,
audit/inspection, selection, batch and archive. Reuse this reviewed policy, never
historical GUIDs, row counts or generated SQL. Migration still needs its normal
preflight and new target/control schemas.

## Validation and staging acceptance

Local checks cover semantic forward/reverse behavior, missing/disabled children,
metadata/ownership/skill guards, full custom originals, source/world immutability,
MySQL transaction rollback/disconnection, completed reruns and exact inverse.
Protected TC/AC skill-effect bodies, AC direct/wrapped trainer state and both
quest known-child gates run in isolated C++ harnesses with recording state sinks.
Known children keep trainers learned without a stored wrapper and suppress the
reviewed quest recast path. These are behavioral consumer tests; they do not run
a full worldserver or establish gameplay acceptance.

Release approval remains **UNREVIEWED**. Record staging acceptance separately:

| Staging check | Status |
| --- | --- |
| Reconstructed paladin/priest/warlock ranks and trainers: known lower ranks learned, genuinely unknown higher ranks available | NOT TESTED |
| Highest and supported lower rank casts | NOT TESTED |
| Switch both specs, relog in each and verify talent ownership | NOT TESTED |
| Talent points, profession slots, recipes, riding tier, skill values and caps; retired teacher state | NOT TESTED |
| Save/relog/restart, repeat spell/trainer/spec checks and inspect deletion/correction logs | NOT TESTED |
