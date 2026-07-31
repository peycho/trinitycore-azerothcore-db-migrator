# Rolling back an AzerothCore to TrinityCore cutover

1. Stop TrinityCore and prevent new client connections.
2. Record the run ID, report, archive manifest, and whether TrinityCore accepted
   player writes.
3. Restore AzerothCore configuration pointing at the untouched source schemas.
4. Start AzerothCore privately and test authentication and representative
   gameplay persistence before reopening.
5. Preserve the failed TrinityCore targets and control schema for investigation.

This rollback is safe only while the original AzerothCore schemas remain
untouched. TrinityCore-era writes are not automatically converted back. Honor
the predeclared rollback deadline rather than attempting an unreviewed merge.
