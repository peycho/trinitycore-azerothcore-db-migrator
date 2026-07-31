# Core repository setup

The migration toolkit requires local Git checkouts of both projects. It reads
their SQL trees and verifies their pinned commits; it does not compile or modify
either project.

## Recommended sibling layout

```text
workspace/
├── trinitycore-to-azerothcore-db/
├── TrinityCore/
└── azerothcore-wotlk/
```

Create the core checkouts:

```bash
git clone --branch 3.3.5 https://github.com/TrinityCore/TrinityCore.git
git -C TrinityCore checkout a1fca43764

git clone https://github.com/azerothcore/azerothcore-wotlk.git
git -C azerothcore-wotlk checkout 5bdaa898d
```

With this layout, the example configuration defaults work unchanged:

```bash
TRINITYCORE_DIR=../TrinityCore
AZEROTHCORE_DIR=../azerothcore-wotlk
```

Relative paths in a migration configuration are resolved from the
`trinitycore-to-azerothcore-db` repository root. They are not resolved from the shell's
current directory.

## Separate locations

The repositories may be stored elsewhere. Use absolute paths:

```bash
TRINITYCORE_DIR=/srv/wow-sources/TrinityCore
AZEROTHCORE_DIR=/srv/wow-sources/azerothcore-wotlk
```

Before rehearsal or production, verify the checkouts:

```bash
git -C /srv/wow-sources/TrinityCore rev-parse --short=10 HEAD
git -C /srv/wow-sources/TrinityCore status --short -- sql
git -C /srv/wow-sources/azerothcore-wotlk rev-parse --short=9 HEAD
git -C /srv/wow-sources/azerothcore-wotlk status --short -- data/sql
```

The expected outputs are revisions `a1fca43764` and `5bdaa898d`, followed by no
status output for either SQL tree. Do not point production at a newer branch
tip without reviewing schema differences, updating mappings and validations,
pinning the new revisions, and completing a fresh populated rehearsal.

The live TrinityCore database remains the authoritative source for actual
production DDL and data. The TrinityCore checkout establishes the reviewed
schema baseline; it does not replace the preflight live-schema capture.
