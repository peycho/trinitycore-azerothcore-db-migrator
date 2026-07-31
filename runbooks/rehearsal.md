# Rehearsal runbook

1. Choose and record `MIGRATION_DIRECTION`, then prepare clean pinned
   TrinityCore and AzerothCore checkouts as described in
   [Repository setup](repository-setup.md). Put their paths in the rehearsal
   configuration and run `tests/static-checks.sh`.
2. Restore recent production auth and characters backups into isolated source
   schemas. Mask personal data only if the masking process preserves lengths,
   nullability, identifiers, binary SRP6 fields, and relationships.
3. Create a least-privilege migration account. Grant source/world `SELECT`,
   metadata visibility, and target/control DDL/DML permissions.
4. Copy and review the secure configuration. Set `REQUIRE_QUIESCENT=0` only
   because the restored rehearsal schemas have no writers.
5. Run `preflight`; inspect source DDL, row-count snapshots, and
   `source-orphan-audit.tsv`; run `archive-unsupported`, verify its manifest,
   then run `assemble`.
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
