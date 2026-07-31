# Contributing

Contributions are welcome, especially schema mappings, safety checks,
reproducible fixtures, and performance improvements.

## Before opening a change

1. Search existing issues and pull requests.
2. Explain which compatibility profile and actual TrinityCore/AzerothCore
   revisions the change targets.
3. Never include production dumps, credentials, account data, character data,
   generated reports, or other private server information.
4. Keep source and world schemas read-only in every test.

## Development setup

Clone this repository together with the core repositories described in
[the repository setup runbook](runbooks/repository-setup.md), then run:

```bash
tests/static-checks.sh
```

Database behavior must also be exercised against disposable MySQL 8 schemas.
For loader, sanitizer, or checkpoint changes, test:

- a clean end-to-end migration;
- a rerun/no-op;
- interruption and resume at the affected operation;
- exact target schema fingerprints and restored indexes;
- zero validation errors.

Never point test configuration at production schemas.

## Pull requests

Keep changes focused and include:

- the problem and safety implications;
- schema revisions and fixtures used;
- commands run and their outcomes;
- expected compatibility or migration behavior changes;
- documentation updates where operator behavior changes.

By contributing, you agree that your contribution is licensed under the GNU
General Public License, version 3 or any later version.
