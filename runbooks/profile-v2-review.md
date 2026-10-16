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


## Spell blocker review amendment, 2026-10-16

The existing pins and **UNREVIEWED** approval remain unchanged. The additional
protected Teron file is byte-identical at AC pin `1cd97629...`, staging
`f089543d...` and configured checkout `cb3d99cd...`; TC matches `92127cd...`.
The already protected paladin/Murmur files also match those references.
Configured core checkouts and DBC assets were read-only; no existing staging,
production or world database was accessed. Database writes were confined to
synthetic fixtures on a dedicated disposable server.

This amendment resolves specific compatibility gaps exposed by operator reports:

- TC's reviewed legacy Seal of Corruption constructor alias follows its protected
  implementation with verified damage/aura arguments; other unresolved legacy
  aliases remain guarded. Mutation rejection still propagates to aliases.
- Explicitly reviewed Murmur Sonic Boom and Teron Shadow of Death handlers enter
  the script policy. The complete Teron file is added to both semantic manifests;
  unreviewed handlers in those files remain blocked.
- Constant indexed family-flag writes represent Ebon Plague's correction;
  conditional, dynamic, out-of-range and copied indexed expressions still block.
- An authorized hidden/passive temporary talent child may have an AC-only rank
  prefix if TC requires no predecessor. AC's native exact-child `_addSpell` call
  is the consumer contract. No target-only predecessor or persistent runtime row
  is granted. TC predecessor obligations, including Primal Fury, still block.

The observed worlds had no TC Fiery Payback chain but an AC `44440 -> 44441`
chain. Both had Primal Fury `16958 -> 16961`. TC also had inactive learns
`17002 -> 24867` and `24866 -> 24864`; this amendment does not invent an AC
ownership/dependency mapping for those rows. These observations are diagnostic
input, not new stock-world requirements baked into the profile.

Unowned talents, unsupported disabled/inactive state, skill mutations, persistent
teaching spells and unresolved dependencies remain blockers. The original block
policy is retained: no new archive override, skill grant, replacement talent or
blanket source cleanup. Reports now include rank prefixes and unowned talent
flags/family ownership to support exact subsequent review.

Use a fresh migration toolkit copy, target/control schemas and run after this
transform/profile change. Existing cleanup archives remain preserved; no repair
of already migrated targets is implied. Native gameplay and the two required
production-sized isolated rehearsals are still outstanding release gates.

Local validation passed on 2026-10-16:

- Static checks, profile reproduction/drift rejection and 79 unit tests,
  including 22 spell tests. Disabled unowned history and zero-mask inputs
  remain blocked; diagnostics exclude zero-mask entries from selected ownership.
- The complete rehearsal command exited successfully from a frozen toolkit copy
  on MySQL 8.4.10 with MySQL 8.0.46 client tools. Both directions reached `READY`;
  rollback, interruption/resume, completed reruns, exact spell provenance,
  trainer checks, malformed/cyclic inputs, same-count drift, restored indexes
  and source/world/unrelated-data preservation passed. The preparation audit,
  talent cleanup/reset and 15 console check groups also passed.
- The protected AC talent consumer compiled with a recording spell-add sink
  verified exact Fiery Payback children, temporary flags and additional-talent
  exclusions. This verifies delegation only, not `_addSpell` effects or gameplay.
- Read-only supplied DBC checks with the observed world rank/learn rows accepted
  Fiery Payback in either spec without granting `44440` from `44441`, applied
  Ebon Plague's family correction and retained Primal Fury/Feral Swiftness blocks.
  Other world relationships/overlays were empty in this focused check; it does
  not certify the complete operator worlds or character records.

Staging gameplay acceptance for this amendment:

| Check | Result |
| --- | --- |
| Paladin/priest/warlock rank audit and trainer visits; trained predecessors learned and untrained higher ranks available | NOT TESTED |
| Cast representative highest and supported lower ranks | NOT TESTED |
| Switch both specs and relog in each; verify talent ownership and availability | NOT TESTED |
| Compare talent points, profession slots, recipes, riding tier, skill values and caps | NOT TESTED |
| Save, relog and restart AC; repeat checks and inspect spell-deletion/skill-correction logs | NOT TESTED |

## Research and talent-child follow-up, 2026-10-16

`spell-state-v2` uses the complete talent learn catalog to classify dependent
spells before considering a character's selected ownership. This closes an
ordinary-mask fallthrough for unselected hidden/passive talent children. It
adds no ownership and continues blocking disabled unowned history. Pet-target
teaching is excluded from player authorization. Missing ordinary prerequisites
now report `MISSING_SPELL_PREREQUISITE`; research without its existing profession
reports `RESEARCH_SKILL_MISSING`. Rank mismatch evidence includes stored flags
and selected learned-spell owners.

The earlier analysis relating `12296` to selected `12308` was incorrect:
Talent.dbc has talent 137 containing only `12296`, while talent 146 contains
`12308`, `12810`, `12811`. Their ownership is separate. Fiery Payback fixtures
also incorrectly used `64356`/`64348` for rank one; they now use actual talent
`64353`, learning `44440` and `64350`. Rank two remains `64357`, learning
`44441` and `64349`. Tests retain both active/inactive-spec ownership and
unselected disabled-history boundaries. These corrections do not change the
source character's selections or grant historical children.

The protected generic script files match the retained TC/AC pins and AC staging
`f089543d...` byte for byte. The reviewed profession research handler mutates
recipes when cast. It is not relabeled as non-mutating. A separate contract
accepts only existing research spells `60893`, `61177`, `61288` with exact
`[157,77,0]` effects and the matching existing Alchemy/Inscription skill. Both
native loader cast branches leave these spells uncast; migration derives no
recipes or skill changes. Unknown attached IDs, passive/stance variants and
teaching/effect changes remain blocked. TC/AC future research outcomes differ
as documented in the spell runbook; this change preserves the current known
recipe set. Profiles and native C++ remain otherwise unchanged.

Profile approval remains **UNREVIEWED**. Changed policy/profile/toolkit hashes
require a fresh migration toolkit, target/control schemas and run. Existing
staging/production databases and source cleanup archives are not repaired.
All five staging gameplay acceptance checks above remain **NOT TESTED**. Add
research login/relog recipe preservation and a representative native AC research
cast to staging checks. Production-sized acceptance remains pending.

The operator's actual worlds confirm an AC-only requirement `779 -> 5487`,
with no TC requirement for `779`. The ordinary-prerequisite diagnostic now
identifies that boundary without calling it a corrupt talent or granting Bear
Form. The conservative block remains. Source review also rejects a blanket
zero-mask repair for temporary children: AC's existing-row `_addSpell` branch
does not change their persistent state to temporary, and its temporary-only
removal then retains them. No historical rows are activated or removed here.

Follow-up validation passed with the final implementation: 81 unit tests,
ShellCheck and static/profile checks, and the complete disposable MySQL 8.4.10
bidirectional rehearsal. Forward/reverse validation, interruption/resume,
reruns, rollback, malformed relationships, same-count drift and unrelated-data
preservation passed. The cleanup rehearsal also passed 21 invalid-talent,
21 pending-reset and 15 console check groups. All 87 frozen runtime/profile/test
files matched the implementation after the final rehearsal.

The isolated C++ harness compiled protected native loader cast branches and
verified that all three research spells remain uncast during loading, with
passive/stance/skill-step positive controls. The corrected protected AC talent
consumer also passed its mocked-state checks. These checks do not execute a
worldserver or certify gameplay. Read-only checks against the supplied DBCs
confirmed the corrected talent identities and AC-only prerequisite diagnostic;
their limited world fixtures do not certify the full operator databases.

## Shared Dual Wield ownership correction, 2026-10-16

The complete talent-child catalog introduced a false blocker for ordinary
Dual Wield (`674`): shaman talent `30798` teaches it, but its ordinary skill
route also covers warriors, hunters, rogues and death knights. In the supplied
TC and AC DBCs, ability row `610` maps skill `118` to `674`, class mask `109`,
acquisition method `2`. Race/class skill rows `131`, `132`, `913` authorize the
ordinary classes; the shaman row `883` has the not-trainable flag and the talent
owner's class mask is `64`.

`spell-state-v3` recognizes matching native skill rewards in both effective
catalogs only when the character has no applicable or unknown talent owner and
the explicit class/race skill route is trainable. It preserves reached known
spells without granting arbitrary skill rewards. Skill values/caps and disabled
state checks still apply; no skill is inserted or repaired. Provenance records
the native row IDs, skill, acquisition method, threshold and flags. Shamans keep
selected talent masks; unowned hidden children remain blocked. This is a
converter correction, not a reason to remove ordinary Dual Wield from sources.

The protected native `Player.cpp` and `DBCEnums.h` files match the retained TC
and AC pins and AC staging `f089543d...` byte for byte. The pins and v1
profile remain unchanged. Nurturing Instinct's AC script really mutates the
spellbook on aura application/removal and stays blocked pending a separate
runtime ownership review. Missing ordinary prerequisites, unowned disabled
history and other unsupported representations are not cleared by this fix.

The cleaned source and cleanup archives remain usable. A new toolkit,
target/control schemas and run are required by the changed policy hash.
Profile approval remains **UNREVIEWED**; the five staging gameplay checks and
research gameplay check remain **NOT TESTED**.

The same review adds only TC's `spell_chapter1_runeforging_credit` to the
reviewed script inventory. Its complete `ScarletEnclave/chapter1.cpp` file is
now protected in v2 and matches retained TC `92127cd...` byte for byte. AC has
no equivalent script registration in this inventory; no cross-core alias is
invented. The TC handler casts `54586` only for incomplete quest `12842`.
The supplied DBCs make that spell a quest-completion effect (`16`), not a
spell-learning effect. The Runeforging spells themselves are non-passive
item-enchantment/dummy effects (`53,3,0`), so neither native loader casts them.
The converter preserves only known enchantments, adds no enchantments or quest
credit, and still requires the existing Runeforging skill. Other chapter
handlers and Nurturing Instinct remain unreviewed/blocked. The v2 manifest now
contains 96 TC semantic files; AC remains at 97. Release approval is unchanged.

Runeforging additionally requires existing value/cap `1/1` and compatible mono
range metadata. Both native skill loaders normalize that skill to `1/1`, so
nonstandard stored values/caps now block rather than relying on correction.
Fixtures use the actual recipe acquisition methods and `510/500` trivial-skill
fields. Focused read-only checks with the actual supplied DBCs verified all ten
normal enchantments and rejected three nonstandard skill states per enchantment
(40 checks). This is separate from a complete worldserver loading test.

Final validation passed: 84 unit tests, ShellCheck, profile/schema checks and the
complete disposable MySQL 8.4.10 bidirectional rehearsal, including the strict
Runeforging guard and actual recipe acquisition/trivial-skill fields. Both
directions reached database validation and passed interruption/resume, reruns,
rollback, malformed/cyclic relationship and same-count input-drift checks.
Read-only source/world and unrelated-data preservation checks passed. The
preparation suites retained their 21 invalid-talent, 21 pending-reset and 15
console check groups. All 88 final frozen runtime/profile/test files matched
the working implementation; the supplied DBC assets remained unchanged.

Isolated compiled native skill-reward consumers and the AC trainer function
also passed Dual Wield class/race/acquisition and direct/wrapped trainer checks
with recording/mocked state. Loader and Runeforging quest-handler harnesses
passed separately. These are scoped behavioral checks, not full native player
loading or staging acceptance. Updated operator blocker counts remain untested;
the release/gameplay gates above are still pending.

## Native aura and skill review, 2026-10-16 (`spell-state-v4`)

This later amendment supersedes the earlier pending Nurturing Instinct review.
The operator's read-only worlds bind `-33872` to
`spell_dru_nurturing_instinct` in both cores and contain `47179 -> 47180` in
both rank tables. TC casts the exact helper aura; AC adds the exact helper
with mask `3`, update `false`, temporary `true`, then removes only temporary
spells on aura removal. The conversion records the selected owner's mask and
exact helper as `AURA` without persistent helper rows in either direction.
The shared helper rank chain does not establish learned predecessor ownership:
TC casts an aura here rather than learning a spell. The temporary-rank blockers
for genuinely learned Primal Fury and death-knight children remain unchanged.
Stored Nurturing helpers, differing bindings and incompatible effective
parent/helper shapes block explicitly. No zero-mask history policy is added.

The operator's TC world also confirms enabled dependencies from Runeforging
`53428` to `53341` and `53343`. Both supplied DBCs make these native skill `776`
rewards with acquisition method `1` and threshold `1`. With an existing skill
exactly `1/1`, matching eligible native relationships and a known parent, the
converter delegates these exact children as `SKILL` in both directions. TC
restores dependent spells and AC restores temporary spells from skill loading;
no persistent children, extra recipes, skill repairs or quest credit are added.
A stored child and an omitted child merge with recorded provenance. This does
not approve arbitrary world dependencies or riding upgrades.

The protected `spell_druid.cpp`, `Player.cpp`, `SpellMgr.cpp` and AC
`PlayerStorage.cpp` match the retained pins byte for byte; the AC files also
match staging `f089543d...`. Configured checkout revision differences therefore
do not silently replace the pins. Existing v2 manifests already protect these
consumers; no manifest expansion, pin replacement or v1 modification is needed.
Release approval remains **UNREVIEWED**. All five staging gameplay acceptance
checks, plus native Nurturing aura/form/spec and Runeforging checks, remain
**NOT TESTED**. Use fresh migration target/control schemas and a new run; keep
the cleaned source and its separate cleanup archives.

Final v4 validation passed: 86 unit tests, ShellCheck, profile reproducibility,
schema guards and the complete disposable MySQL 8.4.10 bidirectional rehearsal.
Both directions reached database `READY` with zero failed ERROR checks.
Interruption/resume, rollback, completed reruns, malformed/cyclic relationships,
same-count input drift and read-only source/world/unrelated-data preservation
passed. Final provenance checks cover two native aura helpers with distinct
spec masks and two skill rewards, including stored/derived overlap. Isolated
compiled protected aura handlers and skill loaders passed; 20 checks against
the supplied DBCs also passed and reproduced both previous-converter blockers.
All 90 frozen runtime/profile/test files matched the final implementation and
all 14 supplied DBC assets remained unchanged. These are fixture and consumer
results; operator preflight and native gameplay acceptance remain untested.
