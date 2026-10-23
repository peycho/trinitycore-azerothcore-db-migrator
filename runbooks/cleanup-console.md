# Cleanup from the Linux shell

The optional [ordinary training-prerequisite repair](#reviewed-training-prerequisites-ordinary-v4)
archives wholly disabled Divine Spirit/Prayer and Nature's Grasp history under
exact requirement-only contracts, preserving enabled counterparts and skills.
Earlier history policies retain their exclusions.

`python3 console` provides the repeatable audit, plan, prepare, apply, status and
restore workflow for a **stopped restored TrinityCore preparation copy**. Use
Python 3.10 or later and MySQL 8 client tools against MySQL 8.4.x. It uses the
standard library; no Python database package is required.

The separate [ordinary spell eligibility repair](spell-eligibility-repair.md)
uses `plan spell-eligibility --migration-inspection latest --preview`. It requires
read-only AC world/DBC inputs, verified TC `PlayerStart.AllSpells=0` and AC
`PlayerStart.CustomSpells=0`.
It deliberately permits reviewed enabled-row retirement when both catalogs
reject the complete ordinary rank family, while protecting skills and talents.
It does not change existing history policies or migration rejection rules.

The separate opt-in `--absent-teachers` eligibility v2 mode reviews exact stock
Conjure Water/Doomguard incoming teachers only when all are absent. Known,
skill, multi-child, scripted and modified teachers still defer. Use the
[v2 preview and archive procedure](spell-eligibility-repair.md#opt-in-absent-single-child-teachers-v2);
normal prepare/status/apply/restore commands remain unchanged.

New eligibility batches also use an exact fractional numeric fingerprint.
Historical archives keep their original guards, which can miss fractional-only
FLOAT/DECIMAL changes. Do not rely on old guards after gameplay or edits; retain
the unchanged stopped baseline and original toolkits for restoration.

The console supports reviewed policies to remove verified non-rank talent
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
| Missing native Generic/Runeforging skills (v1) | INSERT on character_skills | DELETE on character_skills |
| Explicit Generic normalization (v2) | UPDATE(value,max); INSERT if missing rows selected | UPDATE(value,max); DELETE if inserted rows selected |
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

## Review a saved migration blocker report

[`inactive-legacy-spells`](inactive-legacy-spells.md) is a separate opt-in policy
for unavailable old Bloodthirst book rows. It archives only exact inactive/
non-disabled catalog members, keeps existing active members and current talent
23881, and changes no skills or builds. No legacy rank links or new grants are
inferred. It deliberately discards unavailable known history, so review its
native proofs and exact selection before apply. Other inactive states defer.

The separate
[`talent-ownership --selected-direct-passives`](talent-ownership-repair.md#opt-in-selected-direct-passive-ranks)
retires only unselected higher direct passive ranks in five verified families.
Existing lower selected talents are authoritative; AC restores their exact
active passive auras. TC does not reconstruct these direct lower ranks. This
changes incorrect passive effects deliberately while preserving both builds,
skills, professions and flags. Both effective worlds/DBC and explicit native
custom-start-off settings are required. Pending resets remain deferred. Use
`--preview` and its exact `selected_rows`; preparation, atomic apply and exact
restore use the existing two-world archive workflow.

[`talent-ownership --native-passive-rekey` v5 policy](talent-ownership-repair.md#opt-in-already-known-selected-passive-ranks-v5)
updates conflicting enabled passive child keys to selected lower ranks already
known through verified TC predecessor recursion. Both builds and skills remain
unchanged. It requires one enabled anchor per reviewed chain, an absent lower
destination and stock spell-table columns. Preview first; review `spell-rekeys.tsv`
and the native proofs. This changes keys rather than deleting rows and needs
`UPDATE(spell)` for apply and inverse restore.

The opt-in
[`talent-ownership --reviewed-aura-aliases` v4 policy](talent-ownership-repair.md#opt-in-reviewed-paladin-area-aura-aliases-v4)
can retire isolated unselected paladin area-aura talent history under four exact
protected alias/helper contracts, including enabled rows. Both-spec ownership,
skills/caps and unrelated state remain preserved; unknown scripts and selected
families still defer. Preview and review its native proofs before any apply.

The opt-in
[`talent-ownership --native-passive-prefixes` v3 policy](talent-ownership-repair.md#opt-in-retained-native-passive-prefixes-v3)
retires disabled passive predecessors only when retained enabled higher anchors
already justify their native restoration. It also retires stale unowned higher
child history within those exact families, including enabled rows; no talent
selection, skill, rank grant or flag rewrite is inferred. Preview first, use
`selected_rows` as the expectation, and review `prefix_restore_anchors` before
prepare/apply. Missing anchors, direct talent conflicts and pending resets defer.

The separate insertion-only
[`native-skills --skills generic --known-generic-switch` v3 policy](native-skill-repair.md#v3-known-switch-spells-and-missing-generic)
accepts verified known switch anchors without inferring a second spec. It
preserves existing skills and requires an exact selected-row expectation.

For isolated foreign-class talent families, use the explicit
[`talent-ownership --foreign-class-families` v2 policy](talent-ownership-repair.md#opt-in-unselected-foreign-class-families-v2).
It preserves shared skill spells such as Dual Wield and both selected builds.
Its expectation is selected rows; ordinary-history expectations use reviewed
candidate rows as documented in their own sections.

When several migration spell categories remain, capture their complete source
context together instead of deleting every audit finding or repeatedly rerunning
preflight. With the existing preparation config and session:

```bash
python3 console inspect-migration-blockers \
  --report /secure/migration-reports/RUN_ID/spell-state-blockers.tsv --bundle
```

This performs SELECT only through the configured audit account. It creates no
archive schema, cleanup batch or executable SQL and leaves the active batch
unchanged. The saved file is treated as data, never as instructions or SQL.
The expected input is the migrator's four-column, first-failure-per-character
TSV. Invalid headers, duplicate GUIDs, numeric/control-character errors and
oversized inputs fail with structured errors. Limits are 128 MiB, 40000 reported
characters, 16384 characters per detail and 5000000 captured semantic rows;
exceeding a limit blocks instead of truncating.

The private `inspections/*-migration-blockers/` directory contains:

- Original `spell-state-blockers.tsv` and its SHA-256 fingerprint.
- `groups.tsv`: reason, spell, reported flags, exact detail and character count.
- `source-state.json`: all spell flags, both talent groups, skill values/caps and
  character race/class/level/spec/online/login state for every reported GUID.
- `character-context.jsonl`: the same complete per-character context beside its
  reported blocker, with explicit comparisons where the report supplies flags.
- `tc-world.json`: effective TC world input tables with layouts and fingerprints;
  `spell-metadata-profile.json` and DBC hashes identify the metadata interpretation.
- `inspection.json`, `README.md` and `SHA256SUMS`: provenance, limits and sealed
  evidence. Failures retain an `INCOMPLETE` directory plus the operation journal.

Retain or transfer the whole private directory for consolidated offline review.
The optional `--bundle` writes `migration-blocker-context.tar.gz` into the private
operation directory and prints its path. `bundle.json` records its SHA-256; the
archive contains exactly the sealed inspection files and no client config.
No passwords are exported, but player evidence must remain private. This captures
a **new** read-only source snapshot, not a replay of the migration run. Missing
characters and mismatched reported flags are recorded; the saved file does not
prove the current source is unchanged. Character tables share one consistent
snapshot; TC world metadata uses a separate consistent snapshot. Target-world
overlays are not captured. These semantic fields are not full-row restore
archives and cannot be used as a cleanup package.

The report shows only the first failure per character. Direct talent history
does not cover all trained/indirect ranks, and an unsupported temporary chain
can be valid source data with no reviewed target representation. Missing skills
or prerequisites do not authorize grants. Enabled records do not authorize
deletion. Review complete ownership, effective relationships and native consumers
before implementing a fix or preparing exact source changes. Migration approval
remains `UNREVIEWED`.

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

Instead of supplying `--inspection`, any history planning mode can take
`--audit FULL_AUDIT_ID`. It creates and seals a fresh read-only inspection from
that complete audit, then uses it for the candidate. This avoids manually
copying a new inspection ID. The source must still match the audit's guarded
inputs; this option does not run a new full audit or bypass stale-input checks.
The two evidence options are mutually exclusive. Planning still makes no source
writes and retains the new inspection if a later eligibility check fails.

If the first batch leaves `DEFER_SCRIPTED_TALENT_FAMILY` rows, review the exact
script families before broadening the policy. A second, explicit mode accepts
only effective TC bindings already protected by the compatibility profile's
`NO_SPELLBOOK_MUTATION` contract:

```bash
python3 console plan disabled-talent-history \
  --inspection NEW_INSPECTION_ID --expect-review-rows 1000 \
  --include-reviewed-scripts
```

After applying an earlier batch, run a new full audit and
`inspect-spell-history` first, then use that new inspection's exact
`REVIEW_DISABLED_NO_SELECTED_FAMILY` count. Do not reuse an inspection of the
pre-cleanup spell set. Starting over on a fresh database import requires a new
session, audit and inspection; do not reuse old archive schemas or generated SQL.

This option selects policy `tc-disabled-reviewed-script-talent-history-v2`;
the default remains v1. Every binding on every rank of the direct talent family
must pass the reviewed contract. Unknown scripts, runtime talent-aura helper
contracts and cast-only research contracts are insufficient. Independent
learning routes, teaching/prerequisite dependants, mixed chains, skill effects,
selected families, enabled family conflicts and pending resets remain excluded.
Pinned TC `AddSpell` returns for a newly loaded disabled spell before passive
casts, learned-spell effects and skill/profession updates. The alternate-route
guards also exclude earlier runtime entries that could take a different path.
No server login, aura removal, C++ change or migration blocker override is used.

The candidate records accepted selected-family bindings in the manifest,
`scripted_selected_rows`, and all direct-family binding reviews in
`scripted-family-review.tsv`. A reviewed binding is a script-contract result,
not permission to delete a family excluded by another guard; the exact deletion
set is still `selected-rows.tsv`. V1 and v2 use the same complete archives,
transactional apply/restore and source/world/DBC drift guards. Existing v1
batches remain usable under their original policy. Migration approval remains
`UNREVIEWED`.

For remaining teaching/prerequisite dependencies or mixed direct/trained rank
chains, a separate explicit policy can review a complete related group:

```bash
python3 console plan disabled-talent-history \
  --inspection NEW_INSPECTION_ID --expect-review-rows 1000 \
  --include-inert-relations
```

**This v3 option can remove related disabled spell rows as well as direct talent
rows.** Review both counts before preparing or applying. It implies the reviewed
script checks; the default and `--include-reviewed-scripts` modes keep their
original v1/v2 behavior. Policy `tc-disabled-unselected-talent-closure-v3`
starts only from the inspection's disabled/no-selected-family direct ranks.
It expands verified rank membership, TC world/DBC learned-spell edges and
`spell_required` dependants. It selects only isolated groups whose present rows
are all disabled, with no selected talent in either spec and no outside incoming
learning/dependency edge. A single enabled related spell defers the entire
character/family group, including inactive (`active=0, disabled=0`) spells.

Shared talent owners, unknown script contracts, skill rewards, custom starting
spells, profession/secondary/riding recipes or tiers, skill/dual-wield effects,
unsupported corrections, pet learning and malformed relationships remain
deferred. Rank groups are collapsed before iterative cycle detection; cycles,
groups above 4096 spells and review evidence above 5000000 nodes are rejected
or deferred without truncation. At most 500000 exact rows can be selected.
This uses a fresh read-only complete spell-state supplement for reviewed GUIDs,
then rechecks it in the same snapshot as the full original-row fingerprints.

The manifest distinguishes `selected_root_rows` and `selected_related_rows`;
`selected_rows` is their total. `excluded-rows.tsv` continues to list deferred
direct inspection rows. `relationship-review.tsv` records each accepted group's
GUID, talent family, spell, direct/related role and original flags. Absent nodes
are explicitly `ABSENT_NO_GRANT`; no spell is inserted or activated by apply.
`relationship-edges.tsv` records the verified dependency edges; rank membership
is protected by the retained world/DBC fingerprints. These reports and the exact
selection are sealed with the candidate. SQL prepare/apply/restore, checkpoints,
complete original archives and metadata drift guards are shared with v1/v2.

Native source rationale: new disabled `AddSpell` returns before cast/learn/skill
effects, but it first removes other direct talent ranks. `RemoveSpell` can recurse
through higher ranks, prerequisites and learned children. Therefore this policy
checks the whole related group, preserves every enabled availability and selected
build, and refuses profession/skill effects even on absent rank members. It does
not simulate login, reset builds, infer missing ownership or authorize clearing
enabled unowned spells. Those and pending native resets remain separate work.

An explicit reviewed-route mode adds two teaching-wrapper contracts and
one shaman-specific root-only contract:

```bash
python3 console plan disabled-talent-history \
  --audit FULL_AUDIT_ID --expect-review-rows 1000 \
  --include-reviewed-routes
```

Policy `tc-disabled-reviewed-talent-routes-v4` implies v3 and keeps its general
guards. Earlier policies and archived batches keep their original behavior.
It validates the direct talent family, class and exact effective teaching
effects before adding Berserk's wrapper `51266` for talent `50334`, or Blast
Wave's wrapper `1831` for talent `11113`, to the related group. Both are
single-rank direct talents. The wrapper, its other learned children and every
related trained rank must be absent or disabled; enabled teachers or children,
unknown incoming routes, altered effects, scripts, skills and cycles still
defer the group. Present disabled wrappers may be explicitly archived/removed.

The stock local DBC catalog lacks `50321`, another LEARN target of `51266`.
Pinned TC `SpellMgr::IsSpellValid` rejects the entire teacher when any LEARN
target is missing. V4 can disregard only this exact invalid incoming route when
effective metadata still lacks `50321` and neither `51266` nor `50321` is stored
for the character. It reports `ABSENT_INVALID_TEACHER`,
`ABSENT_METADATA_NO_GRANT` and `rejected_missing_target_teachers`; it deletes no
teacher row and grants nothing. Stored invalid teachers defer to a separate
review. A custom world definition of `50321` disables this shortcut and requires
the complete teacher/child group check. Other missing targets are not ignored.

The shaman exception removes **only** disabled/unselected talent `30798`, whose
single direct rank has the exact learn effect for shared Dual Wield `674`.
It requires shaman class ownership metadata, no selected rank in either spec,
no incoming route/default/skill reward for the root, no additional root rank
or outgoing child, and compatible script/correction contracts. Pinned TC's
disabled load path has no other direct talent rank to remove and returns
before the learn effect. Therefore this inert root row can be discarded without
changing the shared child or skill: **spell `674` is preserved in every stored
state, and skill `118`, its value and cap receive no writes.** An absent `674`
is never granted. Other classes and selected shaman builds do not qualify.

`relationship-review.tsv` labels retained `674` rows
`PRESERVED_SHARED_SKILL_ROUTE`; the manifest reports
`preserved_shared_route_rows` and `reviewed_teacher_pairs`. Other direct/related
counts, full original archives and exact restoration are unchanged. The exception
does not authorize Dual Wield in an unowned spec, repair a corrupt skill, or
promise migration acceptance for the preserved shared state. Remaining enabled
availability and skill ownership require separate migration review. All source
spells and skills remain fingerprinted, including preserved rows, so same-count
drift blocks apply/restore as before. Gameplay and release approval remain
unaccepted until their existing gates pass.

For disabled ranks whose family **does have a selected rank**, use a separate
mode and the exact `REVIEW_DISABLED_OTHER_SELECTED_RANK` inspection count:

```bash
python3 console plan disabled-talent-history \
  --audit FULL_AUDIT_ID --expect-review-rows 100 \
  --selected-rank-history
```

Policy `tc-disabled-other-selected-talent-rank-v5` removes only disabled direct
ranks selected by neither talent group. Existing `character_talent` selections
are the authority: a stale rank can be below or above the selected rank. It never
chooses a highest rank, merges the two builds, changes selected ownership or
enables a spell. This mode cannot be combined with the v2/v3/v4 flags; earlier
policies and batches retain their original behavior.

Pinned TC `AddSpell` removes other direct ranks in a talent family before its
new-disabled return. A stale disabled row can therefore interfere with a selected
rank during loading. V5 is an explicit repair against retained talent ownership;
it does not promise identical behavior to the old conflicting spellbook state.
`AddTalent` tracks choices separately in each specialization. Selected spell rows,
their original flags, talent points and both talent groups receive no writes.

Review `selected-rank-review.tsv` for each deleted rank, the selected
`[spell,group,rank]` choices and their stored `[spell,active,disabled]` flags.
A missing selected spell row is recorded with null flags; apply does not grant
it. Native talent loading and specialization switching still require gameplay
acceptance. Full affected character, spell, talent and skill originals are
archived and guarded exactly as in the earlier policies.

V5 defers mixed ordinary/talent chains, independent learning/default/skill routes,
teaching or prerequisite dependants, profession/riding/skill effects, unknown
scripts or corrections, invalid ownership, online characters and pending resets.
An enabled unselected sibling defers the whole candidate family; enabled selected
ranks remain untouched. All enabled-history findings require separate review.
`excluded-rows.tsv` records precise deferral reasons, so the selected count may be
smaller than the reviewed population. This policy is separate from the migrator's
legitimate missing-lower-rank reconstruction and changes no migration blocker rule.

For disabled **trained** talent ranks left after their direct talent roots were
removed, use a retained migration context inspection rather than the direct-rank
audit. This is a separate policy, `tc-disabled-unselected-trained-talent-history-v6`:

```bash
python3 console plan disabled-talent-history \
  --migration-inspection MIGRATION_CONTEXT_INSPECTION_ID \
  --expect-review-rows 1000
```

Use the exact number of disabled non-direct stored spells whose verified TC rank
chain starts at a direct talent, across all characters captured in that inspection.
This is not the number of first failures or the direct-talent audit count. The
command reports count mismatches without source writes. `--migration-inspection`
selects v6 unless the explicit v7 option below is present, and cannot be combined
with direct-history policy flags or other evidence options.
No new full audit or migration preflight is required when captured inputs match.

V6 reviews the whole verified talent/rank/dependency group, even when every
direct talent root is absent from `character_spell`. All present group rows must
be disabled and no related talent may be selected in either specialization.
Online characters, pending resets, invalid talent ownership, foreign-class
families, enabled related spells and independent learning/default/skill routes
defer the whole group. The same bounded graph, reviewed script, correction,
cycle and profession/riding/skill guards used by v3/v4 apply. The exact reviewed
teacher contracts from v4 retain their existing conditions. It does not expand
unverified indirect dependencies whose rank root is not a direct talent.

Review `relationship-review.tsv` and `relationship-edges.tsv`, all selected keys
and every exclusion. Absent roots/predecessors are `ABSENT_NO_GRANT`. Existing
disabled direct roots or dependent rows may also be selected if the whole group
qualifies; the manifest separates direct and related counts. Selected ownership,
enabled availability, skills/caps, points and login flags receive no writes.

The sealed context must match the current source UUID/schema, producer, profile,
DBC assets, effective TC world inputs and source column layouts. Planning rechecks
**all** captured spell flags, talent groups, skill values/caps and character
semantic fields, including deferred characters, before emitting a candidate.
It then archives/fingerprints complete affected rows, including custom fields,
through the existing prepare/apply/restore transaction. The context is evidence;
it is never used as a restoration archive. Same-count changes reject stale
planning, and post-prepare full-row or metadata changes block apply/restore.
Earlier policies and archived batches retain their original behavior.

This policy removes reviewed unavailable history. It does not resolve valid
temporary talent-chain representation differences, grant missing skills/forms,
delete enabled unowned abilities, or complete a pending native reset. Keep those
migration blockers separate. Release approval remains `UNREVIEWED`.

Archiving these rows also discards their stored future-reactivation history.
TC can re-enable disabled higher ranks when a talent is learned again. After
cleanup, future talent changes use native learning/retraining behavior, which may
require learning those ranks again. Current selected builds are protected, but
this policy does not promise to preserve every past training purchase. Exact
archive restoration is guarded and must precede later affected-state/gameplay
changes. Include this consequence in candidate review before apply.

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
reviewed `(guid,spell)` pairs. Talents, enabled spells,
spec counts, skill values/caps, profession slots, login flags, items and quests
receive no writes. All work in each prepare/apply/restore phase is transactional;
incomplete phases roll back, while successful reruns verify committed state.
V1/v2/v5 preserve all ordinary rank rows; v3/v4 can remove only the exact disabled
ordinary ranks/dependants listed in their isolated related group selection.

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

## Review orphaned disabled talent children

Some stored spells are children learned by talent effects or requirements, while
their own rank chain does not start at a direct talent. V6 does not select those
rows. Use the explicit `tc-disabled-unselected-talent-child-history-v7` policy
only after reviewing their effective TC relationships. It does not change any
migrator rejection rule or infer talent ownership.

Capture current source state from a saved blocker report; another preflight or
full audit is unnecessary for this step. Set `BLOCKER_REPORT` to that report:

```bash
python3 console inspect-migration-blockers --report "$BLOCKER_REPORT"
python3 console plan disabled-talent-history \
  --migration-inspection latest --orphaned-talent-children --preview
```

`latest` selects the newest migration-blocker inspection in the current session
and prints its exact ID. Explicit IDs remain supported. An incomplete newest
capture fails; the tool does not silently fall back to older evidence.

Preview writes `talent-child-review.json` in its operation directory, with
`reviewed_candidate_rows`, `selected_rows`, `selected_characters`, exact selected
keys and deferred reasons. It creates no SQL package, archive or active-batch
pointer and performs no source writes. It reviews the captured state against
current effective metadata; it is not full live-row verification or cleanup
approval. If the source changed, capture another inspection before planning.

After reviewing the preview, replace `COUNT` with **reviewed_candidate_rows**:

```bash
python3 console plan disabled-talent-history \
  --migration-inspection latest --orphaned-talent-children \
  --expect-review-rows COUNT
```

Use the preview's printed inspection ID instead of `latest` if another capture
was made in between. The count is the disabled child-candidate population,
including exclusions. It is not selected rows, affected characters or the
first-failure count from preflight. Counts depend on the captured scope; never
reuse a number from a different report or database import.

V7 derives candidate families only from the effective TC rank/learn/requirement
catalog, including absent direct roots and verified child-rank siblings. It then
applies the same whole-family guards as v6. Every present family row must be
disabled; no family talent may be selected in either spec. Ambiguous/shared
derivations, independent/default/skill routes, profession/riding/skill effects,
unsupported scripts/corrections, malformed chains/cycles, online characters,
pending resets, invalid ownership and foreign classes defer or block.
Traversal is iterative, bounded and deterministic; no evidence is truncated.
V4's exact reviewed teaching contracts retain their original conditions.

Only present, exact `(guid,spell,active,disabled)` rows in qualifying families
are selected. The full closure can include disabled direct or trained siblings;
absent nodes are `ABSENT_NO_GRANT`. No enabled spell, selected talent, point,
spec, skill value/cap, profession slot or login flag is changed. Deleting this
unavailable history discards its stored future reactivation/training state, as
described above; it does not prove those records were corrupt.

Planning rechecks the entire sealed semantic scope, including deferred
characters, against live data, then fingerprints full affected originals and
effective metadata. Review the candidate README, manifest, selected/excluded
rows and relationship reports before using its exact batch ID with
`prepare`, `status`, `apply` and `restore`. The existing archive transaction,
atomic checkpoint, drift rejection, reruns and guarded exact inverse apply.
Native gameplay is separate; release approval remains UNREVIEWED.

Retain earlier toolkits/archives for their original guarded restore. After a
fresh source import, initialize a new session, capture new evidence and regenerate
needed plans; do not replay an old APPLIED package. After an actual preparation
apply, use new evidence and fresh migration target/control schemas and run ID.

## Review isolated disabled ordinary spells

`plan disabled-spell-history` is a separate opt-in preparation policy,
`tc-isolated-disabled-ordinary-spell-history-v1`. The migrator continues to block
unrepresentable disabled state. This policy retires reviewed unavailable
ordinary history; it never enables a spell or treats every disabled row as corrupt.
Deleting it discards stored future reactivation/retraining history. Retain the
archive and original toolkit for exact restoration before gameplay/further edits.

Use the current session's fresh migration-blocker inspection:

```bash
python3 console plan disabled-spell-history \
  --migration-inspection latest --preview
```

The private `ordinary-spell-review.json` reports the actual
`reviewed_candidate_rows`, `selected_rows`, `selected_characters`, exact keys and
deferred reasons. Preview creates no executable package, archive, active-batch
change or source writes. Its captured-state review is not a live restoration
snapshot or approval. After reviewing it, use **reviewed_candidate_rows** as
`COUNT`, including deferred candidates:

```bash
python3 console plan disabled-spell-history \
  --migration-inspection INSPECTION_ID --expect-review-rows COUNT
```

Use the exact inspection ID printed by preview. Counts depend on this source
and scope; do not reuse them after an import or source edit. Planning rechecks
the complete captured semantic scope, including deferred characters, and then
fingerprints full affected character/spell/talent/skill originals.

Every present row in an eligible verified rank family must be disabled. Both
`active=0,disabled=1` and `active=1,disabled=1` remain unavailable in TC;
`active=0,disabled=0` is still known and prevents removal of that family.
Absent ranks are `ABSENT_NO_GRANT`; no predecessor is inserted or activated.
Talent ancestry is excluded across all classes and both specs, even when a
talent family fails its own cleanup contract. Aura helpers and additional
talent spells stay excluded. Any incoming/outgoing learning or prerequisite
edge, including an internal cycle, defers an ordinary family.

Default spells, skill rewards, profession/riding/Runeforging associations,
learning/skill effects, unsupported scripts/corrections, malformed chains,
invalid flags/ownership, ineligible race/class, online characters and pending
native resets defer or block. The graph is bounded and deterministic, using
effective TC world/DBC metadata only. Target trainers never supply grants.
No enabled spell, talent selection, point, spec, skill value/cap, profession
slot or login flag is changed. Selected builds may coexist with unrelated
ordinary cleanup; a talent-linked family cannot qualify.

Review README, manifest, selected/excluded rows and `relationship-review.tsv`
(`ordinary_first_spell` identifies the rank family), then use the exact new batch
ID with `prepare`, `status`, `apply` and `restore`. The existing full-row archive,
atomic deletion/checkpoint, live/SQL metadata guards, reruns and exact inverse
apply. Prior talent policies retain their original behavior. Current code is
fingerprinted in the package; preserve earlier toolkits for earlier archives.

After a fresh import, initialize a new cleanup session, capture current inputs
and regenerate plans. After applying preparation edits, use a fresh migration
run and target/control schemas. Native gameplay and release acceptance remain
separate; approval remains **UNREVIEWED**.

### Inactive custom starting-spell routes (ordinary v2)

Use this separate opt-in policy only after verifying that the **effective TC
worldserver configuration** has `PlayerStart.AllSpells = 0`. Record that fact in
the existing private cleanup config:

```ini
[source]
player_start_all_spells = 0
```

Edit the existing `[source]` section; do not duplicate it. Blank means unknown;
only literal `0` or `1` is accepted. This is an operator assertion, not automatic
detection of a server configuration. Do not upload a whole worldserver config
containing credentials. This setting does not change the session endpoint, so
the existing preparation session can continue.

Pinned TC `Player::LearnCustomSpells()` returns immediately when
`CONFIG_START_ALL_SPELLS` is false. `World::LoadConfigSettings()` reads that flag
from `PlayerStart.AllSpells`. Thus `playercreateinfo_spell_custom` does not supply
a login learning route under this assertion. `LearnDefaultSkills()` and other
reward/learning routes are separate and retain their guards.

```bash
python3 console plan disabled-spell-history \
  --migration-inspection latest --inactive-custom-defaults --preview
```

Review the new `ordinary-spell-review.json`. The distinct policy is
`tc-disabled-ordinary-inactive-custom-defaults-v2`. Its `configuration_contract`
records the exact setting, value and `OPERATOR_ASSERTION` evidence.
`selected_custom_default_rows` counts selected stored rows in families with an
inactive custom-start route. `relationship-review.tsv` labels their proof rows
`ORDINARY_RANK_INACTIVE_CUSTOM_DEFAULT`, including absent ranks receiving no
grant. Skill rewards, professions/riding/Runeforging, talents, every dependency
direction, enabled family rows, scripts, invalid states and pending resets
retain the v1 guards. Staff characters receive the same reviewed policies as
other characters; there is no automatic GM exclusion or migration exemption.

Generate a candidate with **reviewed_candidate_rows**, including exclusions:

```bash
python3 console plan disabled-spell-history \
  --migration-inspection INSPECTION_ID --inactive-custom-defaults \
  --expect-review-rows COUNT
```

Review, prepare, apply and restore with the exact printed batch ID as above.
The assertion is hashed into the batch and rechecked before every console
prepare/apply/restore. Unknown/enabled settings fail with
`ORDINARY_HISTORY_CONFIG_REQUIRED`; a differing recorded contract fails with
`ORDINARY_HISTORY_CONFIG_DRIFT`. No source action is attempted after either
error. Old v1 behavior is unchanged, even when this config value is zero.

Direct SQL calls require both fresh-session assertions before **each** action:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @ordinary_history_all_spells=0;
CALL `ARCHIVE_SCHEMA`.apply_batch();
```

Replace `ARCHIVE_SCHEMA` with the exact owned archive. Use `prepare_batch()` or
`restore_batch()` for those actions. Missing/nonzero assertions reject, and
live world fingerprints also protect the custom-start table against same-count
changes. SQL cannot prove what a separate worldserver configuration contains;
the operator must retain and honor the asserted configuration. Exact restore
requires that same assertion and unchanged archived state. Restore in reverse
application order before gameplay or other edits, or restore the baseline dump.

The v2 semantic manifest additionally protects TC `World.cpp` (100 TC / 103 AC
files) at the retained pins; v1 and release approval are unchanged. Earlier
migration runs need fresh target/control schemas because profile hashes changed.
This preparation extension adds no migration grants or validation exceptions.

### Native Death Coil rank-1 repair (ordinary v3)

`tc-native-death-coil-base-repair-v3` is a separate explicit preparation policy.
It allows **rank 1 Death Coil (47541)** to become native skill-derived known
state after removing reviewed disabled higher-rank history. This availability
change is intentional. Ordinary v1/v2 continue to defer the skill-reward route.
The policy covers only the exact chain
`47541 -> 49892 -> 49893 -> 49894 -> 49895`, on death knights with existing
Unholy skill `772`. The base must be absent from storage. Every present higher
rank must have exactly `active=1,disabled=1`; inactive or enabled siblings defer.
Multiple eligible higher rows are archived/removed together deterministically.

TC loads skills and their automatic rewards before stored spells. Skill 772
initially supplies base 47541. A stored disabled higher rank recursively disables
its predecessors, including that base. Removing the reviewed suppressing rows
lets the existing skill supply rank 1 on native load. SQL **inserts no spell**,
updates no spell flags and grants no higher trained ranks. AC's reviewed native
skill consumer also supplies only the base under the compatible metadata.
Target-world overlays and full gameplay remain separate migration checks.

The exact source skill/ability/race/class metadata, non-passive dummy effects,
reviewed non-mutating script, chain, base absence and existing positive skill
row must match the contract. The skill value must not exceed its cap, and the
cap must not exceed the native level-80 bound of 400. Unknown, duplicate,
zero-value or missing Unholy skills defer; no skill is added or guessed.
Talent ancestry, any learning/prerequisite edge, aura helpers, selected ownership
conflicts, unsupported metadata, foreign classes, online state and pending
resets retain their guards. Other ordinary families stay outside this policy.

The existing private config must assert `[source] player_start_all_spells = 0`.
This keeps the separate custom-start route from regranting higher ranks.
Unknown/enabled settings fail with `DEATH_COIL_CONFIG_REQUIRED`. The new flag
cannot be combined with `--inactive-custom-defaults`:

```bash
python3 console plan disabled-spell-history \
  --migration-inspection latest --native-death-coil --preview
```

Read `ordinary-spell-review.json`: `reviewed_candidate_rows` includes every
ordinary candidate and exclusion; `selected_rows` counts exact stored rows to
remove, while `native_base_characters` counts characters whose independent base
route is permitted. `spell_rows_inserted` and `skill_rows_changed` are zero.
`native_base_proofs` records the skill value/cap, level, both-spec base mask,
existing normalization and base absence. `relationship-review.tsv` uses
`NATIVE_DEATH_COIL_BASE_ROUTE` and distinguishes
`NATIVE_BASE_FROM_EXISTING_SKILL` from absent higher ranks marked
`ABSENT_NO_GRANT`.

After reviewing the preview, use its total **reviewed_candidate_rows**:

```bash
python3 console plan disabled-spell-history \
  --migration-inspection INSPECTION_ID --native-death-coil \
  --expect-review-rows COUNT
```

Review the generated `native-base-review.json`, exact selected/excluded rows,
manifest and full prepared originals. Use the new printed batch ID with
`prepare`, `status`, `apply` and `status`. `APPLIED` means the exact higher rows
were archived/removed; rank 1 is native state on load, not an inserted stored
row or gameplay acceptance. Skills/values/caps, professions/slots, talents,
specs, enabled unrelated spells, character state and login flags stay unchanged
by SQL. No automatic staff exemption or migration-validation bypass is added.

Both native skill loaders already normalize Unholy skill to `level * 5` through
their existing load-range and level-update paths. This happens before and after
the repair. The policy preserves the **stored** skill rows exactly and reports
`existing_native_skill_normalizations` so that legacy values are visible; it
does not silently turn this spell repair into a skill normalization batch.
Compare native skill behavior with the source baseline during gameplay checks.

The existing atomic archive/delete/checkpoint and exact inverse are reused.
Source/world content drift, same-count changes, interruption, reruns and restore
guards still apply. Console actions require the same configuration contract;
`DEATH_COIL_CONFIG_DRIFT` rejects a differing recorded contract. Direct SQL calls
add a separate availability acknowledgement before each action:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @ordinary_history_all_spells=0;
SET @ordinary_history_native_base=47541;
CALL `ARCHIVE_SCHEMA`.apply_batch();
```

Use the exact owned archive, with `prepare_batch()` or `restore_batch()` for
those actions. Missing/wrong acknowledgements reject. These session values are
operator assertions, not configuration detection. Restore before native login
or later source edits, in reverse application order. A login may persist native
skill/state changes and invalidate exact-restore guards; retain the untouched
baseline for rollback rather than bypassing them.

For a fresh import, initialize a new session and repeat the reviewed policies
against fresh captures/counts. After source edits use a fresh migration run and
target/control schemas. Pins, 100 TC / 103 AC protected files, metadata profile,
control schema and migration spell-state-v12 stay unchanged. All five gameplay
gates remain **NOT TESTED** until executed; approval stays **UNREVIEWED**.

## Reconcile conflicting talent spell ownership

The separate `talent-ownership` policy retires verified conflicting **enabled**
and disabled spell rows while preserving both selected builds. Old history
policies retain their original restrictions.

```bash
python3 console plan talent-ownership --migration-inspection latest --preview
```

Use **selected_rows** as `--expect-rows`. Missing active anchors, pending resets,
inconsistent owned-child flags and unsafe skill/learning routes defer. SQL
inserts no spells and changes no flags, talents or skills; supported native
children restore from correct existing selected anchors. Follow the
[ownership repair guide](talent-ownership-repair.md) for review, prepare/apply,
SQL acknowledgement, full originals, exact restore and fresh-import repetition.

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

For the complete preparation-to-cutover sequence, see
[Repeat the complete preparation and migration](source-preparation.md#repeat-the-complete-preparation-and-migration).
Reuse reviewed policies against fresh findings; old counts and character-specific
approvals are not a recipe. A combined automatic cleanup/migration orchestrator
is not implemented yet. The current manual operations below are its building
blocks and do not establish fresh-snapshot end-to-end acceptance.

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

## Repair native skill rows

Use `python3 console plan native-skills --preview` to inspect absent Generic
and Runeforging skills justified by already known enabled native anchors. It
uses the latest migration-blocker context in this session, prints its ID and
creates no SQL package or active-batch change. After reviewing the preview,
use `plan native-skills --expect-rows COUNT` to create the exact candidate.
See [missing native skill preparation repair](native-skill-repair.md) for
eligibility, explicit INSERT/DELETE grants, full archives, guarded restoration,
fresh-import repetition and native gameplay acceptance. The earlier
`plan skills` policy still only clamps over-cap values to their stored caps.

The explicit Generic-only v2 option also reviews `63680` load-derived anchors
and existing non-native Generic values/caps:

```bash
python3 console plan native-skills --skills generic --normalize-generic --preview
```

Capture fresh migration-blocker context after earlier preparation changes. Use
the preview's total `selected_rows` with the same options and `--expect-rows`;
review insertion/update counts and exact old/new values before prepare/apply.
The [native skill guide](native-skill-repair.md#v2-reviewed-generic-normalization)
covers extra column grants, exact inverse restoration and fresh-import repetition.

## Reviewed pet-teaching retirement

Use `python3 console plan pet-teaching --migration-inspection latest --preview`
for the separately authorized old player-side pet-teaching policy. It preserves
actual pets/pet spells, both talent selections and all skills. Use the preview's
`selected_rows` with `--expect-rows`, then explicit batch IDs for prepare, status,
apply and exact restore. Scripted, profession, player-teaching and ambiguous
cases defer. See the [complete repeatable procedure](pet-teaching-repair.md).
Reuse the existing read-only target metadata and verified custom-start-off
configuration; no new source session is needed for an unchanged baseline.

The optional pet-teaching `--reviewed-cower` mode is a separate v2 contract for
only the exact reviewed Cower pet-child amount callbacks. Default v1 scripted
exclusions are unchanged. See the [native contract, direct-SQL acknowledgement
and repeatable batch procedure](pet-teaching-repair.md#opt-in-reviewed-cower-child-v2).

## Reviewed training prerequisites (ordinary v4)

`tc-disabled-ordinary-training-prerequisites-v4` extends ordinary retirement only
for Divine Spirit (`14752`), Prayer of Spirit (`27681`) and Nature's Grasp
(`16689`). Complete stock chain order and touching edges must match. Their
`spell_required` links gate training, rather than grant learned spells. Native
TC loading does not activate a disabled spell merely because its ordinary
prerequisite is known. AC's ordinary mask and both trainers likewise separate
existing ordinary knowledge from training requirements.

This deliberately discards future reactivation/retraining history. Every stored
rank in a selected family must be disabled; enabled siblings defer it. Enabled
counterpart spells, such as Entangling Roots, remain unchanged. No base/higher
rank is granted. Both talent builds, skills/caps, professions, glyphs, items and
login flags stay unchanged. Talent/aura or learn routes, skills/rewards, scripts,
extra/cyclic/changed edges, unsupported classes and pending resets defer.
Historical ordinary v1/v2/v3 policies retain their behavior; no GM exemption is
introduced.

Use the complete toolkit with a current sealed migration inspection. After
source edits, capture fresh context from an existing report using
`inspect-migration-blockers --report /path/to/spell-state-blockers.tsv --bundle`.
Continue the existing unchanged preparation session. Verify the stopped TC
configuration and set the existing `[source] player_start_all_spells = 0`.
Do not duplicate keys. This is an operator assertion, not a configuration change.

The exact reviewed training families may also occur in
`playercreateinfo_spell_custom`. With this required `PlayerStart.AllSpells=0`
assertion, their custom-start routes are inactive and do not prevent selection.
This allowance applies only to families satisfying the full training contract;
unrelated custom-start families still defer. Missing custom-start catalog
metadata fails with `ORDINARY_HISTORY_DEFAULTS_REQUIRED`, rather than being
treated as an empty catalog. Review `selected_custom_default_rows` in the
summary and `inactive_custom_default_spells` in each training proof. The catalog
is fingerprinted even when its routes are inactive; content drift blocks apply.

```bash
python3 console plan disabled-spell-history --migration-inspection latest --training-prerequisites --preview
python3 console plan disabled-spell-history --migration-inspection INSPECTION_ID --training-prerequisites --expect-review-rows REVIEWED_CANDIDATE_ROWS
python3 console prepare --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Here `--expect-review-rows` is **reviewed_candidate_rows**, including deferred
rows, rather than selected_rows. Preview creates no SQL package or active batch.
Review `ordinary-spell-review.json`, `ordinary-training-proof.json`, manifest,
relationship review and full archived originals. PREPARED leaves selected rows
stored. After reviewing the exact batch:

```bash
python3 console apply --batch BATCH_ID
python3 console status --batch BATCH_ID
```

Planning rechecks the complete captured semantic scope, including deferred
characters. V4 seals full custom source rows with exact FLOAT/DOUBLE and DECIMAL
fingerprints, TC world content/layout, DBC assets, configuration, selector/guard
hashes, proofs and expected result. Apply/checkpoint commits atomically; late
errors and interrupted transactions roll back. Reruns verify committed state.
No new source/world grants are added. The console supplies acknowledgements;
before each direct SQL action also set:

```sql
SET @talent_cleanup_ack='STOPPED_PREPARATION_COPY_ONLY';
SET @ordinary_history_all_spells=0;
SET @ordinary_training_ack='REVIEWED_TRAINING_PREREQUISITES_ONLY';
```

Before gameplay or further edits, `python3 console restore --batch BATCH_ID`
restores exact full removed rows and rejects affected-state/metadata drift.
Restore overlapping later batches first with their original toolkits. Earlier
archives retain their original guards and numeric limitations. After a fresh
baseline import, retain prior evidence, start a **new session**, capture fresh
inputs and regenerate plans. Never reuse old approvals or SQL. Source preparation
requires a fresh migration run and target/control schemas. This source-only
policy does not approve AC compatibility; normal target world/DBC preflight is
still required.

Static controls keep old policies rejecting these cases. MySQL 8.4 tests exercise
real console preview/count/full-scope drift, source/world layout and fractional
changes, extra acknowledgements, late/disconnect rollback, reruns and exact
custom-row restoration. Protected TC load/disabled/dependent consumers and both
trainers/AC ordinary-mask consumers run with mocked state, separately from full
worldserver gameplay. Record all five staging gates individually: ranks/trainers;
casting; both specs/relog; talent/profession/recipe/riding/skill state; and
save/relog/restart/logs. Gameplay remains **NOT TESTED** and approval **UNREVIEWED**
until accepted. Core pins, global manifests, metadata and migration reconstruction
are unchanged.
