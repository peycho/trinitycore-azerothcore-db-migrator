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
handlers, and spell/aura enum and effect-copy corrections.
Inventories use `LC_ALL=C`. Candidate approval exists only in disposable
toolkit copies under `/tmp`; the checkout's approval is unchanged.

## Disposable MySQL fixture rehearsals

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
