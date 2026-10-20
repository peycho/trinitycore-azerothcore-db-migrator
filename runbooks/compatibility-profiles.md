# Compatibility profile maintenance

Profiles approve protected auth/characters SQL and semantic readers/writers.
Actual Git revisions are recorded for each run; unrelated commits are accepted
when protected manifests match.

The [selected-talent ownership repair](talent-ownership-repair.md) is a separate
preparation policy. Its source-world/DBC and selector fingerprints do not approve
target compatibility or gameplay. It changes no core C++, existing pins,
protected manifests, migration reconstruction policy or release approval.

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

Native Death Coil preparation v3 uses the already protected TC/AC player,
storage, skill-level-update, script and DBC consumers. It adds no core revision,
protected file, metadata or migration-logic exception. The exact source skill
reward/chain and configuration contract are fingerprinted in its preparation
batch; skills and talents remain unchanged in SQL. Target overlays and gameplay
still require their own migration acceptance. See the
[rank-1 contract](cleanup-console.md#native-death-coil-rank-1-repair-ordinary-v3).

Ordinary-history preparation v2 additionally protects TC `World.cpp` for the
`PlayerStart.AllSpells` configuration gate. Its content matches retained pin
`92127cd...`; protected counts become 100 TC / 103 AC. AC pins, v1, spell-state-v12,
metadata and control-schema definitions remain unchanged. Profile hashes change,
requiring fresh migration runs and target/control schemas. The preparation
assertion is explicit, independently hashed and does not relax migration checks.
See [ordinary history v2](cleanup-console.md#inactive-custom-starting-spell-routes-ordinary-v2).

`spell-state-v12` recognizes the native inactive-spec gate for Shaman Dual Wield
without granting skill `118` or changing talent selections. The protected player,
skill-manager and storage consumers already cover this behavior. Metadata
profile, manifests, pins and v1 remain unchanged. Policy hashes require fresh
target/control schemas and a new run; approval remains UNREVIEWED. See the
[contract](spell-reconstruction.md#inactive-dual-wield-talent-spell-state-v12).

`spell-state-v11` separates ordinary training prerequisites from known-spell
loading and talent authorization. Protected TC/AC player and trainer consumers
already cover the behavior; no pins, manifests or v1 files change. The metadata
profile is unchanged, while policy/checkpoint identity changes. Ordinary known
rows retain both specs without granting missing parents; talent-linked ancestry
keeps the strict path. Use fresh target/control schemas and retain UNREVIEWED
approval. See the [contract](spell-reconstruction.md#ordinary-training-prerequisites-spell-state-v11).

`spell-state-v10` adds the exact dual-spec teaching-wrapper contract and control
disposition `TEACHER`. The two derived buttons must already be justified by TC's
load map and existing two-spec/skill state; no effect is executed. AC gossip and
spec-count consumers additionally protect `PlayerGossip.cpp`/`PlayerUpdates.cpp`.
Both files match the retained AC pin and supplied staging/configured refs byte
for byte. The protected counts are TC 99 and AC 103. Pins, v1 and UNREVIEWED
approval remain unchanged. Fresh target/control schemas are required; see the
[contract](spell-reconstruction.md#dual-spec-teaching-wrapper-spell-state-v10).

`spell-state-v9` adds the bounded Nurturing Instinct ranked world-helper
contract alongside the existing script-only representation. Existing protected
files cover its TC dependent/prefix restoration and AC temporary lifecycle;
no additional protected files or revision substitutions are needed. Exact
mechanics and routes are part of the generated metadata profile and checkpoint
identity. Pins and UNREVIEWED approval remain unchanged. See the
[Nurturing contract](spell-reconstruction.md#nurturing-instinct-world-helpers-spell-state-v9).

`spell-state-v8` adds only the bounded Feral Swiftness TC-world/AC-aura
representation contract. Both semantic manifests add `SpellAuraEffects.cpp`
for the native stance loops. Both configured files match the retained pins
byte for byte; v1, revision pins and UNREVIEWED approval remain unchanged.
This profile/policy change invalidates prior migration checkpoint identity.
Use fresh target/control schemas and retain old preparation toolkits for the
original guarded restoration of their batches. See the
[Feral Swiftness contract](spell-reconstruction.md#feral-swiftness-world-helpers).

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

The missing-native-skill preparation policy additionally protects both cores'
`Entities/Unit/Unit.h`, which supplies the reviewed level-times-five maximum.
The retained pins and v1 stay unchanged; the extra v2 manifest entries do not
grant release approval. Retain older cleanup toolkits with their old archives
for exact restoration under their original metadata contracts.
