# Rehearsal runbook

1. Choose and record `MIGRATION_DIRECTION` and `COMPATIBILITY_PROFILE`, then
   prepare both checkouts as described in [Repository setup](repository-setup.md).
   Put their paths in the rehearsal configuration, run `compatibility`, retain
   its report, and run `tests/static-checks.sh`.
2. Restore recent production auth and characters backups into isolated source
   schemas. Mask personal data only if the masking process preserves lengths,
   nullability, identifiers, binary SRP6 fields, and relationships.
3. Create a least-privilege migration account. Grant source/world `SELECT`,
   metadata visibility, and target/control DDL/DML permissions.
4. Copy and review the secure configuration. Set `REQUIRE_QUIESCENT=0` only
   because the restored rehearsal schemas have no writers.
5. Run `preflight`; inspect the run-specific compatibility report, source DDL,
   row-count snapshots, and `source-orphan-audit.tsv`. Run
   `archive-unsupported`, verify its manifest, then run `assemble`.
6. Review both schema-diff and type-risk reports against the checked-in mapping
   registries. Any live-only table or column requires a mapping change and a
   new run.
7. Run both load phases, then `sanitize-target`. Review
   `cleanup-orphan-characters.tsv`, `cleanup-table-summary.tsv`, and
   `timing.tsv` before running `validate`. A reachable missing-owner item must
   produce `cleanup-blocked-items.tsv` and stop before item deletion. Resolve
   errors; do not downgrade them to warnings merely to complete the rehearsal.
8. Start the selected target core with copies of its normal configuration
   pointing only at the rehearsal targets. Keep the world database read-only.
9. Test SRP6 login, character list/login, position/homebind, equipment and
   bags, spells/talents/glyphs, cooldowns, quests, achievements, pets,
   guild/group/arena, mail, auction, channels, instance binds, logout, and
   relogin persistence.
10. Record direction, total database time, `sanitize-target` time, largest-table
    throughput, deferred-index build duration, target-core startup time, and
    smoke-test results. Tune `LOAD_CHUNK_SIZE`, `CLEANUP_CHUNK_SIZE`, and
    `LARGE_TABLE_ROWS` from the evidence, then repeat from fresh targets.
11. Kill one rehearsal during a large load chunk and one during an item cleanup
    chunk. Rerun the same command: the exact incomplete range must replay with
    no duplicates. Kill an index rebuild once; its registry must reconcile the
    physical index and either finish the remaining rebuild or mark it restored.
12. Run the same commands a second time. All completed phases must no-op or
    skip verified checkpoints without creating duplicate rows. Compare critical
    table checksums with the first rehearsal.

Acceptance gates are: total database workflow under two hours,
`sanitize-target` under 30 minutes, zero validation errors, identical critical
checksums, every deferred index `RESTORED`, and no source/world writes.

After a failed validation, item candidates remain available for diagnosis.
After successful validation their count/min/max/checksum signature remains in the
report and checkpoint, while the large candidate staging rows are purged.

## Automated fixture rehearsals

Provision a dedicated disposable MySQL 8 instance. For example:

```bash
docker run --detach --name migrator-rehearsal \
  --publish 127.0.0.1:33317:3306 \
  --env MYSQL_ALLOW_EMPTY_PASSWORD=yes mysql:8.0.46
MIGRATOR_DISPOSABLE_MYSQL=1 tests/rehearsal-tests.sh
docker stop migrator-rehearsal
docker rm migrator-rehearsal
```

The explicit disposable-server flag is required. The harness connects only to
localhost and rejects port 3306. Override `REHEARSAL_MYSQL_PORT` for another
isolated port; `REHEARSAL_MYSQL_DEFAULTS_FILE` may supply administrator client
options. An administrator named `root` must be able to create test users and
databases. Python 3 and MySQL 8 client tools are required.

The harness creates random databases and a separate migration user, grants
read-only source/world privileges, and removes only its own objects. It tests
both directions, source DDL/data fingerprints, boundary blockers, native update
ledgers, uptime archives, duplicate loot payloads, stale pet relations,
interruption/resume, completed-phase no-ops, and restored indexes. Test approval
exists only in a temporary toolkit copy. CI runs the same harness against the
reviewed core revisions.

For v2, inspect `source-blockers.tsv` before target assembly, and resolve blocked
usernames, unsupported mail flags, empty-caster character auras, overflowing
uptime ends, ambiguous money rows, and out-of-range reverse loot payloads in a
reviewed source preparation step. Start a new migration run after resolution.
Inspect `loot-index-normalization.tsv` for AC → TC and verify the full uptime
archive before copying its common columns. Target cleanup reports must account
for dangling pet aura, spell, and cooldown rows in both directions.

Extend native-core smoke tests to cover login/reconnect with boundary-length
names, item charges/enchantments and guild banks, corpse equipment loading,
common mail flags across save/relogin, stored-loot consumption after slot
normalization, pet spellbook persistence, arena member counters, petitions,
and extended instance binds. Track the TC high-bit mail-save limitation in the
[v2 review record](profile-v2-review.md) separately.

Fixture success does not approve the profile. Follow the
[profile maintenance workflow](compatibility-profiles.md) for private native-core
and production-sized rehearsals; retain their evidence before release approval.
