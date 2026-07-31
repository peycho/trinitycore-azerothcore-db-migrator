# TrinityCore to AzerothCore database migration

This repository is a standalone, fail-closed migration toolkit for one
TrinityCore 3.3.5 auth/characters pair to fresh AzerothCore schemas on the same
MySQL 8 server. It does not modify either C++ project and never writes to the
world database.

The checked-in mapping registries cover every table in the pinned source and
target schemas. Exact and safely compatible columns are copied by name after
runtime metadata and value checks. Semantic changes use explicit transforms.
Unknown live-schema differences, nonempty blocked mappings, truncation,
constraint violations, source drift, or target data cause the run to stop.
The two TrinityCore auth administration views (`vw_log_history` and `vw_rbac`)
are explicitly catalogued as source-only objects; any other live view, routine,
trigger, or event blocks preflight until added to `mappings/objects.csv`.

## Safety model

- TrinityCore must be stopped before `preflight` when `REQUIRE_QUIESCENT=1`.
- Source schemas are read-only. Use a MySQL account with `SELECT` on source and
  world, and DDL/DML privileges only on the designated target/control schemas.
- Target schemas must be absent or empty. The runner does not drop schemas.
- A source table-count snapshot and normalized DDL fingerprints prevent a run
  from silently continuing after source drift.
- Every table appears in `mappings/auth.csv` or `mappings/characters.csv`.
- Target AzerothCore update ledgers and seed tables are retained.
- Large mappings are split on their leading numeric primary-key column.
  Target inserts and completed chunk checkpoints commit atomically.
- Non-unique secondary indexes on configured large tables may be deferred;
  their exact native DDL, order, hash, and rebuild state are retained.
- Source-existing orphan data is removed only from the fresh targets by the
  explicit, audited `sanitize-target` phase. Source schemas remain untouched.
- MySQL strict mode and explicit target column lists are used for all loads.
- Validation must report `READY`; AzerothCore smoke tests remain a separate
  cutover gate.

## Requirements

- MySQL 8.x server and MySQL 8 client tools (`mysql`, `mysqldump`)
- Bash 4+, `git`, `sha1sum`, `sha256sum`, `sed`, and `awk`
- Source and fresh target schemas on the same MySQL server
- Local Git checkouts at the pinned revisions:
  - [TrinityCore](https://github.com/TrinityCore/TrinityCore) 3.3.5 at
    `a1fca43764`
  - [AzerothCore](https://github.com/azerothcore/azerothcore-wotlk) at
    `5bdaa898d`

Both core repositories are required on the host running the migration. The
TrinityCore checkout supplies the pinned source-schema definition and Git
revision used to verify the mapping provenance. The AzerothCore checkout
supplies the base and released update SQL that `assemble` imports to create the
targets. The toolkit does not download these files, and copying only SQL files
is insufficient because `preflight` also verifies each Git revision and checks
the SQL tree for local changes.

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

`SOURCE_WORLD_SCHEMA` is optional and read-only. It is used only by validation
for map/item/quest/spell/creature references when such checks are available;
it is never assembled, migrated, sanitized, or written.

The config file is sourced by Bash. It must be owned and reviewed by the
operator and must not contain untrusted shell text.

## Commands

Run each command separately and inspect its reports:

```bash
bin/migrate.sh --config /secure/migration.env preflight
bin/migrate.sh --config /secure/migration.env assemble
bin/migrate.sh --config /secure/migration.env load-auth
bin/migrate.sh --config /secure/migration.env load-characters
bin/migrate.sh --config /secure/migration.env sanitize-target
bin/migrate.sh --config /secure/migration.env validate
bin/migrate.sh --config /secure/migration.env status
```

`preflight` creates a run ID in `var/`. Set `MIGRATION_RUN_ID` in the
secure config to resume from another operator host. Runtime reports are written
under `reports/<run-id>/`.

The normal phase order is enforced. Completed phases no-op. Failed table loads
and item cleanup batches can be rerun because their mutations and completion
checkpoints are atomic. A `RUNNING` checkpoint left by a killed process is
replayed only for that exact range. Never edit a mapping or transformation in
the middle of a production run; the toolkit hash will reject the old run.

This performance revision also changes the control-schema layout. Discard
targets and the control schema created by an earlier toolkit revision and
start again at `preflight`; do not resume the previously interrupted run.

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

- Auth credentials preserve SRP6 `salt` and `verifier` byte-for-byte;
  `session_key_auth` maps to `session_key`; unsupported Battle.net session data
  is excluded; online state is reset.
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
five reachability root masks.

Follow the [rehearsal](runbooks/rehearsal.md),
[production cutover](runbooks/cutover.md), and
[rollback](runbooks/rollback.md) runbooks.
