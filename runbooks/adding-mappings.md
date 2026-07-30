# Adding or changing mappings

1. Capture fresh no-data dumps with routines, triggers, events, checks,
   generated columns, collations, and indexes. Record server variables and
   exact core revisions.
2. Start a new rehearsal run and inspect `*-table-inventory.tsv`,
   `*-schema-diff.tsv`, and `*-type-risk.tsv`.
3. Add every new source and target table to the appropriate CSV. Use:
   - `COPY` only for approved common-by-name data;
   - `TRANSFORM` for renames, splits, merges, enum changes, packed fields, or
     semantic defaults;
   - `TARGET_SEED`, `TARGET_EMPTY`, or `DERIVED` for target-owned objects;
   - `SOURCE_ARCHIVE` only with an explicit loss rationale;
   - `BLOCKED` when semantics are unresolved.
4. For a transform, add an explicit target list and source expression list or a
   specialized transactional loader. Never use `SELECT *`.
5. Read only the relevant prepared statements/loaders in both C++ projects.
   Verify binary layouts, bit masks, epochs, enum meanings, packed text, and
   ownership relationships.
6. Extend validation with row-count rules and logical orphan/domain checks.
7. Update static inventory tests and run a populated rehearsal twice.
8. Pin the new revisions and require operator review before production.

