# Missing native skill preparation repair

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

## Reviewed native state

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
row counts still reject stale evidence. Up to 10,000 insertions are supported
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
it does not edit source data. Apply inserts only the selected absent keys.
The source insert, full expected-result verification and APPLIED checkpoint
commit together. A failure or killed connection before commit rolls back;
status reconciles uncertainty. Completed apply reruns verify the same result.

Before gameplay or further preparation, the exact inverse is:

```bash
python3 console restore --batch BATCH_ID
```

Restore deletes only the inserted rows, verifies all original affected rows and
absences exactly, and retains the archive. Any changed affected character,
spell, talent or skill state—including a changed inserted value—blocks restore.
World/DBC/schema drift also blocks. Restore reruns verify RESTORED state;
apply-after-restore is refused. Do not weaken guards or reuse/drop archives.

After application, use a fresh migration toolkit/run and fresh target/control
schemas against the cleaned preparation source. Other spell blockers need their
own reviewed policies; this repair does not resolve Feral Swiftness native aura
mapping, stored teaching wrappers or unsafe talent ownership. Following a fresh
database import, create a new console session and capture new evidence before
planning; old APPLIED batches are not reusable repairs for a new import.

## Acceptance

Synthetic MySQL checks and protected C++ consumer harnesses are distinct from
native gameplay. In isolated staging verify spec switching/relog; existing
talents and points; unchanged primary-profession slots, recipes, riding and
other skills; Runeforging access/default enchantments; and save/relog/restart
persistence without correction logs. Until executed, these gameplay checks are
NOT TESTED and profile approval remains UNREVIEWED.
