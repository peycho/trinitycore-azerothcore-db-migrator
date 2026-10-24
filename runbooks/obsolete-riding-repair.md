# Retire forbidden legacy Wolf Riding

`plan obsolete-riding` uses the separate policy
`tc-obsolete-wolf-riding-spell-skill-retirement-v1`. It archives/removes **both**
Wolf Riding spell `825` and legacy skill `149`. Modern Riding skill `762`, its
known ranks, mounts, items, both talent builds, every other skill/cap, profession
slots and login flags remain unchanged. SQL grants no spell or skill.

Both native skill loaders reject `149` for incompatible race/class combinations.
AC also rejects its spell. This repair requires existing modern riding; it does
not convert old riding into a new rank or clean up other obsolete skills.

## Configure and preview

Use the existing [cleanup console configuration](cleanup-console.md) on a
stopped restored preparation copy. Install the complete toolkit, retaining old
toolkits for earlier archives. Keep the session when source identity is unchanged.
A fresh import needs a new session, inspection, selection and archive.

Existing TC/AC world, DBC and source paths are required. Verify effective TC
`PlayerStart.AllSpells=0` and AC `PlayerStart.CustomSpells=0` and retain their INI
assertions. These settings do not modify either core. Audit/writer roles need
SELECT on source inventory, mail, mail_items and item_instance, and both worlds'
item_template and playercreateinfo_skills, as well as normal spell metadata.
Item column names resolve case insensitively; original layouts remain sealed.

Refresh the inspection after changed readers or source edits. The saved report
supplies scope; no new full audit or preflight is needed just to capture context:

```bash
python3 console inspect-migration-blockers --report /path/to/spell-state-blockers.tsv
python3 console plan obsolete-riding --migration-inspection latest --preview
```

Review `obsolete-riding-review.json` at the printed path. Preview changes no
source rows and creates no SQL package or active batch. Historical counts and
GUIDs do not authorize selection on a fresh snapshot.

## Selection boundaries

Each offline selected character needs enabled `825`, skill `149` at `1/75`, and
no eligible `149` entry in either catalog. Modern `762` must already have equal
value/cap at `75`, `150`, `225` or `300`, with one matching enabled rank among
`33388`, `33391`, `34090`, `34091`. Higher known ranks above the stored cap defer.
Both specs remain authoritative. Invalid ownership, pending talent resets,
unsupported character state or flags defer.

The exact mechanics, learning/requirement graphs, skill abilities, race/class
entries, tiers and native consumers must match the fixed catalog. Teacher `6746`
must be absent, and matching starting-skill routes defer. Both custom starting-
spell settings must remain off. No missing prefix, skill, rank or mount is granted.

Every owned instance, inventory reference and mail attachment is checked against
both worlds' RequiredSkill, RequiredSkillRank and requiredspell. Actual mail
recipients are included even if the attachment receiver differs. Missing
instances/templates or any item requiring `149`/`825` defer the character.
Items are never moved or changed. Layouts and scoped requirements are rechecked
at prepare/apply/restore, including direct SQL. Serializable guards prevent
concurrent conflicting item requirement changes during apply.

## Archive, apply and restore

Use preview **selected_rows** for `COUNT`: it counts pairs, so each selected pair
removes one spell row and one skill row. Replace `BATCH_ID` with the new output:

```bash
python3 console plan obsolete-riding --migration-inspection latest --expect-rows COUNT
python3 console prepare --batch BATCH_ID
python3 console status --batch BATCH_ID
python3 console apply --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Prepare archives complete affected character, talent, spell and skill originals,
including custom fields; source stays unchanged. Review the generated README,
selected/excluded rows, `obsolete-riding-native-proof.json` and status. Apply
deletes the exact pair and updates its checkpoint in one transaction. Late
errors and disconnected transactions roll back both deletions. Reruns verify
phase state. Status shows retired spell/skill rows and retained modern riding.

Apply requires DELETE on source character_spell **and** character_skills. Restore
requires INSERT on both; the tool does not add source grants. Direct SQL also
needs `@obsolete_riding_ack='RETIRE_FORBIDDEN_WOLF_RIDING_PAIR_RETAIN_MODERN_RIDING'`
plus normal stopped-copy/custom-start-off assertions.

Before gameplay or later edits, use the original toolkit/config for the exact
inverse:

```bash
python3 console restore --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Restore checks the full original/expected affected state and restores complete
rows. Changed riding, talents, custom fields, item requirements, worlds or archive
evidence block it. Reverse dependent later batches first and retain the backup.

After reviewed batches, start a new migration run and run preflight. This repair
bypasses no migration check. Native consumer/disposable SQL tests are separate
from gameplay acceptance, which remains **NOT TESTED**; release approval remains
**UNREVIEWED**.

## Opt-in native-invalid item evidence (v2)

`--native-invalid-items` selects the separate
`tc-obsolete-wolf-riding-native-invalid-items-v2` contract. The default v1 mode
still defers incomplete item requirements.

This mode recognizes only two exact cases: a positive item GUID whose joined
instance and template fields are all NULL, or an existing entry-zero instance
with a known owner field and no template in either world. It explicitly verifies
that **neither world defines item template zero**. Native inventory queries
exclude missing instances; mail uses a left join, and both native item loaders
reject an undefined template before reading instance fields or requirements.
Additional pinned item loaders and inventory/mail query sources are checked.

These invalid records cannot establish a usable item requirement on the retired
riding pair. The repair records their GUIDs and reasons but leaves their instances,
references, mail, container contents and all other item data unchanged. It does
not repair corruption or authorize a native login/deletion path. Every valid
item keeps both-world requirement checks; missing **nonzero** templates, partial
NULL evidence and zero item GUIDs continue to defer.

After installing the complete updated toolkit, refresh context using the saved
report, including when an earlier pair was applied. Use the same current session
if the source identity is unchanged:

```bash
python3 console inspect-migration-blockers --report /path/to/spell-state-blockers.tsv
python3 console plan obsolete-riding --migration-inspection latest --native-invalid-items --preview
python3 console plan obsolete-riding --migration-inspection latest --native-invalid-items --expect-rows COUNT
```

Use the actual preview count, not an old snapshot's count. Prepare/apply/status/
restore follow the same workflow above. Proofs include
`native_invalid_items_retained`, `valid_items_checked` and the verified absence
of zero templates. Fresh item/requirement reads and serializable SQL guards
reject resolved references, changed entries, added definitions and any newly
defined template zero at every phase. Native source/catalog fingerprints and
the distinct acknowledgement are sealed. Direct SQL needs
`@obsolete_riding_ack='RETAIN_NATIVE_INVALID_ITEM_ROWS_CHECK_ALL_VALID_REQUIREMENTS'`;
the v1 acknowledgement cannot apply a v2 batch.

Earlier archives require their original toolkit for exact restoration. This
mode grants no item or riding state and bypasses no migration item checks.
Gameplay remains **NOT TESTED**; approval remains **UNREVIEWED**.
