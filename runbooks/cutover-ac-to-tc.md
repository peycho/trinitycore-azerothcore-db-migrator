# AzerothCore to TrinityCore production cutover

## Before the maintenance window

- Complete two migrations from the same production snapshot with
  `MIGRATION_DIRECTION=ac-to-tc` and the same compatibility-profile digests.
- Confirm both core checkouts pass `compatibility` and retain its report.
- Review every `SOURCE_ARCHIVE` mapping and store the verified archive outside
  the repository. Resolve all blocked or gameplay-bearing unsupported data.
- Verify backups of AzerothCore auth, characters, and the migration control
  schema. Keep the world database read-only.
- Prepare TrinityCore configuration for the new target schemas without starting
  either server.
- Define the rollback deadline. Writes accepted by TrinityCore after reopening
  are not merged back automatically.

## Cutover sequence

1. Stop AzerothCore authserver and worldserver and verify database quiescence.
2. Take and verify final backups.
3. Run `compatibility`, then `preflight`; inspect schema drift and the orphan
   audit, then run `archive-unsupported`.
4. Run `assemble`, `load-auth`, `load-characters`, and `sanitize-target`.
5. Run `validate`; continue only when the report is `READY`, every archive hash
   verifies, and every deferred index is restored.
6. Start TrinityCore privately and test authentication, character login,
   inventory, talents, cooldowns, pets, guilds, groups, arena, mail, auctions,
   instances, respawns, logout, and relogin persistence.
7. Open the realm and retain the source AzerothCore schemas read-only through
   the rollback deadline.

Do not treat a database `READY` result as an application smoke-test substitute.
