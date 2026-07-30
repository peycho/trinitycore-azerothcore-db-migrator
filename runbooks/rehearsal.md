# Rehearsal runbook

1. Restore recent production auth and characters backups into isolated source
   schemas. Mask personal data only if the masking process preserves lengths,
   nullability, identifiers, binary SRP6 fields, and relationships.
2. Create a least-privilege migration account. Grant source/world `SELECT`,
   metadata visibility, and target/control DDL/DML permissions.
3. Copy and review the secure configuration. Set `REQUIRE_QUIESCENT=0` only
   because the restored rehearsal schemas have no writers.
4. Run `preflight`, inspect source DDL and row-count snapshots, then run
   `assemble`.
5. Review both schema-diff and type-risk reports against the checked-in mapping
   registries. Any live-only table or column requires a mapping change and a
   new run.
6. Run both load phases, then `validate`. Resolve errors; do not downgrade them
   to warnings merely to complete the rehearsal.
7. Start AzerothCore with copies of its normal configuration pointing only at
   the rehearsal targets. Keep the world database read-only.
8. Test SRP6 login, character list/login, position/homebind, equipment and
   bags, spells/talents/glyphs, cooldowns, quests, achievements, pets,
   guild/group/arena, mail, auction, channels, instance binds, logout, and
   relogin persistence.
9. Record phase duration, largest-table throughput, index/analyze duration,
   AzerothCore startup time, and smoke-test results. Tune `CHUNK_SIZE` and
   repeat from fresh targets.
10. Run the same commands a second time. All phases must no-op or skip verified
    checkpoints without creating duplicate rows.

