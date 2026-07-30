# Production cutover runbook

## Before the window

- Complete at least one production-sized rehearsal against the same revisions.
- Review every `SOURCE_ARCHIVE` disposition and confirm the per-account RBAC
  blocker is empty or has an approved concrete mapping.
- Verify logical and physical backups by restoring them elsewhere.
- Prepare AzerothCore configuration with the new target schema names, but do
  not start it.
- Define the rollback decision deadline. Once users write new AzerothCore data,
  rollback cannot preserve those new changes automatically.

## Migration

1. Stop TrinityCore authserver and worldserver.
2. Confirm no sessions remain connected to auth or characters.
3. Take the final consistent backups and record their locations/checksums.
4. Run `preflight`; archive the run ID and source fingerprints.
5. Run `assemble`; inspect update hashes and schema/type reports.
6. Run `load-auth`, then `load-characters`.
7. Run `validate`. A status other than `READY` is an automatic no-go.
8. Start AzerothCore privately and run the smoke tests from the rehearsal
   checklist with representative accounts.
9. If smoke tests pass, enable public access. Keep source schemas read-only and
   retain all reports/backups through the rollback deadline.

Do not run either core against the opposite schema family, and never point the
migration account's writable grants at the source or world schemas.

