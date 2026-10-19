# Compatibility profile maintenance

Profiles approve protected auth/characters SQL and semantic readers/writers.
Actual Git revisions are recorded for each run; unrelated commits are accepted
when protected manifests match.

Format 2 expands explicit coverage to item, corpse, mail, stored-loot, arena,
guild-bank, and RBAC definitions. The generator writes format 2 only. The v1
profile remains unchanged as historical evidence and is rejected by this toolkit;
use the older toolkit release for v1 migrations.

Operator setup, candidate staging approval, and compatibility checks are in
the [migration guide](migration-guide.md). This document covers maintainer
work when introducing a new reviewed baseline. General world SQL and unrelated
C++ changes remain outside the profile. Seven AC DBC overlay definition files
are protected because the spell-profile generator uses their ordered layouts.
Live spell metadata is separately fingerprinted for each run. There is no
production approval override.

The unapproved v2 spell metadata also contains a narrow persistent-world
dependency contract for Flight Form and existing Expert Riding. It requires
the actual TC learn edge, reviewed spell/rank/skill metadata and preserved riding
values/caps. The separate `spell-state-v6` native-passive contract explicitly
lists four talent families and seven chains, with unchanged ownership and skill
state. Both v2 manifests additionally protect `SpellAuras.cpp`; pinned revisions
remain unchanged. The metadata profile and policy change run/checkpoint identity. Earlier migration
runs need fresh target/control schemas. See [spell reconstruction](spell-reconstruction.md).

The `spell-state-v7` correction binds the persistent riding dependency to native
secondary skill category `9`, replacing an incorrect class-category assumption.
The generator and synthetic fixture agree with actual DBC/overlay data. Core
pins, protected-file manifests and approval remain unchanged. This metadata and
policy change also invalidates earlier run/checkpoint identities.

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
validation, and fixtures as required. The generated `spell-metadata.json`
contains WDBC layouts, additive/override reader rules, integer core corrections,
conservative unsupported-correction guards and native spell-script dispositions.
Correction operands can also copy a reviewed effect field. Protected spell/aura
enum definitions resolve constant operands. Script policy follows native named
registrations and pairs, and protects each explicitly reviewed encounter source.
Core-specific quest handlers are reviewed individually; v2 protects TC's
Scarlet Enclave chapter file and accepts only its Runeforging quest-credit
handler. It does not approve every script in that file or invent an AC alias.
Cast-only script contracts are separate from non-mutating classifications.
They bind reviewed IDs, exact effects and profession skills to verified native
loader behavior; they do not authorize running those scripts during migration.
Review these alongside the expanded spell/DBC/trainer readers. Record the full
revisions and evidence.
Never replace an existing approved profile's manifests.

The checked-in [v2 candidate](profile-v2-review.md) remains unreviewed. Use
[step 3 of the migration guide](migration-guide.md#3-prepare-the-persistent-staging-toolkit)
for manual candidate rehearsals and [development tests](development.md) for
disposable fixture checks. Both preserve checked-in approval.

Only after the [release acceptance gates](migration-guide.md#rehearsal-acceptance-and-release-approval)
pass, set the checked-in candidate to `APPROVED`, retain acceptance evidence,
and rerun checks against that final toolkit identity. Until then, example
configurations intentionally fail closed.

CI pins reviewed core revisions. When introducing a later profile, update those
pins together with its manifests and review evidence. The test entrypoints
accept `TRINITYCORE_DIR`, `AZEROTHCORE_DIR`, and `COMPATIBILITY_PROFILE` overrides;
all inventory sorting uses the C locale.
