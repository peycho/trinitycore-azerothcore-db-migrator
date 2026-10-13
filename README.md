# TrinityCore/AzerothCore database migrator

[![CI](https://github.com/peycho/trinitycore-azerothcore-db-migrator/actions/workflows/ci.yml/badge.svg)](https://github.com/peycho/trinitycore-azerothcore-db-migrator/actions/workflows/ci.yml)
[![License: GPL v3 or later](https://img.shields.io/badge/License-GPL_v3_or_later-blue.svg)](COPYING)

This repository is a standalone, fail-closed migration toolkit for moving one
realm's auth and characters data between profile-approved TrinityCore 3.3.5
and AzerothCore revisions on the same MySQL 8 server. Both `tc-to-ac` and
`ac-to-tc` create fresh native target schemas. The toolkit does not modify
either C++ project and never writes to the world database.

> [!CAUTION]
> Database migration is destructive to its designated target schemas and can
> cause permanent data loss when misconfigured. Use verified backups, isolated
> rehearsals, least-privilege credentials, and the cutover/rollback runbooks.
> The software is provided without warranty.

This release supports repository content approved by its checked-in
compatibility profiles. It is not a generic converter for arbitrary core
versions. Unrelated upstream commits are accepted; protected auth/characters
SQL or reader changes require review, profile and mapping updates where needed,
fixtures, and production-sized rehearsals.

The current `tc335-acwotlk-v2` profile is an **UNREVIEWED release candidate**.
Production commands reject it until native-core smoke tests and two
production-sized isolated rehearsals pass. Repository tests enable the
candidate only in disposable toolkit copies. The v1 artifacts remain historical
evidence; use the older toolkit release for that baseline. See the
[v2 review and acceptance record](runbooks/profile-v2-review.md).

The checked-in mapping registries cover every table in the reviewed source and
target schemas. Exact and safely compatible columns are copied by name after
runtime metadata and value checks. Semantic changes use explicit transforms.
Unknown live-schema differences, nonempty blocked mappings, truncation,
constraint violations, source drift, or target data cause the run to stop.
The two TrinityCore auth administration views (`vw_log_history` and `vw_rbac`)
are explicitly catalogued as source-only objects; any other live view, routine,
trigger, or event blocks preflight until added to the selected direction's
`objects.csv` registry.

## Safety model

- The source core must be stopped before `preflight` when `REQUIRE_QUIESCENT=1`.
- Source schemas are read-only. Use a MySQL account with `SELECT` on source and
  world, and DDL/DML privileges only on the designated target/control schemas.
- Target schemas must be absent or empty. The runner does not drop schemas.
- A source table-count snapshot and normalized DDL fingerprints prevent a run
  from silently continuing after source drift.
- Every table appears in the selected direction's auth or characters registry
  under `mappings/`.
- Target-core update ledgers and seed tables are retained.
- Large mappings are split on their leading numeric primary-key column.
  Target inserts and completed chunk checkpoints commit atomically.
- Non-unique secondary indexes on configured large tables may be deferred;
  their exact native DDL, order, hash, and rebuild state are retained.
- Source-existing orphan data is removed only from the fresh targets by the
  explicit, audited `sanitize-target` phase. Source schemas remain untouched.
- MySQL strict mode and explicit target column lists are used for all loads.
- Every MySQL client session is initialized to UTC so checkpoint and timing
  timestamps remain comparable when the server uses a local timezone.
- Validation must report `READY`; target-core application smoke tests remain a
  separate cutover gate.

## Requirements

- MySQL 8.x server and MySQL 8 client tools (`mysql`, `mysqldump`)
- Bash 4+, `git`, `sha1sum`, `sha256sum`, `sed`, and `awk`
- Source and fresh target schemas on the same MySQL server
- Local Git checkouts of [TrinityCore](https://github.com/TrinityCore/TrinityCore)
  3.3.5 and [AzerothCore](https://github.com/azerothcore/azerothcore-wotlk)

CI and the automated rehearsal harness use the MySQL 8.4.x server baseline.

Both core repositories are required on the host running the migration. They
supply the native source/target schema definitions and released target updates.
The toolkit records each actual full Git revision but grants compatibility only
when protected SQL and semantic-reader manifests match the selected reviewed
profile. Copying only SQL files is insufficient because reader semantics are
also verified.

Neither core needs to be compiled, and the toolkit does not modify either
checkout. Keep both available for the complete run, including resumed commands.
Their locations do not need to be siblings: configure absolute
`TRINITYCORE_DIR` and `AZEROTHCORE_DIR` paths when using another layout. See
[Repository setup](runbooks/repository-setup.md) for exact commands and the
supported directory layouts.

Use a MySQL option file instead of putting a password in the environment:

```ini
[client]
password=replace-me
ssl-mode=REQUIRED
```

Restrict it with `chmod 0600`.

## Configuration

Copy `config/migration.env.example` to a secure location and set:

- source/target/control schema names;
- `MIGRATION_DIRECTION=tc-to-ac` or `ac-to-tc`;
- `COMPATIBILITY_PROFILE=tc335-acwotlk-v2`;
- MySQL endpoint and option-file path;
- `REALM_ID` matching the characters database;
- load/cleanup chunk sizes, the large-table threshold, index deferral, and
  repository paths.

The production-oriented defaults are:

```ini
LOAD_CHUNK_SIZE=500000
CLEANUP_CHUNK_SIZE=100000
LARGE_TABLE_ROWS=250000
DEFER_SECONDARY_INDEXES=1
```

`SOURCE_WORLD_SCHEMA` is read-only and is never assembled, migrated, sanitized,
or written. It is optional when no world-backed check is needed, but an
`ac-to-tc` run with nonempty creature or gameobject respawns requires it so
their IDs and maps can be validated before the two tables are merged.

The config file is sourced by Bash. It must be owned and reviewed by the
operator and must not contain untrusted shell text.

## Commands

Run each command separately and inspect its reports:

```bash
bin/migrate.sh --config /secure/migration.env compatibility
bin/migrate.sh --config /secure/migration.env preflight
bin/migrate.sh --config /secure/migration.env archive-unsupported
bin/migrate.sh --config /secure/migration.env assemble
bin/migrate.sh --config /secure/migration.env load-auth
bin/migrate.sh --config /secure/migration.env load-characters
bin/migrate.sh --config /secure/migration.env sanitize-target
bin/migrate.sh --config /secure/migration.env validate
bin/migrate.sh --config /secure/migration.env status
```

`compatibility` performs no MySQL operation. It records actual revisions and
compares protected repository content with the selected profile. A mismatch
produces a per-file diff under `reports/compatibility/` and fails closed.

`preflight` creates a run ID in `var/`. Set `MIGRATION_RUN_ID` in the
secure config to resume from another operator host. Runtime reports are written
under `reports/<run-id>/`.

`preflight` must precede both `archive-unsupported` and `assemble`, and both
must complete before loading. Completed phases no-op. Failed table loads and
item cleanup batches can be rerun because their mutations and completion
checkpoints are atomic. A `RUNNING` checkpoint left by a killed process is
replayed only for that exact range. Never edit a mapping or transformation in
the middle of a production run; the toolkit hash will reject the old run.

The compatibility-profile release changes the control-schema identity and
layout. Discard targets and control schemas created by an earlier release and
start again at `preflight`; do not resume an older run.

The v2 update retains that control-schema layout but changes toolkit identity.
It also requires fresh targets, a new run, and format 2 profiles.

`archive-unsupported` is mandatory after preflight. It no-ops when every
source-only mapping is empty. Otherwise it requires `ARCHIVE_DIR` outside the
repository and writes binary-safe compressed dumps plus a SHA-256 manifest
before loading can begin.

`ALLOW_SOURCE_ARCHIVE=1` permits reviewed archival dispositions.
Gameplay-bearing rows marked `REVIEW_REQUIRED` additionally require
`ALLOW_GAMEPLAY_ARCHIVE=1`; leave it disabled until an operator has inspected
and approved the report and archive policy.

`preflight` writes `source-orphan-audit.tsv` so inherited inconsistencies are
visible before target creation. `sanitize-target` then applies the approved
target-only policy: characters whose nonzero account is absent from auth and
their dependent data are removed; dangling inventory, mail-item, and
item-loot relations are removed; and items with missing owners are removed
only after a single indexed root set proves they are unreachable from
inventory items/bags, valid mail, auctions, or guild banks. Root masks are
`1`, `2`, `4`, `8`, and `16` respectively. The phase stops and emits
`cleanup-blocked-items.tsv` if any missing-owner item is still reachable.

Guild leaders and arena-team captains are not deleted automatically because
that could destroy valid players' organization state. If an orphan character
holds either role, assign a reviewed successor or explicitly disband the
organization and start a new run. Runtime group state led by an orphan is
removed. `realmcharacters` is target-derived after cleanup rather than copied
from TrinityCore.

## Implemented semantic transformations

### TrinityCore to AzerothCore

- Auth credentials preserve SRP6 `salt` and `verifier` byte-for-byte;
  `session_key_auth` maps to `session_key`; unsupported Battle.net session data
  is excluded; online state is reset.
- Usernames must fit AzerothCore's database and its authserver's 17-byte
  packet limit. Mail flags outside its defined mask `0x1f` and character auras
  with empty caster GUIDs block preflight and loading.
- Historical uptime rows receive a derived end time and unknown shutdown
  outcome. An overflowing end time blocks migration.
- Auth `AccountID/SecurityLevel` maps to AzerothCore `id/gmlevel`.
- AzerothCore build information and RBAC definitions remain target-owned.
  Per-account TrinityCore RBAC overrides map to exactly one target permission
  by binary-equal name while preserving the grant and realm scope. Missing or
  ambiguous permission names and scopes outside `-1` or `REALM_ID` block the
  migration.
- Character online state is reset. New inn/talent bonus state is initialized
  to the values used by a newly constructed AzerothCore player. TrinityCore
  soft-deleted characters retain their deletion metadata while their `NULL`
  active name is converted to AzerothCore's empty-string representation.
- TrinityCore talent groups become AzerothCore bit masks; duplicate spells
  across both specs are collapsed with `BIT_OR`.
- Spell rows receive both spec bits; cooldown category/end fields are
  consolidated with the later expiration time.
- Instance extension enum value `EXTENDED` becomes the target boolean.
- Item and money loot tables merge into `item_loot_storage`; money is stored as
  `itemid=0`.
- Battleground return data becomes `character_entry_point`.
- Channel IDs are assigned deterministically and the serialized ban list is
  normalized into `channels_bans`.
- Petition GUIDs seed the new petition IDs.
- Transient respawns are intentionally reset, consistent with AzerothCore's
  respawn schema transition.

### AzerothCore to TrinityCore

- Auth SRP6 bytes and the auth session key are preserved; Battle.net session
  state and runtime online state start empty.
- Account access and per-account RBAC overrides map through target column names
  and binary-equal target permission names.
- Talent spec masks expand into TrinityCore talent-group rows.
- Consolidated item loot splits into item and money tables; multiple money rows
  for one container block migration.
- Non-money loot receives consecutive deterministic indexes per container,
  preserving duplicate payloads and reporting changed indexes.
- Full uptime history is archived before copying its common columns so
  AzerothCore-only shutdown metadata remains recoverable.
- Channel bans serialize deterministically into TrinityCore's banned list.
- Entry points, instance-extension state, petitions, arena ratings, surveys,
  spell state, and cooldown state use explicit target-reader-compatible fields.
- Creature and gameobject respawns merge with TrinityCore spawn types `0` and
  `1`.
- AzerothCore-only data is archived before it is omitted. The reverse path is
  semantically compatible, not a byte-for-byte reconstruction of historical
  TrinityCore fields that were previously discarded.

See the CSV registries for every copied, seeded, empty, derived, archived, and
blocked table.

## Reports

The runner captures:

- live source and assembled target DDL;
- server version, SQL mode, time zone, charset, and collation;
- column metadata and source row-count snapshots;
- table inventory, schema diff, and type-risk TSV files;
- the explicit generated `INSERT ... SELECT` SQL used by each executable mapping;
- phase, load-chunk, and cleanup-operation checkpoints in the control schema;
- source orphan audit, exact orphan-character and item-candidate manifests,
  affected-row cleanup totals, deferred-index state, and ranked timing data;
- validation results and a final Markdown go/no-go report.

Schema dumps contain no table data but may still expose object names and
comments. Treat the report directory as operationally sensitive.

## Tests

Run repository checks:

```bash
tests/static-checks.sh
```

Run automated database checks against an isolated MySQL 8.4.x server on localhost
port 33317:

```bash
MIGRATOR_DISPOSABLE_MYSQL=1 tests/rehearsal-tests.sh
```

The harness requires Python 3, creates random test schemas and a migration user,
and removes only those objects afterward. It does not start a database server.
See [Rehearsal](runbooks/rehearsal.md) for provisioning and endpoint options.

The included `tests/rehearsal.env` is only for a disposable MySQL instance on
port 33316. It is not a production template. The static checker defaults to
sibling core checkouts; override its paths when necessary:

```bash
TRINITYCORE_DIR=/srv/src/TrinityCore \
AZEROTHCORE_DIR=/srv/src/azerothcore-wotlk \
tests/static-checks.sh
```

`tests/fixtures/orphan-cleanup-data.sql` exercises dependency cleanup and
unreachable items. `reachable-missing-owner-blockers.sql` is intentionally
applied to a loaded target clone and must make `sanitize-target` fail with all
five reachability root masks. `azerothcore-reverse-data.sql` exercises the
reviewed reverse semantic transforms and unsupported-data archive path.

Follow the [rehearsal](runbooks/rehearsal.md) and the direction-specific
cutover/rollback runbooks: [TC to AC cutover](runbooks/cutover.md),
[TC to AC rollback](runbooks/rollback.md),
[AC to TC cutover](runbooks/cutover-ac-to-tc.md), and
[AC to TC rollback](runbooks/rollback-ac-to-tc.md). Maintainers should follow
the [compatibility profile runbook](runbooks/compatibility-profiles.md) when
protected upstream content changes.

## Contributing and support

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing changes. Reproducible
bugs belong in GitHub Issues, security-sensitive reports follow
[SECURITY.md](SECURITY.md), and operational support boundaries are documented
in [SUPPORT.md](SUPPORT.md).

Never publish real database dumps, credentials, generated migration reports,
SRP6 material, email/IP data, or player/account information.

## License

trinitycore-azerothcore-db-migrator is free software licensed under the
[GNU General Public License, version 3 or any later version](COPYING).
See [THIRD_PARTY.md](THIRD_PARTY.md) for upstream-project and trademark
information.
