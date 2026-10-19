# Migration guide

Use this guide from start to finish for a staging migration. It covers both
directions, including the current v2 candidate, and gives a stopping point and
diagnostic evidence for each phase. Production cutover and rollback are at the
end of the same guide.

Run one numbered step at a time. **If a command fails, stop at that step.**
Preserve the error and reports; do not skip a phase or change a blocker into a
warning. Commands are Bash commands unless a block is labelled SQL or INI.
Replace example paths, passwords, and schema names before executing them.

### Steps

1. [Databases and direction](#1-confirm-the-staging-databases-and-direction)
2. [Tools and core checkouts](#2-check-tools-and-local-core-checkouts)
3. [Persistent staging toolkit and candidate approval](#3-prepare-the-persistent-staging-toolkit)
4. [MySQL account and credentials](#4-prepare-the-mysql-account-and-credentials)
5. [Configuration](#5-create-and-review-the-migration-configuration)
6. [Compatibility](#6-check-compatibility)
7. [Preflight](#7-run-preflight-and-inspect-the-source-audit)
8. [Archives](#8-archive-unsupported-source-data)
9. [Native target assembly](#9-assemble-native-target-schemas)
10. [Auth and character loads](#10-load-auth-and-characters)
11. [Target cleanup](#11-sanitize-targets-and-inspect-approved-removals)
12. [Validation and report](#12-validate-and-retain-the-report)
13. [Private gameplay tests](#13-start-the-target-privately-and-test-gameplay)

For a failure, use [Problems and evidence](#problems-and-evidence) or
[Interruption and resume](#interruption-and-resume). After staging acceptance,
use [Production cutover](#production-cutover) and [Rollback](#rollback).

## 1. Confirm the staging databases and direction

The source auth and characters databases must be restored production clones
on the same MySQL server as the targets. Keep the restored sources unchanged
throughout the run. Stop every core, website job, and other writer using them.

For `tc-to-ac`, this guide uses the following names:

| Database | Role and starting state |
| --- | --- |
| `trinity_auth` | Populated source auth clone |
| `trinity_characters` | Populated source characters clone |
| `trinity_world` | Read-only source world, when configured |
| `acore_auth_migrated` | New target auth; absent or containing no tables |
| `acore_characters_migrated` | New target characters; absent or containing no tables |
| `acore_migration_control_rehearsal` | Fresh control database, created by the runner |
| `acore_world` | Populated native target world for later AzerothCore smoke tests |

**Targets must have no base tables, even empty ones.** The runner imports native
target tables, seeds, and updates during `assemble`. It never drops databases.
If `acore_auth` and `acore_characters` already contain imported tables, preserve
them and use the fresh `_migrated` names above. Keep an existing control database
for its original run; choose a fresh control name for this rehearsal.

For `ac-to-tc`, use populated `acore_auth` and `acore_characters` sources,
`acore_world` as the source world, and fresh `trinity_auth_migrated`,
`trinity_characters_migrated`, and `trinity_migration_control_rehearsal` targets.
Use a populated native TrinityCore world for smoke tests. The migrator never
creates, migrates, or writes a world database or `wow_website`.

If production dumps are already imported into staging, no further source import
is needed. Retain verified backups and enough disk space for targets, reports,
and full archives. Do not start either core against migration targets yet.

## 2. Check tools and local core checkouts

Use MySQL **8.4.x** for this rehearsal; this is the tested server baseline.
Install MySQL 8 client tools, Bash 4+, Git, ripgrep (`rg`), and GNU core utilities, including
`realpath`, `find`, `sort`, `cmp`, `diff`, `xargs`, `sha1sum`, `sha256sum`,
`sed`, `awk`, and `gzip`.
Install Python 3 for spell metadata/reconstruction. Retain the DBC assets used
by each selected core; nonempty spell/talent migrations require both asset sets
and both read-only worlds, as described in [spell reconstruction](spell-reconstruction.md).

```bash
mysql --version
mysqldump --version
bash --version
git --version
rg --version
```

Both local Git core checkouts are required on the machine running the toolkit.
They supply SQL and semantic compatibility evidence; compilation is needed
later for gameplay smoke tests, not for the database migration.

The v2 reviewed revisions are:

| Core | Reviewed revision |
| --- | --- |
| TrinityCore 3.3.5 | `92127cd6252edb96fbfa36540db0eba17d0031fa` |
| AzerothCore | `1cd97629ed6ef49f5c70dec39316846381d2e450` |

From the original migrator checkout, set these operator variables. Adjust the
two core paths to your existing checkouts. Choose a new work directory for each
new rehearsal; the example is persistent so it remains available for resume.

```bash
MIGRATOR_CHECKOUT=$(pwd -P)
TC_SOURCE_DIR=/srv/src/TrinityCore
AC_SOURCE_DIR=/srv/src/azerothcore-wotlk
MIGRATION_WORKDIR="$HOME/db-migration/rehearsal-01"

git -C "$TC_SOURCE_DIR" rev-parse HEAD
git -C "$AC_SOURCE_DIR" rev-parse HEAD
git -C "$TC_SOURCE_DIR" status --short
git -C "$AC_SOURCE_DIR" status --short
```

Expected: the reviewed revisions above and clean checkout status. Protected
content, rather than only the commit ID, determines compatibility: an unrelated
commit can pass, while SQL or reader drift fails. If a checkout is missing or
different, stop and prepare the reviewed checkout without overwriting local
work. Do not fetch moving branches as a substitute for the reviewed baseline.

## 3. Prepare the persistent staging toolkit

The checked-in v2 profile is `UNREVIEWED`. The normal runner therefore rejects
it with `Compatibility profile is not approved: tc335-acwotlk-v2`, including
for `compatibility`, before accessing MySQL.

For an isolated staging rehearsal, copy the toolkit and approve the candidate
**only in that copy**. This permits gathering the acceptance evidence while
the original release remains unapproved. The copy contains code and later
reports/checkpoints; your databases stay on the configured MySQL server.
Automated tests use `/tmp`; a manual run uses the persistent directory here.

```bash
umask 077
(
    set -e
    mkdir -p "$MIGRATION_WORKDIR"
    chmod 0700 "$MIGRATION_WORKDIR"
    mkdir "$MIGRATION_WORKDIR/toolkit"
    cp -a "$MIGRATOR_CHECKOUT"/{bin,lib,sql,mappings,compatibility,config,tests,runbooks,README.md} \
      "$MIGRATION_WORKDIR/toolkit/"
    chmod -R u+rwX "$MIGRATION_WORKDIR/toolkit"
    git -C "$MIGRATOR_CHECKOUT" rev-parse HEAD > "$MIGRATION_WORKDIR/toolkit-revision.txt"
    sed -i 's/^PROFILE_APPROVAL=UNREVIEWED$/PROFILE_APPROVAL=APPROVED/' \
      "$MIGRATION_WORKDIR/toolkit/compatibility/tc335-acwotlk-v2/profile.env"
)
```

Expected: a fresh `toolkit` directory. An existing directory causes `mkdir` to
fail: for a resumed run, keep the existing copy and skip this creation step.
For a separate rehearsal, choose a different work directory and fresh schema
names and matching MySQL grants. Do not deploy this candidate copy as an
approved release.

Keep the same toolkit path, core checkouts, configuration, `var/`, and reports
for the complete run. Toolkit content **and its path** contribute to run
identity. Moving or updating the toolkit requires fresh targets and a new run.

## 4. Prepare the MySQL account and credentials

Have the staging database administrator create a dedicated migration account.
This example assumes the toolkit connects locally over TCP; use the actual
restricted operator host if it runs elsewhere. Replace the password. For the
reverse direction, substitute the source and fresh target names from step 1.

```sql
CREATE USER 'migration_operator'@'localhost' IDENTIFIED BY 'replace-with-a-strong-password';
GRANT SELECT, SHOW VIEW, LOCK TABLES ON `trinity_auth`.* TO 'migration_operator'@'localhost';
GRANT SELECT, SHOW VIEW, LOCK TABLES ON `trinity_characters`.* TO 'migration_operator'@'localhost';
GRANT SELECT ON `trinity_world`.* TO 'migration_operator'@'localhost';
GRANT SELECT ON `acore_world`.* TO 'migration_operator'@'localhost';
GRANT ALL PRIVILEGES ON `acore_auth_migrated`.* TO 'migration_operator'@'localhost';
GRANT ALL PRIVILEGES ON `acore_characters_migrated`.* TO 'migration_operator'@'localhost';
GRANT ALL PRIVILEGES ON `acore_migration_control_rehearsal`.* TO 'migration_operator'@'localhost';
GRANT PROCESS ON *.* TO 'migration_operator'@'localhost';
```

Database-specific grants work before the target databases exist. `SHOW VIEW`
and `LOCK TABLES` support source schema dumps; `PROCESS` lets the quiescence
check see other accounts' sessions. Source/world DML and DDL grants are not
needed. If the account already exists, have the administrator inspect its
grants rather than granting over a broadly privileged account. Unexpected
routines, triggers, or events require review and appropriate metadata
visibility; do not grant source write privileges to bypass an object blocker.

Create `$MIGRATION_WORKDIR/migration-client.cnf` with an editor:

```ini
[client]
password=replace-with-the-account-password
```

For a remote TLS connection, also configure the client TLS options required by
your server. Keep credentials in this file, outside version control.

```bash
chmod 0600 "$MIGRATION_WORKDIR/migration-client.cnf"
mysql --defaults-extra-file="$MIGRATION_WORKDIR/migration-client.cnf" \
  --host=127.0.0.1 --port=3306 --protocol=TCP --user=migration_operator \
  --table -e "SELECT @@version; SHOW GRANTS; SELECT id,name FROM trinity_auth.realmlist;"
```

Expected: an `8.4.*` server version, the intended restricted grants, and the
source realm ID. For `ac-to-tc`, query `acore_auth.realmlist` instead. If access
fails, fix the endpoint, account host, password, or grants before continuing.

Inspect the forward targets with the same account:

```bash
mysql --defaults-extra-file="$MIGRATION_WORKDIR/migration-client.cnf" \
  --host=127.0.0.1 --port=3306 --protocol=TCP --user=migration_operator \
  --table -e "SELECT TABLE_SCHEMA,COUNT(*) AS base_tables
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA IN ('acore_auth_migrated','acore_characters_migrated',
                           'acore_migration_control_rehearsal')
      AND TABLE_TYPE='BASE TABLE'
    GROUP BY TABLE_SCHEMA;"
```

Expected for the new names: no rows, because absent/table-free schemas have
no base tables to count. A positive count means choose fresh names. Substitute
your actual names, including TrinityCore targets for the reverse direction.

## 5. Create and review the migration configuration

```bash
cp "$MIGRATION_WORKDIR/toolkit/config/migration.env.example" \
  "$MIGRATION_WORKDIR/migration.env"
chmod 0600 "$MIGRATION_WORKDIR/migration.env"
mkdir -p "$MIGRATION_WORKDIR/archives"
```

Edit that file. The following is a complete `tc-to-ac` example; replace every
`/absolute/path` with your actual absolute path. `$MIGRATION_WORKDIR` is a shell
variable used in the commands, not a value the runner automatically knows.
The config is sourced as Bash; use only trusted text and quote paths with spaces.

```bash
MYSQL_DEFAULTS_FILE=/absolute/path/rehearsal-01/migration-client.cnf
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_SOCKET=
MYSQL_USER=migration_operator
MIGRATION_DIRECTION=tc-to-ac
SOURCE_AUTH_SCHEMA=trinity_auth
SOURCE_CHARACTERS_SCHEMA=trinity_characters
SOURCE_WORLD_SCHEMA=trinity_world
TARGET_WORLD_SCHEMA=acore_world
TRINITYCORE_DBC_DIR=/absolute/path/tc-dbc
AZEROTHCORE_DBC_DIR=/absolute/path/ac-dbc
TARGET_AUTH_SCHEMA=acore_auth_migrated
TARGET_CHARACTERS_SCHEMA=acore_characters_migrated
CONTROL_SCHEMA=acore_migration_control_rehearsal
REALM_ID=1
TRINITYCORE_DIR=/srv/src/TrinityCore
AZEROTHCORE_DIR=/srv/src/azerothcore-wotlk
COMPATIBILITY_PROFILE=tc335-acwotlk-v2
LOAD_CHUNK_SIZE=500000
CLEANUP_CHUNK_SIZE=100000
LARGE_TABLE_ROWS=250000
DEFER_SECONDARY_INDEXES=1
REQUIRE_QUIESCENT=1
ALLOW_SOURCE_ARCHIVE=1
ALLOW_GAMEPLAY_ARCHIVE=0
ARCHIVE_DIR=/absolute/path/rehearsal-01/archives
MIGRATION_RUN_ID=
```

Use the `REALM_ID` read in step 4. Source, target, and control schemas must all
have distinct names. Absolute core paths avoid a change in relative-path
resolution when using the staging copy. Archives must be outside `toolkit/`.

For `ac-to-tc`, change just these direction/schema values in the full config:

```bash
MIGRATION_DIRECTION=ac-to-tc
SOURCE_AUTH_SCHEMA=acore_auth
SOURCE_CHARACTERS_SCHEMA=acore_characters
SOURCE_WORLD_SCHEMA=acore_world
TARGET_WORLD_SCHEMA=trinity_world
TARGET_AUTH_SCHEMA=trinity_auth_migrated
TARGET_CHARACTERS_SCHEMA=trinity_characters_migrated
CONTROL_SCHEMA=trinity_migration_control_rehearsal
```

Both worlds and DBC directories are required for nonempty spell/talent
conversion. Metadata access is SELECT only; neither world is created or
updated by the runner. Reverse migrations with nonempty creature/gameobject
respawns also require the source world. Keep
`REQUIRE_QUIESCENT=1` and stop source connections. Disable this check only for
restored, isolated clones with independently confirmed absence of writers.
The check cannot prevent a job from reconnecting: keep writers stopped.

Define the two command paths once for this shell session:

```bash
MIGRATOR="$MIGRATION_WORKDIR/toolkit/bin/migrate.sh"
MIGRATION_CONFIG="$MIGRATION_WORKDIR/migration.env"
```

## 6. Check compatibility

```bash
"$MIGRATOR" --config "$MIGRATION_CONFIG" compatibility
```

Expected: all four protected SQL/semantic components `PASS`. This command
performs no MySQL operation. Its report is under
`$MIGRATION_WORKDIR/toolkit/reports/compatibility/`.

If approval is rejected, confirm you invoked the copy created in step 3. If
protected content differs, retain the companion `*-diff.txt` and stop. Do not
regenerate manifests simply to make the check pass. Retired v1 needs its older
toolkit release.

## 7. Run preflight and inspect the source audit

For old or repeatedly migrated sources, first follow
[Source inspection and preparation](source-preparation.md). Its standalone
read-only audit collects multiple findings per character without creating a
migration run. Any reviewed preparation changes belong in a separate restored
copy and must precede a fresh migration run.

```bash
"$MIGRATOR" --config "$MIGRATION_CONFIG" preflight
```

Expected: `Preflight captured source schemas for run <UUID>`. The control schema
and local `toolkit/var/run-*.id` are initialized. Reports for this run live in
`toolkit/reports/<UUID>/`. Copy the UUID from the output into this shell variable
for the report commands below:

```bash
MIGRATION_UUID=replace-with-the-reported-uuid
RUN_REPORTS="$MIGRATION_WORKDIR/toolkit/reports/$MIGRATION_UUID"
```

Inspect `server-metadata.tsv`, `source-*-schema.sql`,
`source-*-row-counts.tsv`, `source-orphan-audit.tsv`, and `source-blockers.tsv`.
The blocker file must contain no blocker rows. The orphan audit can contain
approved cleanup candidates; review the expected removals before loading.
Inspect `spell-state-blockers.tsv`, `spell-fingerprints.tsv` and
`spell-expected.tsv` as well. Unsafe spell states block before assembly;
verified predecessor derivations can increase persistent row counts.
An empty `source-blockers.tsv` clears the general representation checks only.
Spell compatibility is checked separately; `spell-state-blockers.tsv` must also
be empty before migration can proceed.
Do not resolve a missing-rank problem by granting trainer spells or deleting talents.
Spell failures print a full report path and counts by reason. The report records
the first blocker per character; inspect representative rows using the
[spell reason-code reference](spell-reason-codes.md) and
[blocker review instructions](spell-reconstruction.md#checkpoints-evidence-and-validation)
before another preflight attempt. Unreviewed script/correction behavior is not
automatically corrupt source data.
Also inspect `spell-script-review.json`: it inventories every binding on stored
spell and selected talent IDs, even when an earlier character error hides it.
Require inventory status `COMPLETE`; its per-binding reviews do not approve
ownership or cleanup and exclude derived-only IDs. Review unresolved bindings
from this saved file before rerunning a long preflight.

If preflight fails, use the [problem table](#problems-and-evidence) below.
For source changes, fix only an explicitly reviewed staging preparation copy
and start a new run with fresh target/control names. Do not edit source data
under an existing migration run.

## 8. Archive unsupported source data

```bash
"$MIGRATOR" --config "$MIGRATION_CONFIG" archive-unsupported
```

This phase is mandatory even when it reports that no nonempty tables need
archival. Otherwise it creates binary-safe compressed table dumps and
`manifest.tsv` under `archives/<UUID>/`. Archived data is retained evidence;
it is not inserted into the target.

For `ac-to-tc`, a nonempty `uptime` table requires a **full-table archive**
before common columns are copied. This preserves AzerothCore shutdown metadata.
Load and validation verify the archive checksum and source DDL fingerprint;
a missing or changed archive blocks continuation.

When an archive was created, verify its manifest and dump hashes:

```bash
ARCHIVE_RUN_DIR="$MIGRATION_WORKDIR/archives/$MIGRATION_UUID"
sha256sum --check "$ARCHIVE_RUN_DIR/manifest.tsv.sha256"
awk -F '\t' 'NR > 1 { print $5 "  " $4 }' "$ARCHIVE_RUN_DIR/manifest.tsv" |
  sha256sum --check -
```

Expected: every checksum `OK`. Keep the manifest and dumps together at their
original paths for the run. A gameplay-bearing `REVIEW_REQUIRED` archive stops
here with `ALLOW_GAMEPLAY_ARCHIVE=0`. Review the specific table and what gameplay
would be omitted before making that decision. Enabling the setting changes run
identity: configure it before a **new** run, then repeat from preflight with
fresh targets/control. Do not enable it globally just to advance past an error.

## 9. Assemble native target schemas

```bash
"$MIGRATOR" --config "$MIGRATION_CONFIG" assemble
```

Expected: native target schemas assembled, including target seeds and update
ledgers. Released updates are applied before source data is inserted;
already-applied updates require matching ledger hashes.

Inspect `auth-table-inventory.tsv`, `characters-table-inventory.tsv`,
`auth-schema-diff.tsv`, `characters-schema-diff.tsv`, both `*-type-risk.tsv`
files, and `target-*-schema.sql`. Reviewed differences are expected; unknown
tables/columns or unsafe live values require investigation.

If assembly fails partway through DDL, preserve the output and targets. DDL is
not a resumable atomic load. A retry can reject partially populated targets;
resolve the cause and use fresh targets/control for a new run.

## 10. Load auth and characters

Run and inspect these separately:

```bash
"$MIGRATOR" --config "$MIGRATION_CONFIG" load-auth
```

Then:

```bash
"$MIGRATOR" --config "$MIGRATION_CONFIG" load-characters
```

Expected: each phase completes without truncation, range, mapping, archive, or
constraint errors. Generated SQL is retained as `generated-*.sql` in the run
reports. Target RBAC and build seeds remain native; per-account permissions
require exact names and valid realm scope.

For `ac-to-tc`, inspect `loot-index-normalization.tsv` and
`generated-characters-item-loot-reverse.sql`. Non-money rows receive consecutive
zero-based slots per container. Duplicate payloads and quantities are retained;
original sparse or repeated indexes are intentionally normalized.

From a second shell with the same two command paths, monitor long operations:

```bash
"$MIGRATOR" --config "$MIGRATION_CONFIG" status
```

Run only one mutating phase at a time. Loads and transform checkpoints commit
atomically; see [interruption and resume](#interruption-and-resume) for recovery.

## 11. Sanitize targets and inspect approved removals

```bash
"$MIGRATOR" --config "$MIGRATION_CONFIG" sanitize-target
```

Review `cleanup-orphan-characters.tsv`, `cleanup-table-summary.tsv`, and
`timing.tsv`. The policy removes target copies of characters whose nonzero
account is absent and their dependent state, dangling inventory/mail/loot
relations, and dangling pet aura/spell/cooldown rows. Retained pet state is
checked later. Missing-owner items are removed only if unreachable from
inventory/bags, valid mail, auctions, and guild banks. Target realm character
counts are rebuilt after cleanup.

Guild leaders and arena captains among orphan characters block cleanup until
there is a reviewed successor/disband decision and a new source-prepared run.
Reachable missing-owner items produce `cleanup-blocked-items.tsv` and stop.
Do not delete these items manually to bypass the audit. Source data remains
unchanged. Transactional cleanup operations and chunks support resume.

## 12. Validate and retain the report

```bash
"$MIGRATOR" --config "$MIGRATION_CONFIG" validate
"$MIGRATOR" --config "$MIGRATION_CONFIG" status
"$MIGRATOR" --config "$MIGRATION_CONFIG" report
```

Expected: run status **`READY`**, zero failed error checks, and every deferred
index `RESTORED`. Inspect `final-report.md`, including warnings, archives,
cleanup totals, timings, and index state. Counts account for precisely the
approved removals; reverse loot validation checks normalized slots and payload
multiplicity.

Failed validation retains item cleanup candidates for diagnosis. Successful
validation records their signature and purges the staging rows. Do not purge
control tables manually. `READY` is database acceptance; gameplay acceptance
is the next step.

## 13. Start the target privately and test gameplay

Before starting the target authserver/worldserver, save the database acceptance
report and status. Use binaries from the reviewed target core and its normal
configuration, pointing auth and characters at the migrated targets and world
at an isolated, populated native target world. Set its realm ID correctly and
configure the copied target `realmlist` for the private staging endpoint; it
initially contains the source realm addresses. Keep public access disabled.

Keep the frozen source clones for comparison. The migrator does not assemble
world data or prepare client/data assets. If binaries or a matching world are
missing, stop here and record that gameplay acceptance is pending.

In the private target `authserver.conf`, set the auth connection, replacing
`core_user` and `core_password` with the target runtime account:

```ini
LoginDatabaseInfo = "127.0.0.1;3306;core_user;core_password;acore_auth_migrated"
Updates.EnableDatabases = 0
```

In its private `worldserver.conf`:

```ini
LoginDatabaseInfo = "127.0.0.1;3306;core_user;core_password;acore_auth_migrated"
CharacterDatabaseInfo = "127.0.0.1;3306;core_user;core_password;acore_characters_migrated"
WorldDatabaseInfo = "127.0.0.1;3306;core_user;core_password;acore_world"
RealmID = 1
Updates.EnableDatabases = 0
```

For the reverse direction, substitute `trinity_auth_migrated`,
`trinity_characters_migrated`, and the isolated TrinityCore world name. Use the
actual realm ID and endpoint. The runtime account needs the target core's normal
permissions on these isolated databases; use separate credentials from the
migration account. Disable startup updates for this smoke test because auth
and characters were assembled before loading; prepare the matching native
world separately before startup. Do not replay data-repair updates over loaded
player data. Start your installed binaries with these private configurations
and retain their startup logs.

On a production-sized restore, test representative imported characters. Three
to five characters can cover most of this checklist: include a pet class, a
dual-spec character, a guild-bank user, and a character with existing instance
binds. Use two player accounts for trade/mail/group checks and an existing GM
account for permission checks. Compare with the frozen source snapshot or
known pre-migration state. Account for elapsed time on cooldowns, mail expiry,
and instance resets.

| Area | Actions | Passing result |
| --- | --- | --- |
| Authentication | Log in with existing credentials, inspect the character list, enter the world, log out and reconnect. Include the longest supported existing username when available. | Correct accounts/characters; no password reset or missing characters. |
| Character state | Compare level, money, position, homebind, professions, quest log/completions, and important achievements. Use the hearthstone, travel between zones, and advance an existing quest. | Existing state matches; changed quest progress persists, allowing normal timers and position changes. |
| Items and bags | Inspect equipment, bank and bag contents, gems and normal enchantments. Equip/unequip an item, move it between bags/bank, split a stack, consume one charge or consumable, and trade an unbound item. | Expected stats and quantities; no disappearing or duplicated items. |
| Talents and spells | Inspect both talent specs and glyphs, switch specs, cast representative spells, and exercise a cooldown. | Correct talents/glyphs/spells for each spec; cooldown works and survives relog while active. |
| Pets | Summon an existing pet, inspect its name/level/spellbook, cast an ability, dismiss and resummon it. For a hunter, test the stable. | Retained pet state and abilities persist; no unexpected loss of pets or spells. |
| Mail | Open existing migrated mail, read its body, take an attachment, and check money/COD if present. Send one item and some copper between the test accounts. Inspect prepared auction/GM mail when available. | Attachment/money transferred exactly once; remaining mail and read state persist. Check the accepted GM-return behavior separately. |
| Stored loot | Use a migrated container that already had stored loot. Take one item or money, close/reopen it, then relog with remaining loot. | Correct remaining payload and quantities; no duplicate or missing loot. |
| Auctions | Inspect existing migrated listings. List one cheap item, cancel it, and retrieve it through mail; complete a purchase with a second account if available. | Correct listed item/quantity and mail settlement, allowing normal fees and delivery delays. |
| Guilds and guild banks | Inspect guild membership/ranks and bank tabs. Deposit and withdraw one item using an authorized member; check a restricted member if available. | Correct contents and access; transfer persists without duplication. |
| Groups, arena, channels | Group two characters, change the leader, then relog. Inspect an existing arena team's membership/ratings and counters. Join an existing custom channel and check its saved moderation/ban state when present. | Appropriate membership, permissions and stored state; functional group/channel interaction. |
| Petitions | Inspect a migrated charter and its remaining valid signatures, then add a signature using another account if available. | Charter loads and signatures persist without duplication. |
| Instances | Inspect an existing saved instance, enter it, exit/re-enter, and relog. Check an extended bind when available. For AC → TC, also exercise migrated respawns. | Correct instance identity/reset/extension and preserved saved progress. |
| Corpses | Test an existing dead character/corpse when available. Also die on a test character, release, reclaim the corpse or resurrect, and relog. | Corpse loads with expected appearance; resurrection and equipment remain correct. |
| Permissions | Use a harmless permitted GM command and verify a normal player cannot use it. Check any migrated per-account overrides. | Intended realm-scoped access with no unintended privilege grants. |
| New characters | Create one normal character, enter the world, inspect starting items/spells, log out and log back in. | Native target creation works and the new character persists. |
| Persistence and logs | After the checks, log everyone out, shut down both target servers cleanly, restart them, and repeat key observations. Review startup/login/save logs. | All saved changes persist; no new SQL, serialization, item-loading or crash errors. |

Record each case as `PASS`, `FAIL`, or `NOT TESTED`, with a brief observation.
If the snapshot has no charter, stored-loot container, extended bind, or other
rare state to exercise, record that limitation rather than marking it passed.
Accepted feature omissions, such as an inactive custom appearance system, must
be listed separately from stock gameplay checks. Keep the checklist, target
revision and startup/shutdown logs privately with `final-report.md`.

At the reviewed TC revision, its mail-save code still narrows flags to eight
bits. Record that upstream high-bit persistence limitation separately;
migrated AzerothCore mail uses the supported common flags. Core fixes are
outside this toolkit.

Starting the core introduces target writes. Retain database evidence before
smoke tests; rerun/resume acceptance checks use an untouched migration target,
or a separately preserved clone, rather than gameplay-mutated tables.


## Interruption and resume

For interrupted `load-auth`, `load-characters`, or `sanitize-target`, first
confirm the original process has exited and its MySQL work has finished or
rolled back. Keep writers stopped. Invoke `status`, then rerun the **same failed
phase** with the same toolkit path/configuration and unchanged sources.
Incomplete ranges replay through atomic checkpoints; completed phases no-op.

If an index rebuild was interrupted, rerun its load phase. The registry
reconciles indexes already rebuilt and restores remaining native definitions.
Do not add/drop indexes manually. Continue only when all are `RESTORED`.

After reconnecting your shell, restore the variables without recreating files:

```bash
MIGRATION_WORKDIR="$HOME/db-migration/rehearsal-01"
MIGRATOR="$MIGRATION_WORKDIR/toolkit/bin/migrate.sh"
MIGRATION_CONFIG="$MIGRATION_WORKDIR/migration.env"
"$MIGRATOR" --config "$MIGRATION_CONFIG" status
```

Local run IDs are in `toolkit/var/`. If that state is missing, set
`MIGRATION_RUN_ID` to the recorded UUID in the secure config. This does not make
a moved/changed toolkit compatible with an old run. Preserve the exact run
files and paths; source, mapping, transform, approval, or tuning changes need
a new run and fresh target/control schemas. Preserve failed runs for diagnosis
and choose new names instead of dropping imported databases.

## Problems and evidence

| Failure | Stop and inspect |
| --- | --- |
| Profile not approved | Step 3; check that the command invokes the staging copy |
| Protected content mismatch | Compatibility TSV and companion `*-diff.txt`; verify checkout revisions and local changes |
| MySQL access/dump failure | Endpoint, account host, grants, client version, exact error; incomplete DDL cannot be used |
| Target not empty | Choose new target names; truncating rows does not remove tables |
| Source sessions active | Stop core/jobs/other connections and confirm quiescence |
| Source representation incompatible | `source-blockers.tsv`: TC → AC username character/byte lengths (32 characters and 17 bytes), mail bits outside `0x1f`, empty aura casters, uptime overflow; AC → TC multiple money rows or loot numeric bounds |
| Unsupported archive requires approval | Specific mapping/table, retained gameplay meaning, archive policy; configuration decisions precede a fresh run |
| Archive missing/checksum mismatch | Original dump/manifest paths and hashes; recover the verified archive without fabricating one |
| Permission mapping failure | Source override names and scopes; exact target name must be unique, scope must be `-1` or configured realm |
| Unknown live table/column/object | Source DDL and schema/type reports; custom core/module data needs explicit reviewed mappings |
| Cleanup blocked | Orphan-character manifest or `cleanup-blocked-items.tsv`; data-owner decision before a fresh run |
| Different configuration/toolkit or source drift | Original run identity and snapshots; restore unchanged run files or start fresh |
| Validation errors/index failure | `final-report.md`, `status`, generated SQL and affected cleanup/chunk checkpoints |

When asking for help, include the exact failing command, redacted error output,
phase, migration direction, run UUID, toolkit revision, both core revisions,
MySQL server/client versions, and affected report/check names. Retain full
reports privately. They and archives can contain account/character identifiers
or source data; do not publish credentials, SRP6 bytes, emails/IPs, or raw dumps.

## Rehearsal acceptance and release approval

Before production, complete two production-sized isolated rehearsals using
the same reviewed content and record:

- total database workflow under two hours and sanitization under 30 minutes;
- zero validation errors and all deferred indexes `RESTORED`;
- identical critical checksums between untouched migration results;
- no source/world writes by the migrator;
- successful native gameplay smoke tests and target startup time;
- interruption/resume during a large load, cleanup chunk, and index rebuild,
  plus completed-phase reruns without duplicates.

Perform interruption/rerun exercises on disposable rehearsal results before
gameplay writes. Tune chunk sizes only between fresh runs. Retain timing,
checksum, archive, report, and smoke-test evidence privately. Release approval
also requires populated automated acceptance in both directions. A maintainer
can then approve the release profile and rerun checks against the final toolkit
identity. Approval in the staging copy alone does not approve the release.

## Production cutover

Proceed only with an approved release, successful rehearsals within the timing
gates, verified logical/physical backup restores, a rollback deadline, and a
prepared target core. Candidate staging approval does not authorize production.

1. Stop the source authserver/worldserver and every other writer; prevent
   reconnects and confirm quiescence.
2. Take final consistent backups and record their checksums/locations.
3. Prepare a new run using the approved toolkit and fresh target/control
   schemas. Follow steps 4–12 with the production endpoint, retaining and
   reviewing every report. Do not reuse a staging run or its candidate copy.
4. Continue only with `READY`, zero validation errors, verified archives, all
   indexes restored, and reviewed cleanup. A blocker is a no-go.
5. Start the target privately with its intended configuration and endpoint;
   perform step 13's smoke tests before reopening access.
6. Open the realm only after all gates pass. Keep original source schemas
   unchanged and retain backups/reports through the rollback deadline.

Do not run a core against the other core's schema family. Once the target
accepts player writes, switching back does not automatically preserve them.

## Rollback

Rollback uses the untouched source schemas in either migration direction.

1. Stop the target core and prevent new connections.
2. Record the reason, run UUID, failed checks, and whether target-era player
   writes occurred; preserve target/control databases, archives, and reports.
3. Restore the source core configuration pointing at its original auth,
   characters, and world databases.
4. Start the source privately and verify login and representative persistence.
5. Reopen access after the original stack is healthy, honoring the declared
   rollback deadline.

Target-era writes are not automatically merged back. Their recovery requires
a separately reviewed data migration. The toolkit has no automated database
deletion or source write-back command.
