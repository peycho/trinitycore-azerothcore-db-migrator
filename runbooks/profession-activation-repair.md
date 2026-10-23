# Activate existing ordinary profession ranks

`tc-inactive-ordinary-profession-activation-v1` is a separate opt-in preparation
policy. It changes an existing `character_spell` row from `active=0, disabled=0`
to `active=1, disabled=0`. **This deliberately makes an already-known profession
action usable.** It is not history deletion or a migration-checker exception.

Pinned TC considers the original row known but inactive. AC's ordinary persistent
representation makes it active. Deleting a sole known profession rank can affect
profession-slot accounting, while inferring a higher rank from the skill cap can
grant an action the character did not know. This policy does neither.

## Review the current snapshot

Use the current cleanup toolkit and private configuration. Both compatible core
source trees, both DBC directories and both read-only world schemas are required.
The effective TC `PlayerStart.AllSpells` and AC `PlayerStart.CustomSpells` must be
`0`, asserted as `[source] player_start_all_spells=0` and
`[target] player_start_custom_spells=0`. Configuration assertions do not change
the game servers. Use a stopped preparation copy with its retained backup reference.

After source changes, capture a fresh inspection using the existing blocker TSV:

```bash
python3 console inspect-migration-blockers --report "$BLOCKER_REPORT"
python3 console plan profession-activation \
  --migration-inspection latest \
  --preview
```

`latest` selects a saved inspection; it does not capture a new one. An existing
blocker report supplies character scope even after its first errors were fixed;
preview checks all captured rows in that scope, including hidden failures.
A final whole-realm preflight is still required after preparation. No preflight
rerun is necessary just to review this policy.

Preview is read-only and creates no SQL package or active batch. The first policy
reviews ordinary Leatherworking, Tailoring, Blacksmithing and Engineering rank
families under the fixed catalog in `lib/cleanup_profession_catalog.json`.
It requires all of the following:

- An offline valid character, valid selected talent ownership in both specs and
  no pending native talent reset.
- Exactly one stored ordinary rank in the family, with `active=0, disabled=0`.
- An existing eligible skill with a coherent positive value and cap, satisfying
  the known rank's minimum and tier in both native catalogs.
- Exact reviewed spell mechanics, rank chains, skill abilities, learning and
  prerequisite relationships, and skill category/race/class/tier metadata.
  Matching arbitrary custom modifications in both worlds do not qualify.

Specializations, other profession families, multiple stored ordinary ranks,
missing/incompatible skills, scripts, unsupported talent/aura routes and pending
resets defer. A specialization is never chosen or activated by this policy.
There is no GM exclusion and no two-profession inference: existing known ownership
is retained, including characters that already have more professions.

For example, existing Leatherworking `2108` with skill `78/150` can qualify.
Only that row becomes active; the tool does not insert missing rank `3104` merely
because the stored cap is `150`. Recipes, skill value/cap and other spells remain
unchanged. Supported lower-rank reconstruction during migration remains a separate
native contract; no missing higher rank is inferred.

## Prepare, apply and restore

Use this preview's **selected_rows**, not character count or a historical count,
as `N`:

```bash
python3 console plan profession-activation \
  --migration-inspection latest \
  --expect-rows N
```

Review the candidate's `README.md`, `manifest.json`, `selected-rows.tsv`,
`excluded-rows.tsv` and `profession-activation-native-proof.json`. Proofs identify
the exact ordinary root, preserved skill, old/new flags and explicit availability
change. Set `BATCH` to this candidate's ID, then:

```bash
python3 console prepare --batch "$BATCH"
python3 console status --batch "$BATCH"
# Review prepared originals and the exact selection before applying.
python3 console apply --batch "$BATCH"
python3 console status --batch "$BATCH"
```

Prepare archives complete affected character, talent, spell and skill originals,
including custom columns. Apply updates only the selected `active` fields.
No spell row is inserted/deleted, no effect is cast, and no skill/cap, recipe,
specialization, talent/spec, inventory or login flag changes. Source write
permission is **UPDATE(active)** on `character_spell`, plus existing SELECT;
no source INSERT/DELETE privilege is needed or granted automatically. Setup uses
the existing archive administrator requirements described in the console guide.

Status reports `inactive_rows` and `activated_rows`; selected rows remain stored
throughout this policy. It must not describe updated rows as deleted.
Apply and checkpoint are atomic. A rerun verifies the committed result; failures
roll back partial activation. Source/world/DBC/catalog/reader/schema drift,
changed full originals or sealed selection/result hashes stop the operation.
Direct procedure calls also require these assertions:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @profession_activation_ack='ACTIVATE_ONLY_EXISTING_ORDINARY_PROFESSION_RANKS';
SET @eligibility_tc_all_spells=0;
SET @eligibility_ac_custom_spells=0;
```

Restore **before native login or subsequent edits**, reversing batch order:

```bash
python3 console restore --batch "$BATCH"
python3 console status --batch "$BATCH"
```

The guarded inverse restores the exact original active flags and verifies all
four complete affected tables, including custom values. It refuses post-apply
drift rather than overwriting later progress. Retain archives and their original
toolkit; do not edit sealed files to force an old batch through newer readers.

## Repeatability and validation limits

For a fresh production import, create a new session, audit and inspection, then
recompute preview selections/counts and create new batches/archives. Never reuse
the old GUID list, count, batch ID, approval or migration target. This policy is
not an automatic part of other cleanup policies.

Automated coverage includes selector/catalog failures, original inactive migration
rejection, explicit activation followed by native semantic reconstruction in both
directions, no missing higher-rank grant, custom-column exact restoration,
UPDATE(active)-only permissions, full-state and both-world drift, reruns,
transaction rollback and disconnected apply. Compiled protected TC/AC getter,
profession first-rank accounting and ranked-skill loading branches use mocked
state and recording setters. Full game-server login/crafting and production
acceptance remain **NOT TESTED**. Compatibility pins and release approval stay
unchanged; release approval is **UNREVIEWED**.
