# Production cutover runbook

## Before the window

- Confirm the pinned core checkouts from
  [Repository setup](repository-setup.md) are present on the migration host,
  clean, readable by the operator, and referenced by the production config.
- Complete at least one production-sized rehearsal against the same revisions.
- Complete two production-sized rehearsals within the two-hour total and
  30-minute sanitization targets. Confirm identical critical checksums and no
  deferred index outside `RESTORED`.
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
4. Run `preflight`; archive the run ID and source fingerprints, and review the
   source orphan audit against the approved rehearsal.
5. Run `assemble`; inspect update hashes and schema/type reports.
6. Run `load-auth`, then `load-characters`.
   Use `status` during long chunks to record the active range, elapsed time,
   recent throughput, and index state.
7. Run `sanitize-target`; archive and review the orphan-character manifest and
   per-table cleanup counts. A guild-leader, arena-captain, or reachable-item
   blocker is an automatic no-go pending an explicit data-owner decision.
8. Run `validate`. A status other than `READY` is an automatic no-go.
9. Start AzerothCore privately and run the smoke tests from the rehearsal
   checklist with representative accounts.
10. If smoke tests pass, enable public access. Keep source schemas read-only and
   retain all reports/backups through the rollback deadline.

Do not run either core against the opposite schema family, and never point the
migration account's writable grants at the source or world schemas.

## Interrupted index rebuild

Do not add or drop indexes manually. Rerun the same load command. The deferred
index registry compares each recorded index with `information_schema`: indexes
already rebuilt are marked `RESTORED`, and all remaining definitions are
rebuilt together. If any row remains `DROPPED` or `FAILED`, cutover is a no-go.

Do not purge `cleanup_item_candidate` manually. Failed validation deliberately
retains it. Successful validation records its signature in the final report
and purges it; root staging rows are purged by `sanitize-target`.
