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

## Pull requests

Keep changes focused and include:

- the problem and safety implications;
- schema revisions and fixtures used;
- commands run and their outcomes;
- expected compatibility or migration behavior changes;
- documentation updates where operator behavior changes.

By contributing, you agree that your contribution is licensed under the GNU
General Public License, version 3 or any later version.
