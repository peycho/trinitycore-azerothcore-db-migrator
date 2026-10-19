# Migration behavior reference

For the operator procedure, use the [migration guide](migration-guide.md).
This reference describes the data policies and transformations implemented by
the selected mapping registries.

## Safety and execution model

- The source core must be stopped before `preflight` when `REQUIRE_QUIESCENT=1`.
- Source schemas are read-only. Use a MySQL account with `SELECT` on source and
  world, and DDL/DML privileges only on the designated target/control schemas.
- Target schemas must be absent or contain no base tables. The runner does not drop schemas.
- A source table-count snapshot and normalized DDL fingerprints prevent a run
  from silently continuing after source drift.
- Every table appears in the selected direction's auth or characters registry
  under `mappings/`.
- Target-core update ledgers and seed tables are retained.
- Large mappings are split on their leading numeric primary-key column.
  Target inserts and completed chunk checkpoints commit atomically.
- Non-unique secondary indexes on configured large tables may be deferred;
  their exact native DDL, order, hash, and rebuild state are retained.
- Source-existing orphan data is removed only from the fresh targets by the
  explicit, audited `sanitize-target` phase. Source schemas remain untouched.
- MySQL strict mode and explicit target column lists are used for all loads.
- Every MySQL client session is initialized to UTC so checkpoint and timing
  timestamps remain comparable when the server uses a local timezone.
- Validation must report `READY`; target-core application smoke tests remain a
  separate cutover gate.

## Semantic transformations

### TrinityCore to AzerothCore

- Auth credentials preserve SRP6 `salt` and `verifier` byte-for-byte;
  `session_key_auth` maps to `session_key`; unsupported Battle.net session data
  is excluded; online state is reset.
- Usernames must fit AzerothCore's database and its authserver's 17-byte
  packet limit. Mail flags outside its defined mask `0x1f` and character auras
  with empty caster GUIDs block preflight and loading.
- Historical uptime rows receive a derived end time and unknown shutdown
  outcome. An overflowing end time blocks migration.
- Auth `AccountID/SecurityLevel` maps to AzerothCore `id/gmlevel`.
- AzerothCore build information and RBAC definitions remain target-owned.
  Per-account TrinityCore RBAC overrides map to exactly one target permission
  by binary-equal name while preserving the grant and realm scope. Missing or
  ambiguous permission names and scopes outside `-1` or `REALM_ID` block the
  migration.
- Character online state is reset. New inn/talent bonus state is initialized
  to the values used by a newly constructed AzerothCore player. TrinityCore
  soft-deleted characters retain their deletion metadata while their `NULL`
  active name is converted to AzerothCore's empty-string representation.
- TrinityCore talent groups become AzerothCore bit masks; duplicate spells
  across both specs are collapsed with `BIT_OR`.
- Spell state is reconstructed from legitimate known anchors and verified
  lower-rank relationships. Ordinary eligible spells retain both spec bits;
  talent-based chains receive only their existing owners' specialization bits.
  Inactive superseded ranks remain known. Unexplained disabled/inactive states,
  incompatible chains and unsafe dependencies block migration. Direct talent
  ranks are never expanded; native talent/temporary spells are delegated to AC
  where appropriate. Reviewed Nurturing Instinct helpers remain native transient
  state; verified Runeforging dependencies are delegated to existing native skill
  rewards. Both dispositions are reported and emit no persistent spell rows in
  either direction. Profession/riding transforms must preserve existing skills.
  The reviewed TC Flight Form world edge can also restore persistent Expert
  Riding and its known prefix, only when existing riding values/caps already
  support them; it never grants Artisan Riding from a form. See
  [spell reconstruction](spell-reconstruction.md) for the precise policy. Four
  explicitly reviewed passive talent families use AC's native exact temporary
  child representation; superseded TC internal passive entries are recorded in
  provenance rather than persisted in AC. Ordinary trained ranks and selected
  talent ownership retain their existing rules.
  A reviewed hidden dual-spec teacher `63680` is normalized to its two verified
  TC-known switch buttons only with existing dual-spec ownership and Generic
  skill. The original wrapper row is retained in control/report provenance as
  `TEACHER`; no teaching or spec-count effect is executed. Reverse conversion
  preserves buttons without inventing an absent wrapper. Other teaching spells
  remain blocked; see the [exact contract](spell-reconstruction.md#dual-spec-teaching-wrapper-spell-state-v10).
  Ordinary training prerequisites do not erase source-known ordinary spells.
  Under `spell-state-v11`, those rows retain mask 3 and record any missing
  ordinary parents without granting them. Talent-linked requirements continue
  to constrain selected spec ownership. See the
  [ordinary training contract](spell-reconstruction.md#ordinary-training-prerequisites-spell-state-v11).
- Cooldown category/end fields are consolidated with the later expiration time.
- Instance extension enum value `EXTENDED` becomes the target boolean.
- Item and money loot tables merge into `item_loot_storage`; money is stored as
  `itemid=0`.
- Battleground return data becomes `character_entry_point`.
- Channel IDs are assigned deterministically and the serialized ban list is
  normalized into `channels_bans`.
- Petition GUIDs seed the new petition IDs.
- Transient respawns are intentionally reset, consistent with AzerothCore's
  respawn schema transition.

### AzerothCore to TrinityCore

- Auth SRP6 bytes and the auth session key are preserved; Battle.net session
  state and runtime online state start empty.
- Account access and per-account RBAC overrides map through target column names
  and binary-equal target permission names.
- Talent spec masks expand into TrinityCore talent-group rows.
- Consolidated item loot splits into item and money tables; multiple money rows
  for one container block migration.
- Non-money loot receives consecutive deterministic indexes per container,
  preserving duplicate payloads and reporting changed indexes.
- Full uptime history is archived before copying its common columns so
  AzerothCore-only shutdown metadata remains recoverable.
- Channel bans serialize deterministically into TrinityCore's banned list.
- Entry points, instance-extension state, petitions, arena ratings, surveys,
  spell state, and cooldown state use explicit target-reader-compatible fields.
- Spell conversion preserves reconstructed ordinary chains and derives enabled/
  disabled talent-based state from the active group and unchanged talent owners.
  Only the active selected direct talent rank is stored in TC's spellbook;
  alternate selections remain in `character_talent`. Unrepresentable masks block.
- Creature and gameobject respawns merge with TrinityCore spawn types `0` and
  `1`.
- AzerothCore-only data is archived before it is omitted. The reverse path is
  semantically compatible, not a byte-for-byte reconstruction of historical
  TrinityCore fields that were previously discarded.

See the CSV registries for every copied, seeded, empty, derived, archived, and
blocked table.

The two TrinityCore auth administration views (`vw_log_history` and `vw_rbac`)
are catalogued as source-only objects. Any other live view, routine, trigger,
or event blocks preflight until added to the direction's `objects.csv` registry.

The SQL execution details are documented in [sql/README.md](../sql/README.md).
