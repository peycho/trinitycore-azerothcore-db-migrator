# Spell reconstruction reason codes

These uppercase strings are operator-facing diagnostic codes, not temporary
debug messages. They appear in saved reports and identify the check that stopped
conversion. Keep the exact code when reporting a problem. This reference covers
the current spell metadata reader and reconstruction engine in `lib/spells.py`;
general source-audit, cleanup-console and validation checks have separate codes.

Codes identify categories; the `detail` field identifies the actual spell,
relationship, flags or metadata mismatch. Interpret them with the toolkit and
profile that produced the report. New policies may add codes or make previously
blocked cases supported. The spelling of a code alone does not establish that a
case is corrupt, fixed or safe to delete. The detail text is diagnostic prose,
not a stable machine-readable interface.

## Reading a failure

`spell-state-blockers.tsv` has `guid`, `spell`, `reason_code` and `detail`
columns. Currently the engine writes `*` in `spell`; obtain the relevant spell
IDs from `detail`. It records the first failure per character, so fixing one
failure may expose another. Summary counts are affected characters, not the
total number of invalid spell rows. Metadata initialization failures may stop
the scan before all characters have been inspected.

`spell-metadata-errors.tsv` records database read failures separately, with
`input`, `reason_code` and `detail`. These failures do not establish character
spell incompatibility. `spell-script-review.json` can also contain the script
and metadata reason codes below, independently of character ownership.

Before rerunning preflight, retain the complete reports and inspect the named
source rows, both talent groups and effective world/DBC relationships. Use the
[saved blocker context command](cleanup-console.md#review-a-saved-migration-blocker-report)
when appropriate. Do not resolve a code by blindly deleting spells, enabling
disabled rows, adding skills, granting trainer spells or changing talent ownership.
Reviewed source preparation and converter changes are separate remedies. Source
or toolkit changes require a new migration run as described in the
[migration guide](migration-guide.md#7-run-preflight-and-inspect-the-source-audit).

## Temporary ranked talent spells

### `UNSUPPORTED_TEMPORARY_RANK_CHAIN`

A selected talent grants a runtime-owned child spell, and TC knows preceding
ranks of that child, but no reviewed native-passive contract authorizes its AC
representation. The spell ID in `detail` is the internal child, which may differ
from the selected talent's spell ID. This is not the ordinary highest-trained-
rank problem and is not proof of an invalid talent record.

Here, **temporary means owned by the talent/spec lifecycle**, not a timed spell
or a short-lived error code. TC can reconstruct lower internal passive entries;
AC can keep only the exact selected child temporarily and omit it from saved
spell rows. Persisting every internal rank could outlive the talent or produce
incorrect specialization behavior.

The policy introduced in `spell-state-v6` and retained in `spell-state-v9`
supports the reviewed Primal Fury, Will of the Necropolis, On a Pale Horse and
Blood Gorged families. It preserves exact selected talents and spec ownership,
delegates the selected passive child to AC, and does not persist superseded
lower passive ranks. Ordinary trained lower ranks are still reconstructed.
See the [native-passive contract](spell-reconstruction.md#reviewed-native-passive-talent-ranks)
for restrictions, provenance, reverse migration and acceptance checks.

This code was **not renamed or removed** when those cases became supported.
It remains a guard for unsupported chains. `UNEXPECTED_TEMPORARY_RANK_CHAIN`
is not a code emitted by the current engine. A reviewed family whose metadata
fails its contract instead reports `UNSUPPORTED_NATIVE_PASSIVE_RANK`; that is a
distinct failure, not a cosmetic replacement. Review the child, selected owner,
both cores' chains and native runtime behavior before extending support.

## Talent ownership and stored availability

| Code | Meaning and next evidence to inspect |
| --- | --- |
| `INVALID_SPELL_CHARACTER_STATE` | Race/class is outside the supported numeric domain, talent-group count is not one or two, or the active group is unavailable. Inspect character state first. |
| `INVALID_TALENT_OWNERSHIP` | A selected value is not the same valid talent rank in both catalogs, is ineligible for the class, or has an invalid group mask. Inspect `character_talent` and talent/tab metadata; never infer a replacement rank from a talent entry ID. |
| `CONFLICTING_TALENT_RANKS` | More than one rank of the same talent is selected in one specialization. Review the full selected family. |
| `UNAUTHORIZED_TALENT_SPELL` | No verified specialization authorizes the stored/reached spell. Inspect flags, selected ranks, learned children and prerequisites. Disabled history and enabled unowned spells require different reviews. |
| `MISSING_SPELL_PREREQUISITE` | An ordinary spell's required spell is absent from the verified known state, including reconstructable predecessor ranks. Inspect both worlds' requirements and known anchors; do not grant the prerequisite merely to pass. |
| `INVALID_TC_SPELL_FLAGS` | A TC `active` or `disabled` value is outside zero/one. Inspect the exact stored row. |
| `UNREPRESENTABLE_DISABLED_SPELL` | TC disabled state is not explained by verified ownership in an inactive spec. Converting it to an ordinary both-spec spell would be unsafe. |
| `TC_SPELL_OWNERSHIP_CONFLICT` | An enabled TC spell is not authorized in the active specialization. Compare active group, talent ownership and stored flags. |
| `UNREPRESENTABLE_INACTIVE_SPELL` | TC inactivity cannot be explained safely by supported supersession or the reviewed selected passive/hidden talent representation. Inspect higher ranks and flags. |
| `UNREPRESENTABLE_AC_SPELL_MASK` | An AC mask is empty, uses unsupported bits, or differs from reconstructed eligibility. Review both specs before reverse conversion. |

## Rank and dependency representations

| Code | Meaning and next evidence to inspect |
| --- | --- |
| `INCOMPATIBLE_SPELL_CHAIN` | The reached TC/AC predecessor prefixes differ outside the reviewed runtime exception. Compare both effective chains and the anchor; never substitute a target chain blindly. |
| `INCOMPATIBLE_TALENT_CLASSIFICATION` | The reached ID is a direct talent in only one core. Compare effective talent catalogs. |
| `INCOMPATIBLE_SPELL_VISIBILITY` | Passive/hidden flags differ between cores. Review their effect on native loading and availability. |
| `INCOMPATIBLE_TALENT_LEARN_EFFECT` | A selected talent teaches different child IDs in the two cores. Compare its effective learn effects. |
| `UNSUPPORTED_TEMPORARY_LEARN_EFFECT` | A runtime child mixes a learn effect with other effect types. Its native lifecycle has no safe supported interpretation. |
| `UNSUPPORTED_NATIVE_PASSIVE_RANK` | A family with an explicit native-passive rule fails its class, owner, chain, effect, visibility, teacher, skill, prerequisite or trainer exclusions. `detail` names the failed contract. |
| `UNSUPPORTED_AURA_HELPER_SPELL_ROW` | A native aura/temporary helper is stored as a persistent player spell. Review the exact helper row separately from the owning talent. |
| `UNSUPPORTED_TALENT_AURA_SCRIPT` | A recognized talent-aura script's parent/helper effects, visibility, gates or rank identity differ from its reviewed rule. |
| `INCOMPATIBLE_TALENT_AURA_SCRIPT` | TC/AC aura-script bindings or helper predecessor chains differ. Compare both effective bindings and chains. |
| `INCOMPATIBLE_WORLD_TALENT_AURA` | A reviewed TC world-helper/AC native-aura mapping fails its class, exact rank, inactive learn edge, script/form binding, effect, stance or excluded-route contract. Compare the named parent/helper and both effective catalogs; do not persist the helper to bypass the failure. |
| `UNSUPPORTED_DEPENDENT_LEARN` | TC would restore a learned child without a verified compatible native AC dependency or reviewed persistent mapping. Inspect parent/child and active/auto-learn metadata. |
| `UNREPRESENTABLE_INACTIVE_DEPENDENCY` | A learned child is inactive in TC, but the reviewed representation cannot preserve that availability in AC. |
| `CONDITIONAL_DEPENDENT_LEARN` | A dependency reached through spell effects has stance/aura-state conditions that prevent unconditional reconstruction. |
| `UNSUPPORTED_PERSISTENT_LEARN_EFFECT` | A spell selected for persistent storage itself contains a learn effect. Safe load-time teaching and side effects have not been established. |
| `CONFLICTING_SPELL_REPRESENTATION` | Independent paths assign incompatible persistent/runtime dispositions to the same spell. Review all derivations; mask merging alone cannot resolve it. |

## Skills, professions and riding

| Code | Meaning and next evidence to inspect |
| --- | --- |
| `AC_WOULD_DELETE_SPELL` | AC has skill-ability entries for the spell but no eligible race/class skill metadata for this character. Inspect class/race eligibility and spell provenance. |
| `SPELL_WOULD_ADD_SKILL` | Native loading or learning would create a skill absent from the source character. Inspect existing skills and the spell/dependency that would add it. |
| `SPELL_WOULD_CHANGE_SKILL` | Native effects require raising skill values/caps, or a reviewed exact riding/Runeforging state is not met. Inspect the reported skill, values, cap and known tier anchors. |
| `RESEARCH_SKILL_MISSING` | A reviewed profession research spell lacks its required existing positive skill value/cap. No profession or recipes are inferred. |
| `INCOMPATIBLE_SKILL_EFFECT` | Effective TC/AC skill effects differ. Compare the spell effects before considering a mapping. |
| `INCOMPATIBLE_SKILL_METADATA` | Skill category, race/class flags, tier data or reviewed Runeforging layout differs or is unsupported. Inspect both effective catalogs. |
| `SPELL_SKILL_NOT_ELIGIBLE` | A spell's skill effect lacks eligible race/class metadata in one or both cores. |
| `MISSING_SKILL_TIER` | Referenced target skill-tier metadata is absent. Verify the assets and database overlays. |
| `NONDETERMINISTIC_SKILL_EFFECT` | The skill effect uses a die-side representation outside the deterministic forms understood by the reader. Review the effect instead of guessing a value. |
| `UNSUPPORTED_SKILL_STEP_SPELL` | The spell contains a skill-step effect without a supported preservation contract. It may affect profession tiers or accounting. |

## Metadata, scripts and traversal

| Code | Meaning and next evidence to inspect |
| --- | --- |
| `MISSING_SPELL_METADATA_INPUT` | Both read-only worlds and both core-specific DBC directories are required but not configured. |
| `MISSING_SPELL_METADATA_TABLE` | A required world metadata base table is absent. Check schema names and required exports. |
| `MISSING_DBC` | A required DBC file could not be read. Check path, file presence and permissions. |
| `INVALID_DBC` | WDBC layout, length, record IDs or string offsets are invalid for the pinned reader. Verify the supplied asset; do not modify offsets to bypass the check. |
| `INCOMPATIBLE_DBC_OVERLAY` | Database overlay columns/width do not match the pinned core reader. Check the actual world schema and profile compatibility. |
| `TC_DBC_OVERLAY_COLLISION` | A TC custom `spell_dbc` row replaces an ID already in `Spell.dbc`, violating TC's additive overlay rule. |
| `UNKNOWN_SPELL_ID` | A reached spell is missing from an effective catalog. Check both assets, overlays and source provenance. |
| `MISSING_CHAIN_SPELL` | A rank chain refers to a spell missing from its effective catalog. |
| `MALFORMED_SPELL_CHAIN` | World ranks are not contiguous from one, exceed the unsigned rank domain, or disagree with first-rank identity. |
| `CONFLICTING_SPELL_CHAINS` | A spell belongs to conflicting rank sequences. Compare world and talent-derived chain definitions. |
| `MALFORMED_TALENT_CHAIN` | A reached talent has gaps, missing spell IDs or ambiguous/shared rank membership unsupported for player ownership. |
| `INVALID_SPELL_REQUIREMENT` | A requirement references a missing spell or links spells in the same rank family. Inspect `spell_required`. |
| `INVALID_LEARNED_SPELL` | A TC world learn relationship references missing IDs, teaches a direct talent, or has an invalid active flag. Inspect `spell_learn_spell`. |
| `INVALID_TRAINER_SPELL_METADATA` | A target trainer spell ID is not an integer in the unsigned domain. Trainer data is exclusion evidence, never a grant source. |
| `CUSTOM_TALENT_CLASSIFICATION` | TC custom attributes classify a spell as a talent without matching verified talent ownership metadata. |
| `UNSUPPORTED_CORE_CORRECTION` | A pinned C++ spell correction affecting relevant semantics lacks a verified interpretation in the metadata reader. Inspect the named core, spell and field. |
| `UNSUPPORTED_LEARNING_SCRIPT` | A binding is unreviewed, may alter spellbook state, or fails a reviewed cast-only research contract. Inspect the complete binding inventory and protected implementation; the script name alone does not prove corruption. |
| `CYCLIC_SPELL_RELATIONSHIP` | Reachable rank, learn or prerequisite relationships contain a cycle. Review the reported relationship graph. |
| `SPELL_TRAVERSAL_BOUND` | Traversal exceeded the catalog-derived safety bound. Preserve input fingerprints and investigate the graph/reader; do not increase the bound as a workaround. |
| `UNSUPPORTED_SPELL_PROFILE` | The metadata profile format version is unsupported by this toolkit. Use a compatible toolkit/profile pair. |
| `SPELL_METADATA_QUERY_FAILED` | MySQL could not complete a read. See `spell-metadata-errors.tsv` for the input and database error; check access, connectivity and server errors before interpreting spell state. |

Supporting a previously blocked representation requires reviewed compatibility
rules and relevant tests, not a code rename or report edit. Passing these checks
does not replace the [staging gameplay gates](spell-reconstruction.md#validation-and-staging-gameplay-gate).
Release approval remains **UNREVIEWED** until its acceptance gates pass.

`spell-state-v8` supports Feral Swiftness's exact `17002 -> 24867` and
`24866 -> 24864` inactive world edges through native AC selected-talent/form
auras. It does not rename or remove `UNSUPPORTED_DEPENDENT_LEARN` for other
relationships. See the [world-helper contract](spell-reconstruction.md#feral-swiftness-world-helpers).

`spell-state-v9` additionally supports Nurturing Instinct's exact inactive
`33872 -> 47179` and `33873 -> 47180` world edges, with TC-only known prefixes
and AC exact temporary helpers. Unexpected mechanics or incoming/outgoing
routes remain `INCOMPATIBLE_WORLD_TALENT_AURA`; stored helpers still report
`UNSUPPORTED_AURA_HELPER_SPELL_ROW`. See the
[ranked world-helper contract](spell-reconstruction.md#nurturing-instinct-world-helpers-spell-state-v9).
