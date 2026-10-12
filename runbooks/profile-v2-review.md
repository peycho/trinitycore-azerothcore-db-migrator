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

Reproduce the local checks with `tests/static-checks.sh` and the disposable
MySQL harness described in [Rehearsal](rehearsal.md). Record actual test versions
and outcomes in the change description. Database
`READY` means the migrated fixture data passed validation, not that release or
production cutover is approved. Keep the v1 files unchanged; use fresh targets
and a new run with this toolkit. The control-schema layout is unchanged.
