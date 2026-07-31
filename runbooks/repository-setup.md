# Core repository setup

The migration toolkit requires local Git checkouts of both projects. It checks
their protected SQL and reader content against a reviewed compatibility
profile, records the actual Git revisions, and does not compile or modify either
project.

## Recommended sibling layout

```text
workspace/
├── trinitycore-azerothcore-db-migrator/
├── TrinityCore/
└── azerothcore-wotlk/
```

Create the core checkouts:

```bash
git clone --branch 3.3.5 https://github.com/TrinityCore/TrinityCore.git

git clone https://github.com/azerothcore/azerothcore-wotlk.git
```

With this layout, the example configuration defaults work unchanged:

```bash
TRINITYCORE_DIR=../TrinityCore
AZEROTHCORE_DIR=../azerothcore-wotlk
```

Relative paths in a migration configuration are resolved from the
`trinitycore-azerothcore-db-migrator` repository root. They are not resolved
from the shell's
current directory.

## Separate locations

The repositories may be stored elsewhere. Use absolute paths:

```bash
TRINITYCORE_DIR=/srv/wow-sources/TrinityCore
AZEROTHCORE_DIR=/srv/wow-sources/azerothcore-wotlk
```

Before rehearsal or production, verify the checkouts:

```bash
bin/migrate.sh --config /secure/migration.env compatibility
```

All protected components must report `PASS`. A newer or forked revision is
acceptable when its protected content is identical. Any mismatch requires the
compatibility-profile review workflow and a fresh populated rehearsal; there
is no production override.

The live TrinityCore database remains the authoritative source for actual
production DDL and data. The TrinityCore checkout establishes the reviewed
schema baseline; it does not replace the preflight live-schema capture.
