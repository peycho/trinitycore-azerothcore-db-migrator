# Contributing

Contributions are welcome, especially schema mappings, safety checks,
reproducible fixtures, and performance improvements.

## Before opening a change

1. Search existing issues and pull requests.
2. Explain which compatibility profile and actual TrinityCore/AzerothCore
   revisions the change targets.
3. Never include production dumps, credentials, account data, character data,
   generated reports, or other private server information.
4. Keep migration source and world schemas read-only in every test. Standalone
   preparation-repair tests may change only their own disposable preparation
   fixtures; keep their auth/world inputs and unrelated character data unchanged.

## Development setup

Follow [Development and automated tests](runbooks/development.md) for core-path
configuration, static checks, disposable MySQL 8.4 fixture rehearsals, and the
required checks for loader/sanitizer/checkpoint changes. Operator staging runs
follow the [migration guide](runbooks/migration-guide.md).

Python code supports 3.10 and uses only the standard library. Follow PEP 8 and
PEP 257, annotate function interfaces and state, and keep database access,
selection, SQL rendering, and CLI orchestration separate. Preserve SQL literal
contents when formatting. The [Python refactor record](runbooks/python-refactor.md)
describes the module boundaries and compatibility contracts.

When adding or extracting production modules, update `IMPLEMENTATION_FILES` in
`lib/cleanup_files.py`; spell-reader changes must also keep `SPELL_READER_FILES`
in `lib/spell_common.py` complete. Retain public re-exports that callers use
through module attributes. Contract fixtures captured from the original behavior
must not be regenerated from changed code merely to make a failing test pass.

## Pull requests

Keep changes focused and include:

- the problem and safety implications;
- schema revisions and fixtures used;
- commands run and their outcomes;
- expected compatibility or migration behavior changes;
- documentation updates where operator behavior changes.

By contributing, you agree that your contribution is licensed under the GNU
General Public License, version 3 or any later version.
