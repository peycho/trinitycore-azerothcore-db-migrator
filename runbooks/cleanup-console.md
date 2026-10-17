# Cleanup from the Linux shell

`python3 console` provides the repeatable audit, plan, prepare, apply, status and
restore workflow for a **stopped restored TrinityCore preparation copy**. Use
Python 3.10 or later and MySQL 8 client tools against MySQL 8.4.x. It uses the
standard library; no Python database package is required.

The console supports six reviewed policies: remove verified non-rank talent
records; archive an unavailable second group and queue a single character's
free native talent reset; recover existing item instances from reviewed
zero-entry containers into mail; and explicitly clamp reviewed over-cap skill
values to their existing stored caps; and queue a native active-build reset
while archiving/removing an explicitly reviewed foreign-class talent spell;
and archive eligible disabled direct talent history under the policy below. It never treats every audit finding as a
removal instruction. Missing custom item templates, spell history, skill caps,
other talent conflicts and migration compatibility blockers need separate
review. World schemas, DBC assets and core source checkouts receive no writes.

## Configure once

Retain the original verified backup and an untouched baseline. Restore separate
preparation auth, characters and matching world databases. Keep all cores and
other writers stopped against them. Existing staging/production schemas are
outside this workflow. Starting or deploying a service is not part of cleanup.

Create one private working directory outside version control:

```bash
mkdir -m 700 /secure/preparation-cleanup
cp config/cleanup.ini.example /secure/preparation-cleanup/cleanup.ini
chmod 600 /secure/preparation-cleanup/cleanup.ini
```

Edit that INI file. Set `workspace.directory = .` to keep all generated sessions
under that one directory. Fill in source schemas, MySQL endpoint/users/passwords,
TC/AC DBC directories and core checkout paths. Relative paths resolve against
the config file's directory, regardless of the shell's current directory.
Passwords are literal INI values: `%` is not interpolation. An existing private
MySQL `[client]` file can be selected with `defaults_file` in each role instead.
Use a client file for passwords whose leading/trailing whitespace matters.
No config value is evaluated as shell code.

Set `preparation_copy = yes`, `writers_stopped = yes` and `backup_reference` to
the retained verified backup identifier. These settings are operator assertions,
not service detection or automatic backup verification. Leaving either assertion
false blocks session initialization and cleanup writes.

Select the config once in your shell:

```bash
export MIGRATOR_CLEANUP_CONFIG=/secure/preparation-cleanup/cleanup.ini
python3 console --help
```

Or put a private `cleanup.ini` in the current directory, or use
`python3 console --config /secure/path/cleanup.ini COMMAND`. Global `--config`
precedes the command. The console can also be run through its absolute path.

TC source and DBC paths are required. AC paths may be empty for standalone TC
preparation; when configured, both core checkouts must match the v2 protected
manifests. Actual checkout revisions may differ if their protected content
matches. TC/AC DBC paths do not select the cleanup direction: this console
currently implements **TC source preparation only**. It does not invent an AC
source cleanup policy. No profile approval flag is changed.
Session/batch records include actual Git revisions when available and hashes
of the matched protected manifests. Matching content is compatibility evidence,
not a substitution of configured revisions or native gameplay approval.

## Database roles

| Config section | Purpose and required access |
|---|---|
| `[mysql_audit]` | SELECT only on preparation auth, characters and world. Audit and inspection queries run read-only. |
| `[mysql]` | Cleanup writer: SELECT on those schemas, plus the narrow source DML needed by the selected policy. |
| `[mysql_admin]` | Setup/metadata administrator: direct global SELECT/TRIGGER for complete metadata visibility, CREATE/CREATE ROUTINE on new archive schemas, and GRANT OPTION for their archive permissions. |

All roles inherit the same configured host/port/socket. A separately configured
role has its own credentials; it does not inherit the writer password. If a
role section is omitted, the console uses `[mysql]`; separate roles are
recommended so reads have only SELECT permissions.

For local socket authentication, edit the existing `[mysql] socket` entry to
the server's Unix socket path and use `host = localhost`. Socket mode accepts
`localhost`, `127.0.0.1` or `::1` in the config, passes `--host=localhost` and a
single `--protocol=SOCKET` to MySQL, and omits the TCP port. Remote hosts with a
socket path are rejected before connecting. The console uses TCP when that entry is empty;
setting `host = localhost` alone does not select a socket. A root account using
`auth_socket` requires the matching Linux user and a socket connection. Keep
each section and each setting within a section unique: replace `socket =`
instead of adding a second `socket` entry. Connection changes require a new
console session, audit and plan; they do not require a database reimport.

The administrator grants SELECT/INSERT/UPDATE/DELETE/EXECUTE **only on the
verified batch archive** to the authenticated writer. Source write grants are
never added automatically. The source privileges are:

| Policy | Apply | Exact restore |
|---|---|---|
| Invalid talent values | DELETE on character_talent | INSERT on character_talent |
| Scoped pending talent reset | DELETE on character_talent and UPDATE(at_login) on characters | INSERT on character_talent and UPDATE(at_login) on characters |
| Item recovery | DELETE on character_inventory; INSERT on mail and mail_items | INSERT on character_inventory; DELETE on mail and mail_items |
| Active-build pending reset with reviewed foreign spell | DELETE on character_spell and UPDATE(at_login) on characters | INSERT on character_spell and UPDATE(at_login) on characters |
| Disabled unselected direct talent history | DELETE on character_spell | INSERT on character_spell |
| Reviewed skill clamp | UPDATE(value) on character_skills | UPDATE(value) on character_skills |

Do not give source item_instance UPDATE/DELETE or auth/world writes for these
policies. MySQL credentials are passed through temporary mode-0600 client files,
not process arguments. The config/client files must be owned by the operator
and mode 0600. The workspace must be operator-owned and mode 0700. Keep the
setup administrator account available while its read-only DEFINER guard is used.

## Start a session and audit

After each database import, start a new session:

```bash
python3 console init --label rehearsal-01
python3 console audit --scope all
python3 console inspect-items
```

The console prints each audit's ID and report directory, streams its progress,
and keeps stdout/stderr. `audit` exits **0** for a complete audit without findings,
**1** for a complete audit with findings and **2** for errors/incomplete coverage.
Other successful commands exit 0; failures exit 2, interruption exits 130.
In scripts using `set -e`, handle the expected audit exit 1 explicitly:

```bash
audit_status=0
python3 console audit --scope all || audit_status=$?
if [ "$audit_status" -gt 1 ]; then exit "$audit_status"; fi
```

Read the audit's `summary.tsv`, `findings.tsv`, `coverage.tsv` and `audit.json`.
The item inspection lists every contained reference for zero-entry containers,
including missing characters/items. An inspection row is evidence, not proof
that recovery is safe. Choose exact container IDs only after reviewing ownership
and contents. Full audits can take minutes on large databases; a clean talent
scope alone does not establish source or migration readiness.

## Review direct talent spell history

After a complete full audit, reuse that audit without another migration preflight:

```bash
python3 console inspect-spell-history
```

The latest completed audit in this session is selected automatically; use
`--audit AUDIT_ID` for an explicit retained audit. Existing configuration,
sessions and batches remain usable after installing the updated toolkit. This
command needs only the audit reader's SELECT permissions and creates no archive
schema or executable cleanup batch. It does not change the active batch.

Reports are sealed under the session's `inspections/*-spell-history-*/` directory:
`inspection.json` contains totals, fingerprints and limitations; `summary.tsv`
groups dispositions by spell/class; `spell-history.tsv` lists exact keys, flags
and selected ranks in either group. `input-state.json` retains the read-only
snapshot. Keep these reports private.

The audit's unowned findings mean the exact rank spell is absent from
`character_talent`; another rank of that talent may still be selected. Inspection
separates those cases, disabled spells without a selected family, enabled cases
and foreign-class talents. It defers online characters, pending native resets,
invalid ownership and ambiguous metadata. Neither REVIEW nor DEFER authorizes
deletion, activation or guessed ownership. In particular, a character queued
for native talent reset remains pending until the core executes that reset.

This is a bounded direct `Talent.dbc` rank review, not a semantic migration or
an indirect talent-unlocked spell audit. World overlays, scripts, shared normal
learning routes and runtime dependencies require separate review before an
exact-row archive/apply/restore policy can be prepared. Input table counts and
all direct-history keys/flags must match the sealed audit; ownership and current
character state are read again in one read-only consistent snapshot. Schema,
DBC or report drift blocks inspection. Unrelated same-count data changes are
not detected as a replay of the earlier audit. No profile approval changes.

## Archive eligible disabled direct talent history

After reviewing the inspection totals, use its exact disabled/no-selected-family
count and inspection ID:

```bash
python3 console plan disabled-talent-history \
  --inspection INSPECTION_ID --expect-review-rows 1000
```

Replace the example ID/count. This reuses the retained full audit and inspection;
no new session, database import or migration preflight is required when inputs
are unchanged. Planning performs SELECT only. It recomputes ownership, checks
live direct spell/character/talent state against the inspection, and constructs
effective TC metadata using all seven source DBC assets and these read-only world
tables: `spell_dbc`, `spell_ranks`, `spell_required`, `spell_learn_spell`,
`spell_script_names`, `spell_custom_attr` and `playercreateinfo_spell_custom`.
Missing, malformed, non-InnoDB or incompatible metadata blocks the plan.

Policy `tc-disabled-unselected-direct-talent-history-v1` is a source preparation
decision to discard archived unselected history. It does not declare disabled
records corrupt. It selects only unambiguous class-correct **direct talent**
ranks with `disabled=1`, no selected rank in the family in either group, and no
pending native reset or online character. It excludes whole families with an
enabled stored rank, an alternate learned/skill/default route, teaching or
prerequisite dependants, scripts, mixed ordinary/talent chains, or skill effects.
Selected talent and enabled-spell script bindings must pass the existing source
metadata review. Other ranks of selected talents, enabled history, indirect
children and queued resets remain separate cases. Exclusions appear in
`excluded-rows.tsv` and the candidate's manifest/console totals. The reviewed
population count can therefore exceed the selected deletion count.

Review the generated candidate's `README.md`, `manifest.json`, exact
`selected-rows.tsv`, exclusions and `metadata.json`. Only then use the existing
batch workflow:

```bash
python3 console prepare
python3 console status --batch BATCH_ID
python3 console apply
python3 console status --batch BATCH_ID
```

Prepare creates a new archive schema and saves full original affected character,
spell, talent and skill rows, including custom fields. It does not change source
data. This can archive substantially more rows than it removes; the manifest's
`archived_rows` gives the exact counts before prepare. Apply deletes only exact
reviewed `(guid,spell)` pairs. Talents, enabled spells, lower ordinary ranks,
spec counts, skill values/caps, profession slots, login flags, items and quests
receive no writes. All work in each prepare/apply/restore phase is transactional;
incomplete phases roll back, while successful reruns verify committed state.

Full affected rows are hashed in primary-key order, with bounded per-character
digests rather than a single concatenation of millions of source rows. Limits:
500000 reviewed history rows, 40000 affected characters, 10000 original rows per
character/table, 1 MiB of field data per row and 5000000 total archived rows. Exceeding a bound blocks instead
of truncating. Both old/new spell sets, complete archive data, world content,
DBC assets, column layouts and profile fingerprints are guarded. Same-count
changes, online/pending-reset transitions and edited archives block execution.

For exact reversal **before gameplay or further preparation changes**:

```bash
python3 console restore --batch BATCH_ID
```

Restore inserts only the removed full spell rows, verifies the complete original
affected state and retains the archive. It refuses changes to affected
character/spell/talent/skill rows, and apply-after-restore is refused. Restore multiple
cleanup batches in reverse order. After applying a batch, run a new full audit
and inspection before planning any further history batch. Source changes require
a fresh migration into new target/control schemas. This policy changes no
migrator rejection rule or release approval; native load/save, spec switching,
relearning and trainer acceptance still need isolated gameplay checks.

## Recover items without replacing them

For example, after reviewing containers 100 and 200:

```bash
python3 console plan items --containers 100,200
python3 console prepare
python3 console status --batch BATCH_ID
python3 console apply
```

Replace `BATCH_ID` with the printed ID. `prepare`, `apply` and `restore` default
to the currently selected plan; pass `--batch ID` to address a particular batch.
Inspect its manifest, selected rows, generated SQL and prepared status before
apply. Setup and prepare leave source data unchanged. Setup creates only the
new archive; prepare archives full original placements and item rows, including
custom fields such as transmog/enchant, and creates the proposed mail rows there.

The policy requires existing, offline recipients with existing auth accounts,
matching character/container/item ownership, and zero-entry containers with
exactly the reviewed contents. It blocks dangling item references, mixed owners,
nested contents, unexpected container placements, duplicate mail/guild/auction
roots, schema drift, triggers and foreign-key side effects. Unsupported source
representations block the batch instead of guessing replacement items or bags.

Apply atomically replaces those exact inventory references with mail attachments.
Existing item GUIDs, counts, custom attributes and zero-entry container instances
are retained. Missing item templates do not cause instance deletion. Each mail
has at most 12 attachments; larger recipient groups split deterministically.
Mail IDs are above both current mail IDs and dangling attachment mail IDs.
Recovery mail has normal **30-day expiry**. Apply must follow preparation within
24 hours; stale plans require a newly reviewed batch. Do not infer native mail
collection acceptance from a committed SQL transaction.

## Remove verified non-rank talent records

Use the count from the completed audit's summary, not a historical example:

```bash
python3 console plan talents --expect-rows 42
python3 console prepare
python3 console status --batch BATCH_ID
python3 console apply
python3 console audit --scope talents
```

This uses the latest completed audit **in this session**. `--audit AUDIT_ID`
selects a particular retained audit. All seven audit reports, producer/layout
fingerprints and matching DBC hashes must verify. Only
`TALENT_VALUE_IS_NOT_RANK_SPELL` keys are selected; every value is independently
checked against the TC rank catalog. A selectable talent rank is never removed
under this policy, even if a report was edited and re-sealed. Talent-entry IDs
are not reinterpreted as guessed spell ranks. All affected character rows and
all their current talents are archived, not just the deletion candidates.

Preparation checks the exact invalid set and total talent count, then freezes
current full affected state for review. An earlier audit is provenance, not a
hash of every character column. Valid talents, ordinary/dependent spell ranks,
skills, profession slots, glyphs and items receive no writes. Apply and restore
reject later same-count changes to the affected talent sets or character state.

## Queue one reviewed character's native reset

For a character whose remaining reviewed conflict is an unavailable second
build, select only that character, for example GUID 12345:

```bash
python3 console plan reset-talents --guid 12345
python3 console prepare
python3 console status --batch BATCH_ID
python3 console apply
python3 console audit --scope talents
```

The bounded policy requires an offline character with active group 0, configured
group count 1, a nonempty active build and an exact unavailable group 1 of
unambiguous class talent ranks present in Spell DBC. Other states are rejected.
The plan records character/account/name/level/class/spec state and exact keys.
It neither enables dual specialization nor relocates ranks between groups.

Apply archives/removes the unavailable ownership rows and sets only
`at_login | 4`, preserving other flags. The active ownership rows remain until
the core unlearns their spells and dependencies during its free native reset.
**APPLIED means reset pending next login**, not that points/spells have already
been reset. Both reviewed cores consume this flag; the migrator preserves it.
Realm configuration determines the resulting free points. Pending reset does
not bypass any migration spell authorization/compatibility guard.

## Queue an active-build reset and remove a reviewed foreign talent

This separate policy supports an explicitly chosen character with a populated
active build and **empty inactive builds**. It supports one or two configured
specs and either active group. It does not reset another populated spec or
change spec availability. Use the exact reviewed talent-row count:

```bash
python3 console plan reset-active-talents \
  --guid 12345 --remove-spells 12284 --expect-talent-rows 81
python3 console prepare
python3 console status
python3 console apply
python3 console status
```

Replace the example GUID and count with the reviewed character's values. Keep
your current config, workspace and session; no new full audit or migration
preflight is needed to generate this plan. Planning reads just this character
and the source metadata. It records a full byte-sensitive fingerprint of every
character, talent, spell and skill row for that GUID, including custom fields.
Setup creates a new archive. Preparation snapshots those complete original rows
without modifying source data. Inspect its manifest, selection and status.
Archived spell fields in status are hex encoded so binary custom columns can
be reported without losing bytes or breaking UTF-8 output.

This version intentionally supports only explicitly selected warrior talent
`12284` on a different class, with source flags `active=1, disabled=0`, a verified
DBC talent rank and the reviewed dummy effect shape. It does not infer a general
spell-history deletion policy. It rejects unknown, own-class, additional enabled
foreign talents or unsupported foreign selections, changed talent counts,
conflicting talent ranks, a nonempty inactive build and missing enabled selected
talent state. The manifest reports the selected build's actual DBC point cost;
a large count does not authorize automatic normalization of other characters.

Apply **preserves all active talent ownership** so the native reset can unlearn
its spells and dependencies correctly. It removes only the reviewed foreign
spell row and sets `at_login | 4`, preserving other flags. The complete original
spell row, including custom columns, remains archived. The native class reset
would skip the foreign-class talent, which is why its explicit removal is a
separate part of this approved preparation policy.

**APPLIED means FREE NATIVE RESET PENDING LOGIN.** The selected talent rows and
point allocation remain in the stopped source until native reset runs. A clean
talent audit or successful SQL apply does not prove the reset finished. Both
reviewed cores reset the active build; the empty-inactive-build guard avoids
leaving another selected build behind. Free points use native realm settings
(71 at level 80 with `Rate.Talent=1`). No GM/RBAC permission or rate setting is
changed. Verify an empty build and the expected free points after isolated
native login, then save/relog and switch both specs.

Pending reset does not bypass migration blockers; source spell-history,
rank-chain, skill and dependency issues still require their own review. It
introduces no additional spell grants and does not remove ordinary spells,
recipes, professions, glyphs, action bars, items or mail through SQL.

For an exact inverse **before native login or further changes**, run:

```bash
python3 console restore --batch BATCH_ID
```

Restore reinstates the original foreign spell and login flags only after all
preserved character/talent/spell/skill state matches. It refuses native-reset
or other drift, and retains the archive. Interrupted operations roll back their
source changes and checkpoint together; inspect `status` before retrying.
After a fresh import, start a new session and generate a new plan; old archives
are not replayed. An updated toolkit needs its complete `console`, `lib` and
`tools` files; retain the private INI and existing workspace.

## Clamp explicitly reviewed over-cap skills

Use this only after deciding that the existing stored caps are the limits to
retain. A finding compares stored `value` with stored `max`; it does not prove
that the cap agrees with the character's level, learned profession/riding tier
or custom server settings. Both reviewed loaders recalculate eligible
level-based caps. Review those facts first; this policy does not infer GM
status, invent a higher cap or learn a missing tier.

For an explicitly approved reduction, use the actual full-audit count:

```bash
python3 console plan skills --expect-rows 42
python3 console prepare
python3 console status --batch BATCH_ID
python3 console apply
python3 console audit --scope all
```

The latest audit must be complete with scope `all`; `--audit AUDIT_ID` can
select a retained full audit from this session. Planning verifies all seven
report checksums, producer/layout and DBC fingerprints, exact keys and numeric
evidence against the live invalid set. It selects only existing, offline
characters and known skills with `0 < max < value`, with at most 10,000 rows.
Orphan skill rows are excluded. Missing/zero caps, unknown skills, changed
inputs, computed/invisible columns, automatic `ON UPDATE` columns, source
triggers and relevant foreign keys block the operation.

`selected-rows.tsv` and prepared status show GUID, skill, original value,
unchanged maximum and planned value. Preparation snapshots full affected
character rows and **all** their skills, including custom fields and retained
in-range skills. Apply sets only each selected `value = max`; no skill row,
cap, spell, recipe, talent, profession slot or character field is changed.
For example, an approved `450/300` profession becomes `300/300`, and an approved
`150/75` riding row becomes `75/75`. It does not unlock the higher tier.

The writer needs only `UPDATE(value)` in addition to SELECT for this policy.
The console does not grant source privileges automatically. A denied UPDATE
reports an administrator GRANT statement for the actual authenticated writer;
no account host has to be guessed. Grant it on the preparation schema only,
then retry the same prepared batch. No new session or audit is needed merely
because that grant was added.

Apply, its archive state and timestamps commit together; incomplete operations
roll back. Matching reruns verify the current result. Full affected character
and skill comparisons reject same-count edits before apply/restore. Use
`python3 console restore --batch BATCH_ID` for the exact original values before
gameplay or other edits; restore intentionally reinstates the audit findings.
This explicit preparation policy is separate from spell reconstruction, which
continues to preserve skill values/caps and profession ownership.

## Reports, failures, retries and restoration

Everything generated belongs under the configured directory:

```text
workspace/
  current.json
  operations/                         # init/session selection and early errors
  sessions/<session-id>/
    session.json                      # server UUID, schemas, backup, paths
    latest-audit.json
    active-batch.json
    audits/<audit-id>/                 # native seven-report audit + checksums
    inspections/<inspection-id>/      # contained-item evidence
    batches/<batch-id>/                # manifest, selected keys, SQL, README, checksums
    operations/<operation-id>/         # journal, result/status, errors and traces
```

Temporary credential files live in a private `.credentials/` subdirectory and
are removed after use. Do not publish the workspace; it contains player data.
Session/batch IDs are printed so scripts need not supply output paths repeatedly.

Every operation records STARTED and COMPLETE or FAILED_OR_UNCERTAIN. Errors
print a stable code, message, next-step hint and the private `error.json` path.
The same operation directory retains a redacted traceback and applicable
stdout/stderr, result.tsv and status.tsv. A workspace lock rejects concurrent
console commands. Source-side transactional guards still protect against drift;
the lock is not a substitute for keeping external writers stopped.
Operation journals also record the tool/template hashes used by that command;
plan operations retain their read-only character/item evidence on failure.

| Error/result | Action |
|---|---|
| `TOOLKIT_INCOMPLETE` / `TOOLKIT_FILE_UNREADABLE` | Install the named missing file from the same release or fix its read permissions in the toolkit path shown. Keep the config/workspace. No new session, audit or database import is required for a file-only repair; the command stopped before any database query. Git-based delivery must include new SQL templates as well as Python files. |
| `CONFIG_SYNTAX` | Correct the reported INI line. For duplicate sections/settings, edit the existing entry and remove the duplicate. Values are never printed. No database connection is made. |
| `CONFIG_SOCKET_HOST` | Use a local host for Unix socket mode, or clear `socket` to select TCP. |
| MySQL error 2047 in an older toolkit | Set `[mysql] host = localhost` when using a socket, or update the console. Older code combined a numeric host with socket protocol. After a connection setting changes, initialize a new session and regenerate its audit/plan; no reimport is needed. |
| `PRIVATE_FILE_REQUIRED` / `PRIVATE_DIRECTORY_REQUIRED` | Fix owner/modes: config/client files 0600, workspace 0700. |
| `MYSQL_FAILED` | Inspect the MySQL error and grants. Preserve evidence. Query status before retrying; a lost connection can occur after commit. |
| `CORE_PROFILE_MISMATCH` / `DBC_DRIFT` | Restore reviewed metadata or establish compatibility and generate a new audit/batch. Never bypass the guard. |
| `PACKAGE_CHANGED` | Generated files no longer match their checksums. Keep evidence and generate a new candidate. |
| `PARTIAL_ARCHIVE` | Setup DDL was incomplete. Retain/inspect it; the console never drops or silently reuses it. Generate a new batch after resolving the cause. |
| `RESET_STATE_UNSUPPORTED` / `ITEM_RECOVERY_BLOCKED` | Review the exact evidence; no broad deletion, guessed ownership or replacement rank/item is performed. |
| `SKILL_SELECTION_MISMATCH` / `SKILL_INPUT_DRIFT` | Compare exact skill keys, values, caps and the expected count. Changed source state needs a fresh full audit and plan. |
| `SKILL_CLAMP_UNSUPPORTED` / `SKILL_CHARACTER_UNAVAILABLE` | Review missing/zero caps, unknown skills or online/missing characters. No cap or skill ownership is guessed. |
| `SESSION_ENDPOINT_CHANGED` | Check the named identity fields. After intentionally changing connection settings or importing a fresh copy, run `init`, then a fresh audit and plan. A connection-only change does not require a database reimport. |
| Audit exit 1 | Audit completed and found rows; review the report. This is not a client/database failure. |

After an interrupted operation, use:

```bash
python3 console status --batch BATCH_ID
python3 console apply --batch BATCH_ID
```

The archive state is authoritative. Matching APPLIED reruns verify without
changing data or timestamps; incomplete transactions roll back. Setup DDL is
separate and may remain partial. Existing archives are never overwritten.

For exact reversal **before gameplay or further edits**:

```bash
python3 console restore --batch BATCH_ID
```

Restore in reverse application order. It verifies the complete prepared
representations, restores exact originals and retains archives. Changed
character state, item attributes, claimed/expired recovery mail or occupied
original slots cause rejection. A repeat restore verifies the original result;
apply-after-restore is refused. An older talent batch's checks can remain
blocked until later talent/reset batches have been restored.

List retained sessions or explicitly select an older session for inspection:

```bash
python3 console sessions
python3 console sessions --use SESSION_ID
```

Selection requires the same configured server/schemas and does not make stale
archives applicable to a newly imported database. Never edit current.json or
archive metadata to force a replay.

## Repeat after a fresh database import

1. Preserve the earlier workspace, audits, archives and execution reports.
2. Restore the verified untouched dump into stopped preparation schemas using
   your database restore procedure. Keep the original baseline unchanged.
3. Update the config's endpoint/schema names and `backup_reference` if needed;
   verify the preparation-only assertions and role grants for those schemas.
4. Run `python3 console init --label rehearsal-02`. A new session and fresh
   archive names are created, even when server UUID, schemas and IDs are identical.
5. Run a fresh full audit and item inspection. Review actual findings/counts;
   generate **new** item/talent/reset plans as applicable. Do not import SQL
   packages from the old session or reuse its expected row counts blindly.
6. Prepare, inspect and apply each selected policy. Reaudit between categories
   and run a final full audit. Preserve custom item definitions and review
   remaining unsupported categories separately.
7. Preserve the prepared database dump and this session's records. Start a
   **new migration with fresh target/control schemas**; source edits invalidate
   old migration checkpoints. Then perform native gameplay acceptance.

`init` manages cleanup sessions; database dump restore remains an explicit
operator operation. This console neither deploys services nor enables
CleanCharacterDB. A clean audit, APPLIED batch or migrated database READY state
is separate from native gameplay and release acceptance. The compatibility
profile stays **UNREVIEWED** until all existing acceptance gates actually pass.
