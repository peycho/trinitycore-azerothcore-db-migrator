# Python refactor record

Validation date: 2026-10-29.

This refactor preserves the Python 3.10 runtime and adds no dependencies. It
separates orchestration from database access, evidence capture, policy selection,
and package publication. All 35 original production Python modules were reviewed
and updated. The resulting 56 modules contain 388 annotated function signatures.
Annotations at variable-layout SQL and JSON boundaries deliberately retain
heterogeneous evidence dictionaries; they are not runtime schema validators.

## Architecture and compatibility

- [Console compatibility facade](../lib/cleanup_console.py): the existing
  entry point and public helpers remain available. Configuration and credential
  handling, private files, workspace state, command registrations, and guarded
  execution now have focused modules. Broad exception handling remains at the
  operator-facing error/journal boundary.
- [History workflow](../lib/cleanup_history_workflow.py): explicit options,
  evidence, policy, selection, snapshot, package, SQL, verification, publication,
  and reporting stages replace the original 923-line planning function.
  [Dataclasses](../lib/cleanup_history_models.py) describe the data passed
  between stages. Policy precedence and rejection order remain explicit.
- [Spell reconstruction](../lib/spell_reconstruction.py): one context owns one
  character's working state. Ordered methods handle ownership, native runtime
  relationships, authorization, skills, roots, dependency expansion, and final
  proofs. Metadata loading and reviewed compatibility rules are separate.
  [The original module](../lib/spells.py) retains its imports and streaming CLI.
- [Shared types](../lib/cleanup_types.py): native spell/skill state, result
  dictionaries, journals, and narrow database interfaces have reusable types.
- [Policy descriptions](../lib/cleanup_policy_descriptions.json): 62 descriptions
  moved out of a large Python literal without changing their text. The catalog
  is included in toolkit completeness and integrity checks.

Snapshot session settings are explicit parameters rather than temporary changes
to a shared object's method:

```python
captured = snapshot(
    settings,
    queries,
    session_prefix="SET SESSION time_zone='+00:00';\n"
                   "SET SESSION group_concat_max_len=6400001;\n",
)
```

The existing transaction prefixes, SQL contents, ordering, role selection,
credential redaction, and temporary credential-file cleanup are preserved.
Existing command names, arguments, defaults, error codes, exit codes, persistent
representations, policies, SQL templates, core pins, and profile approval remain
unchanged.

New cleanup manifests add `implementation_sha256`, covering production Python
dependencies and the description catalog. Publication checks those hashes
against the operation's initial journal; batch execution checks the frozen
manifest. New source audits add `spell_reader_sha256`, covering the extracted
reader dependencies as well as the original facade. Existing producer fields
and checks remain in force.

Historical evidence is never resealed. Manifests without the supplemental fields
retain their historical validation path. Changed toolkit files still trigger
existing drift checks: use the matching retained toolkit for old batches and
migration runs. Fresh operations must regenerate their evidence and candidates.

## Changes by original module

Each link opens the complete improved code. The table records the original
readability problem and the resulting change; it does not describe new migration
or cleanup policies.

| Improved code | Original problem | Main change and benefit |
| --- | --- | --- |
| [cleanup_console](../lib/cleanup_console.py) | Configuration, credentials, files, sessions, parsing, and execution shared one module. | Compatibility facade delegates to focused modules while retaining the error boundary. |
| [cleanup_disabled_history](../lib/cleanup_disabled_history.py) | A 923-line planner mixed policy choice, evidence, SQL, and publication. | Ordered, typed stages make data flow and verification boundaries visible. |
| [spells](../lib/spells.py) | Metadata, I/O, compatibility rules, and a 739-line closure were interleaved. | Streaming CLI and public imports remain; dedicated modules own metadata, rules, and reconstruction. |
| [cleanup_active_reset](../lib/cleanup_active_reset.py) | Untyped row layouts and dense SQL expressions obscured reset guards. | Typed inputs, expanded statements, and leaf utility imports clarify the existing archived reset. |
| [cleanup_death_coil](../lib/cleanup_death_coil.py) | Proof records and rejection results had implicit shapes. | Explicit metadata, character, and proof types clarify the fixed native-base contract. |
| [cleanup_dual_spec_teacher](../lib/cleanup_dual_spec_teacher.py) | Compact validation and result construction hid the stored-state requirements. | Expanded guards and typed selection results make exclusions easier to follow. |
| [cleanup_eligibility](../lib/cleanup_eligibility.py) | Metadata capture temporarily replaced `settings.sql`; evidence layouts were implicit. | Explicit session prefixes and typed reader boundaries remove hidden method mutation. |
| [cleanup_foreign_skills](../lib/cleanup_foreign_skills.py) | Catalog caches and family-selection state were untyped and compressed. | Catalog attributes, selector inputs, and results now expose their intended shapes. |
| [cleanup_inactive_legacy](../lib/cleanup_inactive_legacy.py) | Dense catalog and ownership guards were difficult to scan. | Typed contracts and expanded control flow preserve the narrow legacy-family policy. |
| [cleanup_migration_evidence](../lib/cleanup_migration_evidence.py) | Report loading, grouping, and capture code lacked interface types. | Typed report and database boundaries clarify the read-only evidence workflow. |
| [cleanup_native_actions](../lib/cleanup_native_actions.py) | Compressed action selection increased the cost of reviewing exclusions. | Expanded statements and typed contracts make the fixed action policies explicit. |
| [cleanup_native_skills](../lib/cleanup_native_skills.py) | Planning mixed implicit state with temporary SQL-method replacement. | Explicit snapshot settings and typed selections distinguish insertion and normalization data. |
| [cleanup_obsolete_riding](../lib/cleanup_obsolete_riding.py) | Item capture, native contracts, and guard generation had implicit inputs. | Typed evidence and clearer expressions expose the existing item-dependent deferrals. |
| [cleanup_ordinary_history](../lib/cleanup_ordinary_history.py) | Flags and requirement proofs were difficult to distinguish in dense code. | Typed contracts and expanded branches make the existing prerequisites easier to review. |
| [cleanup_ownership](../lib/cleanup_ownership.py) | Mask, alias, and rekey evidence relied on undocumented value shapes. | Typed contracts and readable expressions preserve the selected-build ownership rules. |
| [cleanup_pet_teaching](../lib/cleanup_pet_teaching.py) | Native binding proofs and deferral tuples were implicit. | Typed binding/selection contracts clarify the difference between supported and deferred routes. |
| [cleanup_plans](../lib/cleanup_plans.py) | Shared snapshot, rendering, policy prose, and package code were intertwined. | Explicit session settings, external description data, and complete implementation fingerprints clarify package creation. |
| [cleanup_professions](../lib/cleanup_professions.py) | Crafting metadata and activation outputs lacked types. | Typed contracts and expanded guards clarify the existing-row-only activation policy. |
| [cleanup_racial_skills](../lib/cleanup_racial_skills.py) | Reward sets and native skill evidence had implicit representations. | Typed reward/selection interfaces make grant boundaries and preserved state visible. |
| [cleanup_recipe](../lib/cleanup_recipe.py) | Dense registry literals obscured commands and count modes. | Consistent multiline formatting makes the same fixed recipe registry easier to inspect. |
| [cleanup_selected_passive](../lib/cleanup_selected_passive.py) | Ownership evidence and optional native proofs were untyped. | Typed proof results and expanded conditions clarify selected-lower-passive authority. |
| [cleanup_selected_rank_history](../lib/cleanup_selected_rank_history.py) | Selected, excluded, and proof rows had implicit tuple shapes. | Explicit result types clarify the unchanged exact-row selection contract. |
| [cleanup_shaman_dual_wield](../lib/cleanup_shaman_dual_wield.py) | Starting-skill capture temporarily changed the shared SQL method. | Explicit snapshot settings and typed capture data preserve paired spell/skill guards. |
| [cleanup_shaman_offhand](../lib/cleanup_shaman_offhand.py) | Equipment facts, placement decisions, and guard inputs were implicit. | Typed evidence and expanded statements clarify the existing reviewed placement policy. |
| [cleanup_skill_teaching](../lib/cleanup_skill_teaching.py) | Compact teaching checks and selection results lacked types. | Typed metadata and selection interfaces make the existing wrapper exclusions visible. |
| [cleanup_skills](../lib/cleanup_skills.py) | Audit producer checks assumed the spell reader lived in one file. | Supplemental reader fingerprints and typed audit inputs preserve implementation provenance after extraction. |
| [cleanup_specialization_parent](../lib/cleanup_specialization_parent.py) | Parent restoration mixed several implicit evidence shapes. | Typed selection contracts and readable guards clarify the same verified-parent repair. |
| [cleanup_specializations](../lib/cleanup_specializations.py) | Equipment-state and native metadata boundaries were untyped. | Typed capture/guard interfaces make native-invalid item handling easier to audit. |
| [cleanup_spell_history](../lib/cleanup_spell_history.py) | Classification inputs were implicit and producer checks covered one reader file. | Typed state and supplemental reader fingerprints preserve captured-evidence provenance. |
| [cleanup_talent_relations](../lib/cleanup_talent_relations.py) | Graph caches, edges, and native family results lacked types. | Explicit graph attributes and typed family contracts clarify relationship traversal. |
| [cleanup_trained_history](../lib/cleanup_trained_history.py) | Captured inspection tuples and dependent candidates were implicit. | Typed capture and selection interfaces make the existing ownership checks easier to navigate. |
| [metadata profile generator](../bin/generate-spell-metadata-profile.py) | AST evaluation and generated policy data lacked interface types. | Typed parser/generator functions and consistent formatting preserve conservative profile generation. |
| [source audit](../tools/audit-tc-source.py) | Query/report state lacked types; reader hashing assumed one module. | Typed streaming/report state and complete reader fingerprints preserve read-only audit provenance. |
| [talent cleanup planner](../tools/plan-talent-cleanup.py) | Report and rendering contracts were implicit; helper dependencies were not separate files. | Typed inputs and supplemental reader verification protect unchanged SQL generation. |
| [preparation replay](../tools/replay-source-preparation.py) | Dense statements and untyped replay state obscured orchestration. | Typed state and expanded steps clarify the same evidence regeneration, stopping, and migration sequence. |

Supporting console and replay tests were reformatted without changing their
assertions. The new [contract tests](../tests/python-contract-tests.py) use
[expectations captured from the original implementation](../tests/fixtures/python-refactor-contracts.json),
not expectations regenerated from refactored code.

## Validation

The reviewed core revisions used for the baseline and final validation are:

- TrinityCore: `92127cd6252edb96fbfa36540db0eba17d0031fa`.
- AzerothCore: `1cd97629ed6ef49f5c70dec39316846381d2e450`.
- Python: `3.10.12`; isolated MySQL: `8.4.10`.

Completed checks:

- Original full static checks and original complete bidirectional MySQL rehearsal.
- Extracted history transaction suite: all 24 check groups passed.
- Final static checks: 40 fast suites and 533 tests, including the ten new
  contract tests, plus compatibility-profile tests, schema-dump failure checks,
  and ShellCheck.
- Exact baseline comparisons for 60 policy acknowledgement programs and their
  missing-field errors, CLI declarations, ten reconstruction/rejection cases,
  and the unchanged description catalog.
- Integrity checks for extracted dependencies, code changes during generation,
  batch drift rejection, and historical manifests.
- The riding planner's native-defaults reader remains available through its
  existing module re-export; a regression test protects that interface.
- Comparison with the original tree found 207 existing function bodies
  identical after removing imports, annotations, and documentation. Other
  changed bodies correspond to the planned extractions, explicit snapshot
  settings, catalog loading, and provenance checks.
- Python 3.10 syntax and complete production signature annotations, checked
  using the standard library. Formatting edits were checked against parsed
  syntax trees; SQL string values were preserved. Ordinary code lines fit the
  79-character limit; existing multiline SQL literal content is retained.

The complete disposable rehearsal passed all 85 Python entry points and the
final bidirectional migration checks, including rollback, interruption/resume,
reruns, blocker handling, restored indexes, and immutable source/world inputs.
The final log ends with `Disposable bidirectional MySQL rehearsals passed.`

A final spacing-only cleanup preserved the complete parsed syntax trees. After
that cleanup, all 533 fast tests and the 16-group console transaction suite were
rerun successfully against the final files and their current fingerprints.

Reproduce the full checks with reviewed checkouts and a dedicated disposable
MySQL endpoint, following [development.md](development.md):

```bash
TRINITYCORE_DIR=/path/to/reviewed/TrinityCore \
AZEROTHCORE_DIR=/path/to/reviewed/azerothcore-wotlk \
tests/static-checks.sh

TRINITYCORE_DIR=/path/to/reviewed/TrinityCore \
AZEROTHCORE_DIR=/path/to/reviewed/azerothcore-wotlk \
REHEARSAL_MYSQL_PORT=33327 MIGRATOR_DISPOSABLE_MYSQL=1 \
tests/rehearsal-tests.sh
```

These are repository and disposable-fixture results. They do not approve a
production migration, native gameplay, or the currently unreviewed profile.
No static type checker was added or run.

## Further structural improvements

Policy-specific evidence dictionaries can gain narrower types as their schemas
stabilize. Some selectors and metadata guards remain long because they encode
reviewed eligibility sequences; further extraction should retain their rejection
precedence and add policy-specific characterization cases first.
