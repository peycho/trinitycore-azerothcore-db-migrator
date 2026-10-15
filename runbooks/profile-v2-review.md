# Profile v2 review and acceptance record

Reviewed on 2026-10-12 against local clean checkouts. No remote fetch was used.

| Core | Previous reviewed revision | Candidate revision | Additional commits |
| --- | --- | --- | --- |
| TrinityCore 3.3.5 | `a1fca43764e9aa4048a9228bc267e751eb186fe9` | `92127cd6252edb96fbfa36540db0eba17d0031fa` | 78 |
| AzerothCore | `5bdaa898db6180f1121f8364f289447091f1975d` | `1cd97629ed6ef49f5c70dec39316846381d2e450` | 961 |

The table inventories remain TC auth 21 / characters 91 and AC auth 22 /
characters 108. All four protected manifests changed. Format 2 explicitly
protects the serializers and definitions for items and bags, corpses, mail, stored loot,
arena teams, guild banks, and RBAC in addition to existing coverage.

## Reviewed changes and dispositions

| Upstream change | Migrator disposition |
| --- | --- |
| TC username column grows to 64 characters; auth accepts longer packets | TC → AC checks both AC's 32-character column and its 17-byte authentication ceiling. Preserve credentials and report incompatible account IDs and lengths. |
| TC mail flags widen to unsigned 32-bit, with new flag meanings | TC → AC accepts only AC's defined mask `0x1f`; block all other bits. Validate retained flags exactly in both directions. |
| TC stored loot gains `(container_id,item_index)` primary key | AC → TC assigns consecutive indexes by original index, item ID, and payload; preserve duplicate rows and report changed slots. Reject multiple money rows and out-of-range payloads. |
| TC base refresh archives older updates | Retain native update ledgers and verify hashes before skipping already-applied updates. Never replay repairs after migration loading. |
| AC uptime gains `EndTime`, `ShutdownType`, `ExitCode`, `ShutdownReason` | TC → AC derives historical end times and records unknown outcomes. AC → TC archives the complete uptime table before copying common fields. |
| AC adds RBAC permission 945, `Command: account info` | Retain native target seeds. Exact binary permission-name mapping and scope checks remain mandatory; no inferred grants. |
| AC update removes pet relations without a pet; pet saving rewrites its spellbook | Audit and remove only target-side dangling pet aura/spell/cooldown rows; preserve retained pets and account for approved cleanup in validation. |
| AC character aura loading now skips empty caster GUIDs | Block those TC → AC rows before assembly and loading. |
| TC item query field order and corpse loading helpers change | Persisted named columns and serialized formats remain compatible. Protect readers explicitly and exercise serialized fields and guild-bank relations. |
| Channel handling, talent/spell saving, petitions, arena writes, and extended instance reset behavior change | Retain existing transforms; exercise changed consumers during native-core smoke tests. |

The new reports are `source-blockers.tsv`, containing IDs, lengths, flags, and
reasons without account names or credentials, and `loot-index-normalization.tsv`.
Existing orphan, cleanup, generated SQL, checkpoint, and archive reports remain
part of the evidence. Archives contain source data and must remain private.

## Upstream persistence limitation

At the candidate TC revision, `Player::_SaveMail` still narrows `m->checked` to
`uint8` before passing it to a 32-bit statement parameter. A changed mail can
lose high flag bits on save despite the widened schema and load reader.
This toolkit does not patch either core and cannot guarantee high-bit mail
persistence in that upstream code. Migrated AC mail uses its supported common
flags; native TC high-bit behavior must be tracked separately during smoke tests.

## Acceptance status

`PROFILE_APPROVAL=UNREVIEWED` remains mandatory until every release gate passes.

| Gate | Evidence |
| --- | --- |
| Static analysis and compatibility behavior | Passed locally on 2026-10-12: ShellCheck, C-locale inventories, expanded-reader guards, retired/unreviewed rejection, candidate reproducibility, and failed-DDL checks. |
| Disposable MySQL migrations and failure/resume checks | Passed locally on MySQL 8.4.10 with MySQL 8.0.46 client tools: both directions reached `READY`, including blocker boundaries, archive verification, duplicate payloads, pet cleanup, interruption/resume, restored indexes, exact serialized fields, reruns, and source/world immutability. |
| Native-core gameplay smoke tests | Pending: requires runnable cores, appropriate world databases, client/data assets, and representative accounts. |
| Two production-sized isolated rehearsals | Pending: requires restored production-sized snapshots and retained private reports. |

Earlier v2 fixture validation also passed on MySQL 8.0.46. CI and the current
automated rehearsal harness use the MySQL 8.4.x server baseline.

Reproduce the local checks using [Development and automated tests](development.md).
For production-clone staging acceptance, follow the [migration guide](migration-guide.md).
Record actual test versions
and outcomes in the change description. Database
`READY` means the migrated fixture data passed validation, not that release or
production cutover is approved. Keep the v1 files unchanged; use fresh targets
and a new run with this toolkit. Spell reconstruction now adds control-owned
input snapshots, expected rows and provenance; older runs require fresh targets
and a new control schema rather than resuming with changed toolkit content.

## Spell-state review amendment, 2026-10-14

TC's load-time predecessor reconstruction and dependent-save omission require
semantic spell reconstruction instead of stored-row copying. Inactive ranks
remain known; disabled rows require verified specialization ownership. Direct
talent selections, temporary talent spells and profession/riding effects have
separate policies. See [spell reconstruction](spell-reconstruction.md) for exact
inputs, blockers, reports, reverse behavior and gameplay acceptance.

The pins above remain unchanged. AC staging
`f089543d9dfb3aaba2615fbf9427ea3e54a346e3` matches the pinned AC SQL manifests
and all expanded protected spell/DBC/trainer/Spells-script inputs. The configured
local AC revision also matches these protected inputs. Unrelated raid script
changes are outside this protection boundary; revisions are recorded rather
than silently substituted. The expanded TC inputs match its pinned revision.

The amendment does not approve the release or certify existing staging data.
Existing migrated databases require a fresh migration; a repair after player
writes needs separate review. Native gameplay checks and production-sized
rehearsals remain outstanding for the changed toolkit identity.

Local amendment validation passed on 2026-10-14:

- ShellCheck, documentation links, registry inventories, expanded-reader drift
  guards, metadata/profile reproducibility, unreviewed/retired rejection and
  schema-dump failure checks.
- Eleven focused semantic tests covering highest-only/complete/overlapping
  chains, masks in both groups, inactive/disabled states, direct talent ranks,
  temporary dependencies, profession/riding caps, malformed/cyclic/incompatible
  metadata, additive TC overlays and reverse semantic round trips.
- Dedicated disposable MySQL 8.4.10 bidirectional rehearsals reached `READY`
  with zero validation errors, including exact reconstructed sets, committed
  ownership/provenance, real paladin/priest/warlock rank IDs, skill preservation,
  SQL rollback, interruptions before/after spell commit, resume, completed reruns,
  source/world fingerprints, same-count input drift and unrelated-data checks.
- The protected AC trainer-state function was compiled in an isolated harness
  with mocked getters and exercised against migrated direct/wrapped spell rows
  in both specializations. This is consumer verification, not native gameplay.
- Read-only supplied WDBC assets matched the pinned layouts. With stock AC
  rank metadata and synthetic class skills, the example paladin anchors produced
  27 known ranks; tested priest and warlock ordinary chains produced 26 and 23.

Native trainer/casting/spec/persistence and profession gameplay checks are
**NOT TESTED** for this amendment. Two production-sized isolated rehearsals
also remain pending. These local checks do not change approval status.

## Preflight blocker review amendment, 2026-10-15

Ordinary spell prerequisites now recognize verified predecessor ranks that TC
restores from a stored higher rank. The stock druid example is Challenging Roar
`5209`, which requires Bear Form `5487`, while TC can persist only Dire Bear Form
`9634`. This does not authorize absent talents, unknown prerequisites or higher
ranks above the stored anchor.

The native `spell_murmur_sonic_boom_effect` script was reviewed in
`src/server/scripts/Outland/Auchindoun/ShadowLabyrinth/boss_murmur.cpp` for both
cores. It only adjusts hit damage and has no spellbook mutation or learned-spell
dependency. TC uses maximum health and AC current health for the damage amount;
the migration preserves the stored spell ID, not identical combat calculations.
The complete file is now protected in each semantic manifest and metadata input
hash; only this named encounter handler is added to the reviewed script policy.
The AC file is byte-identical at the pinned revision, staging `f089543d…` and
the configured checkout; TC's file matches its pin. Existing pins and
`PROFILE_APPROVAL=UNREVIEWED` remain unchanged.

The profile reader also follows named `RegisterSpellScriptWithArgs` aliases
and paired spell/aura registrations, preserving rejection if either handler
mutates the spellbook. This fixes the stock paladin Judgement aliases. Spell
and aura enum definitions are now protected inputs for correction evaluation;
deterministic effect-field copies are interpreted without executing C++.
The sampled Elemental Oath `51470`, Aspect of the Viper `34074` and Improved
Demonic Tactics `54349` corrections can therefore be applied instead of
blocked as unknown expressions. Conditional and unsupported expressions keep
their guards. The newly protected headers, including AC's registration loader,
match the pinned, staging and configured revisions byte for byte.

Native invalid talent selections and disabled unowned talent rows remain
separate blockers. No archive override, guessed rank mapping, talent deletion
or staging repair is introduced. Console diagnostics show grouped blocker
counts and the report path. Installing this amendment requires a fresh toolkit
copy and run identity with new target/control schemas.

Local validation for this amendment passed on 2026-10-15: static analysis,
profile reproducibility/drift checks, 18 focused unit regressions and the full
disposable MySQL 8.4.10 bidirectional rehearsal, including rollback, interruption,
resume, completed reruns, trainer consumer checks and source/world immutability.
The historical algorithm failed the real-DBC druid prerequisite regression;
the amended reader passed that case plus the reviewed script, Judgement and
three correction examples using read-only supplied DBCs with declared synthetic
skills. These checks do not certify the reported staging character records.
Native gameplay checks remain **NOT TESTED** and production-sized acceptance
for the amended toolkit identity is still pending.
