# TrinityCore/AzerothCore database migrator

[![CI](https://github.com/peycho/trinitycore-azerothcore-db-migrator/actions/workflows/ci.yml/badge.svg)](https://github.com/peycho/trinitycore-azerothcore-db-migrator/actions/workflows/ci.yml)
[![License: GPL v3 or later](https://img.shields.io/badge/License-GPL_v3_or_later-blue.svg)](COPYING)

A standalone migration toolkit for moving one realm's auth and characters data
between reviewed TrinityCore 3.3.5 and AzerothCore revisions on the same MySQL
server. Both `tc-to-ac` and `ac-to-tc` build fresh native target schemas,
preserve compatible player data, archive reviewed unsupported data, and stop
on unsupported representations or validation errors. Source and world databases
remain unchanged by the migrator. The tested server baseline is MySQL 8.4.x.

**Start with the [step-by-step migration guide](runbooks/migration-guide.md).**
It covers staging setup, database roles, candidate approval, configuration,
every migration phase, reports, troubleshooting, resume, gameplay tests,
production cutover, and rollback in one place.

> [!CAUTION]
> Use verified backups and isolated staging databases. A misconfigured target
> can cause permanent data loss. The software is provided without warranty.

The current `tc335-acwotlk-v2` profile remains **UNREVIEWED** pending native-core
smoke tests and two production-sized isolated rehearsals. The guide explains
how to enable it in a separate persistent staging toolkit copy. The v1 profile
is historical and requires the corresponding older toolkit release.

## Documentation

| Document | Purpose |
| --- | --- |
| [Migration guide](runbooks/migration-guide.md) | Complete operator workflow; start here |
| [Source inspection and preparation](runbooks/source-preparation.md) | Read-only legacy-data audit and reviewed cleanup workflow |
| [Cleanup shell console](runbooks/cleanup-console.md) | One config, private sessions, talent/item plans, apply and exact restore |
| [Invalid talent cleanup](runbooks/talent-cleanup.md) | Generate exact-row archive, apply and restore SQL from an audit |
| [Migration behavior](runbooks/migration-behavior.md) | Data policies and semantic transforms |
| [Spell reconstruction](runbooks/spell-reconstruction.md) | Omitted ranks, specialization safety and gameplay checks |
| [v2 review record](runbooks/profile-v2-review.md) | Reviewed changes, limitations, acceptance evidence |
| [Development and tests](runbooks/development.md) | Static checks and disposable fixture rehearsals |
| [Compatibility maintenance](runbooks/compatibility-profiles.md) | Generating and reviewing future profiles |
| [Adding mappings](runbooks/adding-mappings.md) | Extending coverage for schema or semantic changes |
| [SQL execution model](sql/README.md) | Generated statements and control-schema internals |

The mapping registries under `mappings/<direction>/` explicitly cover copied,
transformed, target-owned, derived, archived, and blocked tables. Compatibility
profiles protect SQL and relevant core readers/writers; unrelated repository
changes can pass when protected content remains identical. The toolkit does
not modify either core's C++ sources.

## Contributing and support

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing changes. Reproducible
bugs belong in GitHub Issues; security-sensitive reports follow
[SECURITY.md](SECURITY.md). See [SUPPORT.md](SUPPORT.md) for support boundaries.
Keep production dumps, credentials, SRP6 material, generated reports, and
player/account information private.

## License

Licensed under the [GNU General Public License, version 3 or any later
version](COPYING). See [THIRD_PARTY.md](THIRD_PARTY.md) for upstream-project and
trademark information.
