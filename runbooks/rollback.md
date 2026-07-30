# Rollback runbook

Rollback is configuration-based because the migration never alters source data.

1. Stop AzerothCore immediately and prevent new client connections.
2. Record the reason, run ID, failed checks, and whether AzerothCore accepted
   any post-cutover writes.
3. Restore TrinityCore configuration and verify it still points to the original
   auth, characters, and world schemas.
4. Start TrinityCore authserver/worldserver privately and perform login and
   character smoke tests.
5. Reopen access only after the original stack is healthy.
6. Preserve the failed target/control schemas and reports for diagnosis. Do not
   merge AzerothCore-era writes back into TrinityCore without a separate,
   reviewed reverse migration.

The toolkit intentionally provides no automated target deletion or source
write-back command.

