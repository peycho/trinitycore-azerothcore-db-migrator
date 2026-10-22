# Native skill preparation repairs

`tc-missing-native-skills-v1` is a separate, explicitly selected **TC preparation
repair**. The migrator still preserves skills exactly and blocks spells that
would add or increase them. This policy inserts only missing Generic (`183`)
or Runeforging (`776`) rows when an already known, enabled spell would cause
the reviewed native TC loader to create that skill. It does not change any
existing skill row, talent selection, spell row, character flag or profession slot.

Use a stopped restored preparation copy with the normal
[cleanup console configuration and backup reference](cleanup-console.md).
Never apply this to production or an active game database. Retain earlier
preparation toolkits and archives for their original guarded restoration. Install
all files from the same new toolkit release; a source reimport or a new cleanup
session is not needed merely to install this policy. Migration targets/control
and run IDs remain separate from cleanup sessions.

## V1: missing native state

| Skill | Required authority | Inserted value/cap |
| --- | --- | --- |
| Generic `183` | Known active/enabled `2382`, or `63644`/`63645` with an existing two-spec character; native Generic category, acquisition and ALWAYS_MAX_VALUE metadata | Character level × 5 for both fields |
| Runeforging `776` | Death knight with known active/enabled `53428`, `53341` or `53343`, plus matching native acquisition metadata | `1 / 1` |

Generic is internal bookkeeping, not a primary profession. The native
ALWAYS_MAX_VALUE flag makes its value equal to the maximum independently of the
AlwaysMaxSkill setting. Both pinned cores' `Unit.h` maximum-skill formula is now
protected, alongside the existing player/default-skill and DBC consumers.
The configured core contents must match the retained pins; approval remains
UNREVIEWED. Custom modules that change native skill maxima or loading behavior
need separate compatibility review.

Only levels 1–80, native player classes, valid spec state and eligible race/class
metadata qualify. Existing skills are preserved even if malformed. Pending
native resets, online characters, a one-spec character with only spec-switch
buttons, disabled/inactive anchors and unsupported effects/metadata defer.
Arbitrary recipes, trainers, character level alone and missing prerequisites
cannot authorize a skill. Riding, primary professions and Dual Wield skill `118`
are outside this policy. No missing spell, form, talent or recipe is inserted.

Runeforging's native skill loader can restore default Cinderglacier/Razorice
enchantments after login; these are the same verified native consequences of
the existing anchor. The SQL repair inserts only the skill row, never spells
or recipes. No game spell or research/teaching wrapper is executed during repair.

## V2: reviewed Generic normalization

`tc-native-generic-skills-v2` is an explicit, Generic-only preparation policy.
Select it with **both** `--skills generic --normalize-generic`. Without these
options, the insertion-only v1 policy remains unchanged, including its existing
packages and exact restoration. Retain the original toolkit for earlier batches.

V2 accepts the same enabled Generic anchors as v1 and additionally the exact
stored, active/enabled `63680` teacher on a character that already owns two
specs. The protected TC `AddSpell` load path restores buttons `63645` and `63644`
from that teacher; their verified acquisition method creates Generic. The
converter's bounded teacher contract checks the effective dependencies, exact
numeric mechanics, skill associations, race/class flags, and lack of extra
rank/talent/script/prerequisite routes. Preparation checks **TC metadata only**;
AC compatibility remains the migrator's separate responsibility. It executes
no spell, spec purchase or switch, and inserts no spell row.

For existing nonzero Generic rows, the pinned TC and AC `_LoadSkills` fixed
range and `UpdateSkillsForLevel` bodies establish the native result: value and
cap both equal character level × 5. V2 may increase **or decrease** these two
fields to that exact result. This is an explicit preparation exception to
preserving skill values/caps; it applies only to internal skill `183` with a
verified enabled anchor. Other existing skills, including Runeforging, Dual
Wield, riding and primary professions, are preserved. Talent selections, spec
count, spells, recipes, profession slots and character flags are preserved.

Already-native rows are no-ops. Zero-valued existing Generic is deferred because
native loading deletes a zero-valued skill before the level update; V2 does not
guess a replacement. Invalid levels/specs, online characters, pending resets,
inactive/disabled anchors, unsupported metadata, custom skill-table columns,
and a resulting skill count over AC's 127-slot limit also defer or block. A
single-spec `63680` wrapper cannot establish second-spec ownership.

## V3: known switch spells and missing Generic

`tc-known-generic-switch-skill-v3` is an explicit **insertion-only** policy.
Native TC `AddSpell` and AC `_addSpell` use SkillLineAbility acquisition method
2 to create a missing Generic skill from an already-known enabled `63644` or
`63645`. That native branch has no requirement to own two specs. The earlier
v1/v2 preparation exclusions were conservative; they are retained unchanged.

V3 allows those known switch anchors with either valid spec count. It inserts
only absent Generic `183`, with value/cap both character level × 5, and retains
the existing verified `2382` anchor. It does **not** purchase a second spec,
activate one, insert any spell, change either build, normalize existing skills,
or modify profession slots, recipes, character/login flags or unrelated data.
Known non-passive switch spells are not cast by the stored-spell loader.

On native skill loading, TC/AC may restore Generic's stock system actions,
including switch buttons, as dependent/temporary spells. SQL inserts no spell
rows. V3 checks a bounded stock action catalog and rejects unknown rewards,
learning/skill effects, skill-modifying auras, scripts or dependency routes.
The proof's `native_generic_reward_spells` lists this native consequence;
`sql_spell_rows_inserted` is zero. Restoration of these actions does not purchase
or change stored spec ownership. Gameplay checks must verify the retained spec
count and active group after login, relog and restart.

```bash
python3 console plan native-skills --migration-inspection latest --skills generic --known-generic-switch --preview
python3 console plan native-skills --migration-inspection INSPECTION_ID --skills generic --known-generic-switch --expect-rows SELECTED_ROWS
python3 console prepare --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Review the README, exact selected rows, complete archived originals and
`native-skill-proof.json` before apply. Proofs record the retained spec count,
active group and zero spec-ownership changes. Use **selected_rows** from the
preview, not a prior snapshot's count. After review:

```bash
python3 console apply --batch BATCH_ID
python3 console status --batch BATCH_ID
```

This option requires `--skills generic` and cannot be combined with
`--normalize-generic`. Existing Generic rows, including malformed ones, stay
unchanged. Online characters, pending resets, inactive/disabled anchors,
unsupported metadata/effects/scripts/dependencies, and exceeding AC's 127 skill
slots still defer. The two-spec `63680` teacher is not an extra v3 anchor;
Runeforging recipes still cannot justify missing Runeforging by themselves.

Full affected originals and original absences, source/world layouts, DBC hashes,
exact fractional source/world fingerprints and selector/numeric/world reader
hashes are sealed. Complete captured context, including deferred characters,
must match at planning. Apply and checkpoint commit atomically; interrupted or
failed transactions roll back. Reruns verify the committed result. Before later
edits or gameplay, `console restore --batch BATCH_ID` removes only the inserted
rows and verifies exact restoration of the captured original state.

The console supplies acknowledgements. Direct SQL requires both:

```sql
SET @skill_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @native_generic_switch_ack='KNOWN_SWITCH_SKILL_ONLY';
```

Retain prior toolkits for earlier archives. No new configuration or source/world
grants are added automatically. This preparation policy does not change migration
skill preservation, core pins/manifests, or approval **UNREVIEWED**. Native
consumer tests use mocked state; full gameplay remains **NOT TESTED**.

## Capture fresh context and review Generic normalization

After any previous preparation apply, capture current state once using the
**saved blocker report**, without rerunning migration preflight:

```bash
python3 console inspect-migration-blockers --report "$BLOCKER_REPORT" --bundle
python3 console plan native-skills --skills generic --normalize-generic --preview
```

Set `BLOCKER_REPORT` to your saved `spell-state-blockers.tsv`. The printed
inspection ID identifies this newly captured state. Preview reports
`inserted_rows`, `normalized_rows`, their sum `selected_rows`, and deferrals.
These are source-state-dependent counts; do not reuse a count from an older
snapshot. Review `native-skill-review.json` in the operation directory, then
use the preview's **total selected count** (replace `COUNT`):

```bash
python3 console plan native-skills --skills generic --normalize-generic --expect-rows COUNT
```

The candidate records old/new values, INSERT versus NORMALIZE_GENERIC, native
anchors and teacher proof. Apply uses separate INSERT and narrow
`UPDATE(value,max)` statements; prepare archives full affected character,
spell, talent and skill originals plus exact prior selected skill values.
Source changes, expected-result verification and the APPLIED checkpoint commit
together. Exact restore deletes only inserted rows and restores original
Generic values/caps. Drift in any affected row, schema, DBC or world metadata
blocks apply/restore, including direct SQL procedure calls for SQL-visible
inputs. Direct SQL cannot independently hash local DBC files; use the console
for their checks. No new archive override exists.

V2 mixed batches need INSERT and DELETE on `character_skills`, plus
`UPDATE(value,max)`. Update-only batches need just that column UPDATE grant;
insert-only batches need no UPDATE grant. SELECT is required in every case.
The console reports missing grants without adding them. For example, the
preparation administrator can grant the additional column permission, replacing
the schema and authenticated writer account with configured values:

```sql
GRANT UPDATE (`value`,`max`) ON `preparation_characters`.`character_skills`
TO 'cleanup_writer'@'localhost';
```

Use the existing prepare/status/apply/restore commands below with the exact new
batch ID. A source reimport or new cleanup session is unnecessary after an
ordinary toolkit update. After a fresh database import, initialize a new
session, recapture evidence and regenerate each needed plan; do not replay old
SQL packages against the new import.

## Preview, review and plan

Use the latest sealed migration-blocker inspection in the current console
session. If none exists, capture the saved preflight report once:

```bash
python3 console inspect-migration-blockers --report /secure/run/spell-state-blockers.tsv --bundle
```

Then preview without an executable package:

```bash
python3 console plan native-skills --preview
```

The command prints the selected inspection ID and counts, and writes private
`native-skill-review.json` in its operation directory. The preview reviews
captured evidence against current TC metadata; it does not revalidate all live
character rows, select a new active batch, or change source data. Use
`--migration-inspection INSPECTION_ID` to select a specific retained inspection.
Use `--skills generic` or `--skills runeforging` to review only one skill policy.

After reviewing the anchors, exact proposed rows and deferrals, create a
candidate with the **preview's selected-row count**, not the first-failure count
from preflight. For example, if the preview selects three rows:

```bash
python3 console plan native-skills --expect-rows 3
```

Planning revalidates the sealed producer/profile/DBC/source identity and the
entire captured spell/talent/skill/character semantic context, including deferred
characters. Effective TC world rows and layouts must match. Changes with equal
row counts still reject stale evidence. Up to 10,000 selected skill changes are supported
per reviewed package. A candidate cannot silently truncate a larger selection.

Review its `README.md`, `manifest.json`, `selected-rows.tsv`,
`native-skill-proof.json`, `excluded-rows.tsv` and SQL. Complete affected
character, spell, talent and skill rows are fingerprinted, including custom
fields. Inserting a skill with custom skill-table columns has no reviewed
default policy and is refused; custom fields on the other archived tables are
preserved. No source writes occur during preview or planning.

## Prepare, apply and exact restore

The configured writer needs SELECT on the preparation schemas, INSERT on
`character_skills` for apply, and DELETE on `character_skills` for restore.
The console never adds source grants automatically. The setup administrator
creates only the new archive and grants its archive-only permissions as usual.

Use the exact batch ID printed by planning:

```bash
python3 console prepare --batch BATCH_ID
python3 console status --batch BATCH_ID
python3 console apply --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Prepare archives complete affected originals and their missing-row evidence;
it does not edit source data. V1 apply inserts only selected absent keys. V2 additionally updates only reviewed
existing Generic values/caps as described above.
The source insert, full expected-result verification and APPLIED checkpoint
commit together. A failure or killed connection before commit rolls back;
status reconciles uncertainty. Completed apply reruns verify the same result.

Before gameplay or further preparation, the exact inverse is:

```bash
python3 console restore --batch BATCH_ID
```

V1 restore deletes only inserted rows; V2 also restores archived Generic values
and caps. Both verify all original affected rows and
absences exactly, and retains the archive. Any changed affected character,
spell, talent or skill state—including a changed inserted value—blocks restore.
World/DBC/schema drift also blocks. Restore reruns verify RESTORED state;
apply-after-restore is refused. Do not weaken guards or reuse/drop archives.

After application, use a fresh migration toolkit/run and fresh target/control
schemas against the cleaned preparation source. Other spell blockers need their
own reviewed policies; these preparation repairs do not establish compatibility for unreviewed teaching
wrappers, skill conflicts outside their scope or unsafe talent ownership. Following a fresh
database import, create a new console session and capture new evidence before
planning; old APPLIED batches are not reusable repairs for a new import.

## Acceptance

Synthetic MySQL checks and protected C++ consumer harnesses are distinct from
native gameplay. In isolated staging verify spec switching/relog; existing
talents and points; unchanged primary-profession slots, recipes, riding and
other skills; Runeforging access/default enchantments; and save/relog/restart
persistence without correction logs. Until executed, these gameplay checks are
NOT TESTED and profile approval remains UNREVIEWED.
