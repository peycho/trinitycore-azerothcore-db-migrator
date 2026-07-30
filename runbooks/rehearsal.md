# Rehearsal runbook

1. Prepare clean pinned TrinityCore and AzerothCore checkouts as described in
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
   `source-orphan-audit.tsv`; then run `assemble`.
6. Review both schema-diff and type-risk reports against the checked-in mapping
   registries. Any live-only table or column requires a mapping change and a
   new run.
7. Run both load phases, then `sanitize-target`. Review
   `cleanup-orphan-characters.tsv` and `cleanup-table-summary.tsv` before
   running `validate`. Resolve errors; do not downgrade them to warnings merely
   to complete the rehearsal.
8. Start AzerothCore with copies of its normal configuration pointing only at
   the rehearsal targets. Keep the world database read-only.
9. Test SRP6 login, character list/login, position/homebind, equipment and
   bags, spells/talents/glyphs, cooldowns, quests, achievements, pets,
   guild/group/arena, mail, auction, channels, instance binds, logout, and
   relogin persistence.
10. Record phase duration, largest-table throughput, index/analyze duration,
   AzerothCore startup time, and smoke-test results. Tune `CHUNK_SIZE` and
   repeat from fresh targets.
11. Run the same commands a second time. All phases must no-op or skip verified
    checkpoints without creating duplicate rows.
