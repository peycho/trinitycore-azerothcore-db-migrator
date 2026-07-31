# SQL execution model

`00_control_schema.sql` is the only static SQL imported directly by the runner.
Target DDL is intentionally sourced from the selected profile-approved core
rather than duplicated here: AzerothCore base/update directories for
`tc-to-ac`, or the TrinityCore base schemas and current 3.3.5 update directories
for `ac-to-tc`.
The control schema also stores the orphan-character manifest, compact
`BINARY(16)` item root/candidate sets, affected-row cleanup summaries,
operation checkpoints, and exact deferred-index definitions.

The shell runner generates explicit `INSERT ... SELECT` statements from:

1. the approved CSV mapping row;
2. live `information_schema` metadata;
3. named semantic transformations in `lib/load.sh`.

Generated common-column statements are accepted only when every missing target
column is nullable, generated, auto-incremented, or has a default. Runtime
checks reject NULL, string/binary length, and integer range violations before
the insert. MySQL strict mode catches remaining conversion errors.

DDL order is:

1. native target base tables and seed rows;
2. released target updates and update-ledger checkpoints;
3. transformed data in logical dependency order, with optional non-unique
   secondary-index deferral for large tables;
4. indexed set-based target-only orphan sanitization and realm-count derivation;
5. deferred-index restoration, auto-increment reseeding, and `ANALYZE TABLE`;
6. explicit relational and domain validation.

The reviewed TrinityCore auth schema contains two administration views, both
explicitly dispositioned in `mappings/tc-to-ac/objects.csv`; AzerothCore has no
target counterparts. Live dumps include all non-table object types, and any
unlisted view, routine, trigger, or event blocks preflight.
