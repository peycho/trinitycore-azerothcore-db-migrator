# Compatibility profile maintenance

Compatibility profiles replace exact Git-HEAD requirements. They approve the
auth/characters SQL inputs and the C++ readers/writers on which semantic
transforms depend. Actual Git revisions are still recorded in every run.

## Checking a checkout

Run this before provisioning databases:

```bash
bin/migrate.sh --config /secure/migration.env compatibility
```

All four protected components must be `PASS`. World SQL and unrelated C++
changes are intentionally outside the profile. A failure creates a companion
`*-diff.txt` identifying added, removed, and modified protected files. There is
no unverified-production override.

## Creating a review candidate

Generate outside the repository:

```bash
bin/generate-compatibility-profile.sh \
  /srv/src/TrinityCore \
  /srv/src/azerothcore-wotlk \
  tc335-acwotlk-v2 \
  /secure/profile-review
```

The generated `profile.env` is deliberately `UNREVIEWED` and cannot be selected
by the runner. Compare it with the previous profile and review every protected
SQL and C++ change. Update table mappings, explicit transforms, validation, and
fixtures wherever semantics changed.

After review, run populated migrations in both directions, interruption/resume
tests, target-core smoke tests, and two production-sized rehearsals. Only then
copy the candidate under `compatibility/`, set `PROFILE_APPROVAL=APPROVED`, add
it to the configuration documentation and CI, and retain the review evidence.

Never replace an existing profile in place: its manifests are part of run
identity. Add a new profile ID so historical reports remain reproducible.
