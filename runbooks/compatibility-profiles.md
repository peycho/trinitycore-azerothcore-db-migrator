# Compatibility profile maintenance

Profiles approve protected auth/characters SQL and semantic readers/writers.
Actual Git revisions are recorded for each run; unrelated commits are accepted
when protected manifests match.

Format 2 expands explicit coverage to item, corpse, mail, stored-loot, arena,
guild-bank, and RBAC definitions. The generator writes format 2 only. The v1
profile remains unchanged as historical evidence and is rejected by this toolkit;
use the older toolkit release for v1 migrations.

## Checking a checkout

Before provisioning databases:

```bash
bin/migrate.sh --config /secure/migration.env compatibility
```

All four protected components must be `PASS`. An approved profile is required.
World SQL and unrelated C++ changes remain outside the profile. Mismatches
produce a companion `*-diff.txt`. There is no production approval override.

## Reviewing a candidate

Generate outside the repository, choosing a new profile ID for later revisions:

```bash
bin/generate-compatibility-profile.sh \
  /srv/src/TrinityCore \
  /srv/src/azerothcore-wotlk \
  tc335-acwotlk-v3 \
  /secure/profile-review
```

The candidate is `UNREVIEWED`. Review protected SQL, serialization, gameplay
meaning, and native reader behavior; update mappings, blockers, transforms,
validation, and fixtures as required. Record the full revisions and evidence.
Never replace an existing approved profile's manifests.

The checked-in [v2 candidate](profile-v2-review.md) remains unreviewed. Repository
checks and database rehearsals enable it only in fresh toolkit copies under
`/tmp`, using `tests/test-support.sh`. They never change checked-in approval.
Use the same explicit isolated-copy workflow for private native-core and
production-sized rehearsals: copy the toolkit outside its checkout, mark only
the copied candidate approved, configure absolute core paths, restored sources, and fresh isolated
targets, and retain reports privately. Never deploy that test copy as a release.

Release approval requires populated migrations in both directions,
interruption/resume tests, native-core smoke tests, and two production-sized
isolated rehearsals meeting the timing gates. Only after these pass, set the
checked-in candidate to `APPROVED`, retain the acceptance evidence, and rerun
checks against that final toolkit identity. Until then, example configurations
intentionally fail closed.

CI pins reviewed core revisions. When introducing a later profile, update those
pins together with its manifests and review evidence. The test entrypoints
accept `TRINITYCORE_DIR`, `AZEROTHCORE_DIR`, and `COMPATIBILITY_PROFILE` overrides;
all inventory sorting uses the C locale.
