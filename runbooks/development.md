# Development and automated tests

Operator migrations use the [migration guide](migration-guide.md). These checks
are for toolkit development and synthetic fixtures; they do not replace a
production-sized rehearsal or native gameplay acceptance.

## CI coverage

The `CI` workflow runs `tests/static-checks.sh` on every push and pull request.
It includes the spell semantic regressions and does not start MySQL.

The full database suite runs separately through the `MySQL rehearsal` workflow
(`.github/workflows/rehearsal.yml`). In GitHub Actions, select that workflow,
choose **Run workflow**, and select the branch to validate. GitHub requires
the workflow file on the default branch before manual dispatch is available.
It runs static checks first, then the complete disposable MySQL 8.4 rehearsal,
with a 60-minute job limit. Rehearsals can take more than 15 minutes because
they repeat migrations, interrupt real transactions and verify resume/rerun
behavior. They no longer delay routine push/PR checks.

A passing routine CI run does not establish database integration coverage.
Before merging migration logic, mapping, compatibility-profile or database-test
changes, run the full rehearsal on the final branch revision, either through
that workflow or locally using the instructions below, and record the result.
Documentation-only and other changes without migration behavior do not require
the full database suite.

Private snapshot redaction has a focused MySQL test,
`tests/character-share-mysql-tests.py`, also included in the full rehearsal.
It verifies the standalone SQL procedure against every stock table/column,
unknown metadata and executable objects, late-error rollback, row and gameplay
state preservation, idempotency and an actual dump/restore. See the
[snapshot sharing guide](sharing-character-snapshot.md) for its dedicated-server
command. It does not change migration mappings or loader behavior.

## Static checks

Install ShellCheck, Python 3 and the tools listed in the migration guide, and make both
reviewed local core checkouts available. From the toolkit checkout:

```bash
TRINITYCORE_DIR=/srv/src/TrinityCore \
AZEROTHCORE_DIR=/srv/src/azerothcore-wotlk \
tests/static-checks.sh
```

The default paths are sibling `../TrinityCore` and `../azerothcore-wotlk`.
`COMPATIBILITY_PROFILE` defaults to `tc335-acwotlk-v2`. The suite checks shell
scripts, registry inventories, profile reproducibility/drift, retired and
unreviewed rejection, complete schema dumps, and the disposable-port guard.
It also runs synthetic WDBC semantic regressions for spell-rank reconstruction.
It runs source-health audit unit tests for exhaustive talent findings, legitimate
omitted ranks, disabled talent history, custom spell IDs, skill/spec conflicts,
missing schema coverage and read-only connection guards.
It also runs offline talent-cleanup planner regressions for sealed evidence,
matching DBCs, exact invalid keys, protected selectable ranks, deterministic
packages, private reports and unsupported schema/producer rejection.
The cleanup console's fast tests cover literal/private configuration, credential
files without inline passwords, redacted error journals, package integrity,
workspace locks and identifier/path boundaries.
Socket regressions check every role's transport arguments, unchanged TCP
settings, rejection of remote-host/socket combinations, and a real MySQL client
against a nonexistent test socket. The last check requires no server and
distinguishes a socket connection attempt (error 2002) from protocol error 2047;
it is skipped if the client is unavailable.
Offline skill-policy tests verify sealed full-audit evidence, source/producer
identity, matching DBCs, exact expected counts, duplicate keys, unknown skills,
zero/equal caps, numeric types, report tampering, live drift and offline state.
These include rank-derived prerequisites (Dire Bear Form/Bear Form/Challenging
Roar), native script aliases and paired mutation guards, reviewed encounter
handlers, and spell/aura enum and effect-copy corrections. Script inventory
regressions cover bindings hidden by earlier ownership/correction failures,
multiple bindings per spell, deterministic output, dual-spec counting, orphan
exclusion and incomplete query reports. The encounter callback harness also
executes the protected Shadowy Construct load/apply bodies with mocked sinks.
The spell regressions also cover reviewed legacy constructor aliases, bounded
family-flag corrections, authorized AC-only temporary rank prefixes and rejection
of unreviewed TC temporary predecessor obligations.
Inventories use `LC_ALL=C`. Candidate approval exists only in disposable
toolkit copies under `/tmp`; the checkout's approval is unchanged.

Flight Form regressions require the explicit TC world edge, an ordinary druid
anchor (including a reconstructed Flight Form below Swift Flight Form), exact
riding effects and matching rank prefixes. They verify `225/225` and existing
`300/300` with a known higher anchor, no inferred higher rank, both active specs,
overlapping derivations, reverse round trips and unchanged skills. Missing or
insufficient skills, changed metadata, disabled ordinary spells and unsupported
world relationships remain blocked. The disposable fixture rehearsal loads these
rows transactionally through interruption/resume/rerun and both migration
directions, checks committed provenance and preserves source/world checksums.
`riding-dependency-tests.py` separately compiles the protected TC dependency body
and both native skill-update bodies with mocked getters/sinks, including a
negative control that would raise an insufficient skill. This is consumer
behavior verification, not a worldserver gameplay test.

Native passive-rank units exercise the seven explicitly reviewed chains across
four talent families, both active specs and different ranks in each spec. They
check exact-child masks, stored predecessor flag/provenance normalization,
reverse active-child/native-prefix round trips, unowned higher-rank rejection,
skill/learn/stance/value/teacher/trainer mutations and unsupported contracts.
The compiled `native-passive-rank-tests.py` executes protected AC add/remove/save
bodies and the TC/AC same-caster passive exclusion branches. It checks canonical
exact aura identities, gated casts, temporary save omission, mocked spec/relog
scheduling, persistent-predecessor leakage as a negative control and the actual
Will of the Necropolis rank/threshold callbacks. Getters, aura application,
transaction sinks and scheduling are mocked; full gameplay remains NOT TESTED.
MySQL fixtures check both directions, unchanged talents/skills, committed native
provenance, leaked persistent rows, broadened owner masks, report regeneration,
trainer conflicts and same-count trainer metadata drift. The ordinary trainer
rank regression and all previous cleanup suites remain required.

The active-build pending-reset tests exercise the real console on MySQL 8.4:
read-only planning/prepare, custom binary/timestamp snapshots, narrow source
grants, rollback/interruption, drift rejection, exact restoration and preservation
of ownership, skills/caps, glyphs/actions, items/mail, other characters and worlds.
This policy queues native login reset; SQL tests do not establish gameplay reset.

Direct spell-history inspection tests cover selected different talent ranks in
either spec, enabled/disabled and foreign-class states, pending resets, invalid
ownership, ambiguous metadata, sealed evidence, exact keys/flags and same-count
replacement drift. The console MySQL rehearsal runs inspection with SELECT-only
credentials, checks deterministic repeated output, unchanged source/auth/world
checksums and preservation of the active cleanup batch selection. These reports
do not establish a safe deletion policy or indirect-spell compatibility.

Disabled-history policy tests separately verify exact direct-rank selection,
family-wide enabled/learned/skill/custom-default/script/dependency exclusions,
unchanged selected builds, pending resets, and the protected TC new-disabled
load path and known-spell predicate. The MySQL suite executes the real console
with restricted reader/writer roles, custom binary/timestamp fields, same-count
state and metadata drift, late-error and connection-interruption rollback,
commit/rerun, exact restore and archive retention. To add a bulk scale case on
the dedicated disposable endpoint, run:

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 REHEARSAL_MYSQL_PORT=33317 HISTORY_SCALE_ROWS=151806 \
  python3 tests/disabled-history-mysql-tests.py
```

The scale case adds that many synthetic direct history rows across thousands
of characters, then plans, prepares, applies, reruns and restores them exactly.
It is opt-in; regular push/PR CI continues to run only static checks. A passing
SQL rehearsal does not establish native login, relearning or gameplay acceptance.

The explicit reviewed-script v2 mode has a separate SQL cycle in the same suite:
v1 still defers scripted families, v2 records the accepted protected binding,
same-count script changes block both console and direct SQL calls, late errors
roll back deletion/checkpoint together, and apply/rerun/restore preserve all
other source/auth/world checksums. Units also reject unreviewed sibling bindings,
special runtime-aura contracts, failed script contracts and skill/dependency/
independent-route conflicts despite an otherwise accepted script.

V3 relationship units cover rank-component expansion, deterministic merged
learning/prerequisite edges, cycles, shared owners, incoming routes, every spec,
enabled and inactive-but-enabled children, missing-rank no-grant provenance,
skill/profession/riding guards, script/correction failures, malformed metadata
and traversal bounds. Its MySQL cycle uses Fiery Payback roots/hidden children
and Holy Shock direct/trained ranks. It tests exact root/related counts, child
and same-count world drift (console and direct SQL), late-error and disconnect
rollback, reruns, full custom-field restoration, and unchanged enabled spells,
talents, skills, auth/world and unrelated character tables. V1/v2 still run in
the same suite. These tests remain separate from native gameplay acceptance.

V4 units verify exact Berserk/Blast Wave wrapper effects and class/family
identity, preservation of enabled teachers, outside routes, selected shamans,
other classes and every shared `674` flag combination. SQL tests use actual
talent/wrapper IDs, preserve enabled and disabled `674` custom fields plus
skill `118` values/caps, reject same-count preserved-state drift, and exercise
late rollback, reruns and complete restoration. The one-command `--audit`
planning flow creates a new sealed inspection and is exercised by this cycle.
An additional SQL cycle exercises the stock missing-50321 path, preserving a
stored invalid teacher while cleaning only the root with an absent teacher.
`tests/talent-route-runtime-tests.py` compiles the protected TC `IsSpellValid`
function with mocked catalog/item getters: a missing LEARN child rejects the
whole teacher, while custom valid-child and Blast Wave controls pass. This is
behavioral source verification, not a running worldserver or gameplay test.

V5 selected-rank history units cover stale ranks above/below selections, different
choices in both specs, unchanged counterpart flags, absent counterparts with no
grant, enabled unselected siblings, invalid ownership, pending resets and route,
script, correction and skill guards. Its MySQL cycle uses restricted roles and
custom fields to exercise read-only planning, conflicting mode flags, exact
selection/proof, selected ownership/flag drift, metadata drift, late-error
rollback, apply/rerun, retained enabled conflicts and exact restore. All other
source/auth/world tables must remain unchanged. The earlier policy cycles still
run in the same suite.

`tests/selected-rank-runtime-tests.py` extracts the pinned TC `AddTalent` function
and the sibling-removal branch of `AddSpell`, compiling them with mocked spell
catalog/map/removal sinks. It verifies separate per-spec talent ownership and the
removal of selected spellbook siblings by a stale new-disabled direct rank. It
does not execute the complete loader, aura system, save path or worldserver;
native login, both-spec switching, points, spells and save/relog remain gameplay
acceptance checks. The compiled harness runs in the manual rehearsal, while the
Python policy units run in static CI.

## Disposable MySQL fixture rehearsals

Trained-history v6 units cover absent direct roots, lower/higher disabled ranks,
selected ownership in either spec, enabled related rows, pending/online/foreign
characters, invalid ownership, independent routes, skills, scripts, corrections,
cycles, deterministic proofs and exact-count/flag bounds. Its MySQL cycle captures
real blocker evidence through the SELECT-only reader, rejects same-count full
context drift, archives complete custom fields and checks late rollback,
apply/rerun/exact restore, preservation of deferred/selected/enabled state and
unchanged unrelated source/auth/world tables. Existing v1-v5 cycles still run.

Saved migration-blocker context units cover strict TSV parsing, duplicate GUIDs,
numeric and size bounds, literal untrusted details, deterministic grouping,
private sealed output, missing source characters and incomplete evidence after
failure. The disabled-history MySQL suite also executes this command with the
SELECT-only reader, verifies complete spell/talent/skill rows for the requested
GUIDs and TC world/DBC fingerprints, and checks unchanged source/auth/world
checksums and active-batch selection. This diagnostic command emits no executable
cleanup package and changes no reconstruction/cleanup policy or approval.

Python 3, g++ (C++17), MySQL 8 client tools, and a dedicated disposable MySQL **8.4.x** server
are required. The harness needs an administrator named `root` that can create
users and databases. It accepts localhost only and rejects port 3306.
Never point it at the server holding restored production clones.

For example, with Docker, from the toolkit checkout:

```bash
docker run --detach --name migrator-fixtures \
  --publish 127.0.0.1:33317:3306 \
  --env MYSQL_ALLOW_EMPTY_PASSWORD=yes mysql:8.4
docker logs migrator-fixtures
```

Wait for MySQL startup to finish, then confirm connectivity:

```bash
mysql --host=127.0.0.1 --port=33317 --protocol=TCP --user=root \
  -e 'SELECT @@version;'
```

Run the harness:

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 \
TRINITYCORE_DIR=/srv/src/TrinityCore \
AZEROTHCORE_DIR=/srv/src/azerothcore-wotlk \
tests/rehearsal-tests.sh
```

`REHEARSAL_MYSQL_PORT` overrides port 33317;
`REHEARSAL_MYSQL_DEFAULTS_FILE` supplies administrator client options.
Core/profile overrides reach the temporary configurations for every invoked
check. The included `tests/rehearsal.env` and `tests/populated-rehearsal.env`
are fixture configurations on port 33316, not templates for operator migrations.

The harness creates random schemas and a separate migration user, grants
read-only source/world permissions, and removes only its own objects. It tests
both directions, native update ledgers, boundary blockers, schema and source
data fingerprints, archive checksums, duplicate loot payloads, pet cleanup,
interruption/resume, completed-phase reruns, and restored indexes.
Spell fixtures create separate TC/AC worlds with read-only grants and small,
generated WDBC assets. They exercise the audited paladin chains, priest/warlock
chains, complete/overlapping spellbooks, both specialization bits, disabled and
inactive records, temporary talent spells, profession/riding tiers, exact masks,
unsupported relationships, same-count metadata/source drift and spell transaction
failure/interruption before and after commit. The trainer harness compiles the
protected AC trainer-state function with mocked getters and checks migrated
direct/wrapped spell rows in both specs; this is not a worldserver gameplay test.
The separate talent consumer harness compiles AC's protected
`_addTalentAurasAndSpells` with a recording spell-add sink. It verifies Fiery
Payback's exact child IDs, temporary flags and additional-talent exclusions;
it does not execute `_addSpell` effects, specialization switching or gameplay.
A separate research harness compiles the protected TC/AC loader auto-cast
branches with recording cast sinks. It verifies that the reviewed research
effects remain uncast and checks passive/stance/skill-step positive controls.
Spell units and MySQL fixtures cover preserved research rows/skills, required
professions, provenance, forbidden effect changes and unselected hidden talent
children. Fiery Payback fixtures use the real `64353`/`64357` talent ranks.
Shared-spell regressions distinguish ordinary Dual Wield for warriors, hunters,
rogues and death knights from shaman talent ownership in either/both specs.
They reject missing or mismatched native skill routes, class/race exclusions,
not-trainable routes, unknown owners, skill changes and unowned hidden children.
The MySQL fixture preserves ordinary Dual Wield and its `1/1` skill in both
directions, checks recorded authorization evidence and blocks an unowned shaman.
The Runeforging fixtures preserve eight ordinary enchantment rows plus the
known parent, delegating Cinderglacier and Razorice to existing skill `776` in
both directions. One child starts omitted and one stored to test overlapping
derivations; neither is persisted after conversion. Provenance and unchanged
`1/1` skill checks cover both. The loader harness checks that they remain uncast; a
separate protected TC quest-handler harness verifies the incomplete-quest
credit cast and completed/nonplayer controls with recording sinks. Unreviewed
chapter handlers and missing Runeforging skill remain blocked.
The protected TC/AC skill-reward functions run in a separate compiled harness
with dependent/temporary spell sinks, checking the two Runeforging rewards,
threshold, class, race and acquisition controls. A separate Nurturing Instinct
harness executes the protected apply/remove handlers for both ranks, checking
TC aura casts and AC temporary-only removal. Both use recording sinks; they do
not execute full spell effects or certify gameplay. MySQL fixtures preserve
selected ranks in different specs, emit `AURA` provenance without helper rows,
and block stored helper rows or differing world bindings. Exact skills/talents,
transaction rollback, interruption/resume and completed reruns remain checked.
Run just the two native consumer harnesses without MySQL using:

```bash
python3 tests/nurturing-instinct-tests.py /srv/src/TrinityCore /srv/src/azerothcore-wotlk
python3 tests/skill-reward-tests.py /srv/src/TrinityCore /srv/src/azerothcore-wotlk
```

The callback inventory regressions additionally cover exact reviewed template
arguments, changed implementations/arguments, unsafe duplicate registrations,
mutating callbacks and unknown-template rejection. Fixtures preserve WotF for
an undead warrior with existing racial skill `220`, a known T4 set bonus and
Free Friend in both directions. They grant no triggered cooldown/proc spells;
wrong-race, missing-skill and unexplained disabled states still block.

Two more compiled consumer checks run in the manual rehearsal:

```bash
python3 tests/reviewed-script-tests.py /srv/src/TrinityCore /srv/src/azerothcore-wotlk
python3 tests/temporary-rank-tests.py /srv/src/TrinityCore /srv/src/azerothcore-wotlk
```

The first executes the protected cooldown/proc/Free Friend callbacks with
recording sinks, including a null target. The second executes TC's protected
rank-learning branch and AC's protected talent consumer: a learned Primal Fury
child requests its predecessor in TC while AC adds only its exact temporary ID.
A direct-talent control requests no lower rank. These demonstrate the continuing
compatibility block; they do not add persistent temporary predecessors or
certify full gameplay. Both compiled harnesses remain outside routine push/PR CI.

Nonstandard Runeforging values/caps and tier overrides also block; native mono
normalization is not treated as an approved migration repair. Synthetic recipe
metadata uses the supplied DBC acquisition methods and trivial-skill fields.

The rehearsal entrypoint first runs a focused wide-metadata regression against
the same disposable server. It creates its own temporary schema and SELECT-only
account, reproduces error 1038 with the old all-column sort at a 32 KiB session
sort buffer, and checks that the current reader succeeds, retains deterministic
fingerprints and detects same-count text changes. Run only that regression with:

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 REHEARSAL_MYSQL_PORT=33317 \
python3 tests/spell-metadata-tests.py
```

It accepts the same core/profile and administrator option-file overrides as
the rehearsal harness and removes only its own schema/account.

The rehearsal entrypoint also runs the standalone source-audit integration
tests. They create dirty native TC fixtures under random database names and
a SELECT-only account, then verify multiple invalid rows per character,
custom spell definitions, incomplete coverage, private output, consistent reads
during a concurrent fixture edit, and source/world checksums. Run that focused
test against the dedicated disposable endpoint with:

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 REHEARSAL_MYSQL_PORT=33317 \
python3 tests/source-audit-mysql-tests.py
```

The rehearsal entrypoint additionally runs standalone talent preparation tests.
These are explicitly owned writable preparation fixtures, separate from the
migrator's read-only source fixtures. They generate an audit and SQL package,
then exercise archive-only preparation, exact non-rank removal, source/catalog
and same-count ownership drift, incomplete metadata visibility, least-privilege
grants, interrupted transactions, apply/restore reruns and exact restoration.
The timestamp regression demonstrates the old `GENERATED` substring guard's
false positive on `DEFAULT_GENERATED`, then prepares, applies and restores with
historical and NULL timestamp values preserved. Matching-audit fixtures with
virtual generated, stored generated and invisible columns still fail before
snapshots or source writes.
All unrelated character/auth/world data is checked for preservation. Run only
these tests on the dedicated disposable server with:

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 REHEARSAL_MYSQL_PORT=33317 \
python3 tests/talent-cleanup-mysql-tests.py
```

They do not certify native talent points or gameplay and do not apply generated
operator packages to preparation, staging or production databases.

Single-character pending-reset policy tests use their own disposable fixtures:

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 REHEARSAL_MYSQL_PORT=33317 \
python3 tests/character-talent-reset-mysql-tests.py
```

These check exact unavailable-group removal, full snapshots with timestamp and
custom fields, identity/spec guards, preservation of other login flags and
related data, denied-write and interrupted transaction rollback, reruns and
exact restoration. They exercise `tools/single-character-talent-reset.sql.in`;
native next-login point refunds and spell unlearning remain gameplay checks.

The shell console has an end-to-end disposable rehearsal:

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 REHEARSAL_MYSQL_PORT=33317 \
python3 tests/cleanup-console-mysql-tests.py
```

It uses restricted audit/writer roles and the real CLI for full audits,
non-rank removal, pending reset, recovery mail split at 12 attachments,
custom-field preservation, failure/interruption rollback, status/reruns,
restoration, partial setup and edited-package rejection. It dumps and reimports
its owned fixture databases with old APPLIED archives retained, starts a new
session and repeats cleanup. It checks stale-session rejection and exact
preservation of unrelated/auth/world data. These preparation tests write only
their own disposable fixtures and do not establish native gameplay acceptance.
To run the same console workflow through a dedicated server's Unix socket,
also set `REHEARSAL_MYSQL_SOCKET` to its accessible socket path. The harness
still requires its disposable TCP port and verifies that the socket server UUID
matches that endpoint before creating fixtures. All console roles then use the
socket; fixture setup and checks continue using the dedicated TCP endpoint.
The skill fixture adds weapon/defense, profession and riding over-cap values,
an in-range profession and an orphan row. It verifies source-read-only prepare,
column-only UPDATE grants, denied-write diagnostics, value/cap/custom/character
drift, injected late failure, connection interruption, exact clamps, semantic
reaudit, reruns and full restore. Skills/caps outside the exact selection,
custom fields, orphan skills, talents, spells, recipes and auth/world data are
preserved. These checks do not establish gameplay acceptance.

Focused semantic tests without MySQL:

```bash
python3 tests/spell-state-tests.py
```

When finished, remove only the dedicated fixture server and its volume:

```bash
docker stop migrator-fixtures
docker rm --volumes migrator-fixtures
```

## Fixtures and changes

`tests/fixtures/orphan-cleanup-data.sql` covers dependency cleanup and
unreachable items. `reachable-missing-owner-blockers.sql` is intentionally
applied to a loaded target clone and must block sanitization across all five
reachability root masks. `azerothcore-reverse-data.sql` exercises reverse
transforms and unsupported-data archives.

For loader, sanitizer, archive, or checkpoint changes, verify a populated
end-to-end migration, affected-operation interruption/resume, completed-phase
reruns, target schema fingerprints, restored indexes, and zero validation
errors. Run checks again against the final toolkit identity after approval or
protected content changes. CI pins the reviewed core revisions and uses the
MySQL 8.4 server baseline.
