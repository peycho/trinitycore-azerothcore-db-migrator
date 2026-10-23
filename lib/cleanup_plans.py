"""Generate exact-key cleanup packages from reviewed metadata and read-only state."""
from collections import defaultdict
import csv
import json
import re
import uuid

from cleanup_console import (ROOT, PROFILE, fail, identifier, local_id, load_module,
                             seal, sha, token, write_json)

planner=load_module('cleanup_talent_planner',ROOT/'tools/plan-talent-cleanup.py')


def snapshot(settings, queries):
    statements=['SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;',
                'START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;']
    for label,query in queries:
        # Each query returns a JSON array named row_value; SQL text is generated
        # internally from validated identifiers and numeric selectors only.
        statements.append("SELECT JSON_OBJECT('kind','"+label+"','value',row_value) FROM ("+query+") data_rows;")
    statements.append('ROLLBACK;')
    result=defaultdict(list)
    for line in settings.sql('\n'.join(statements)).splitlines():
        data=json.loads(line)
        result[data['kind']].append(data['value'])
    return result


def metadata(settings, tables):
    schema=settings.schemas['characters']
    names=','.join("'"+identifier(table)+"'" for table in tables)
    result=snapshot(settings,[('columns',f"SELECT JSON_ARRAY(TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY,EXTRA,GENERATION_EXPRESSION,ORDINAL_POSITION) row_value "
        f"FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}) ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION"),
        ('tables',f"SELECT JSON_ARRAY(TABLE_NAME,ENGINE,TABLE_TYPE) row_value FROM information_schema.TABLES "
         f"WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}) ORDER BY BINARY TABLE_NAME")])
    if sorted(result['tables'])!=sorted([[table,'InnoDB','BASE TABLE'] for table in tables]):
        fail('UNSUPPORTED_SCHEMA','Required native InnoDB source tables are missing')
    for row in result['columns']:
        identifier(row[1])
        if row[6] or 'INVISIBLE' in row[5] or re.search(r'(^| )(VIRTUAL|STORED) GENERATED( |$)',row[5]):
            fail('UNSUPPORTED_COLUMN',f'Computed/invisible source column needs separate review: {row[0]}.{row[1]}')
    return result


def require_shape(meta,table,fields,exact=False):
    actual={row[1]:(row[2],row[3],row[4]) for row in meta['columns'] if row[0]==table}
    if not set(fields)<=set(actual) or (exact and set(actual)!=set(fields)):
        fail('UNSUPPORTED_SCHEMA',f'{table} does not have the reviewed column shape')
    return actual


def equality(meta,table,left='s',right='a'):
    columns=[row[1] for row in meta['columns'] if row[0]==table]
    if not columns:
        fail('UNSUPPORTED_SCHEMA',f'No columns for {table}')
    return ' AND '.join(f'(BINARY {left}.`{column}` <=> BINARY {right}.`{column}`)' for column in columns)


def render(template,values):
    text=template.read_text()
    if 'NAME' in values:
        # Character names are data, never SQL syntax, including UTF-8 names.
        literal='CONVERT(0x'+str(values['NAME']).encode().hex()+' USING utf8mb4)'
        text=text.replace("'@NAME@'",literal)
    for key,value in values.items():
        text=text.replace('@'+key+'@',str(value))
    if re.search(r'@[A-Z_]+@',text):
        fail('UNEXPANDED_TEMPLATE','Cleanup template has unresolved values')
    return text


def ranks(settings):
    profile=json.loads((PROFILE/'spell-metadata.json').read_text())
    stores={}
    fingerprints={}
    for name in ('Spell','Talent','TalentTab'):
        path=settings.paths['tc_dbc']/(name+'.dbc')
        stores[name],_=planner.read_dbc(path,profile['stores'][name]['formats']['tc'])
        fingerprints[name+'.dbc']=sha(path)
    catalog=sorted({spell for row in stores['Talent'].values() for spell in row[4:9] if spell})
    if not catalog or len(catalog)>100000:
        fail('UNSUPPORTED_CATALOG','Talent rank catalog is empty or exceeds the reviewed bound')
    return stores,catalog,fingerprints


def readme(manifest):
    policy=manifest['policy']
    details={
        'tc-inactive-competing-specialization-retirement-v1':'Retire only inactive/non-disabled competitors to one retained enabled, verified specialization. This changes known-specialization eligibility; it does not choose or grant a specialty. Fixed stock specialization and ordinary-rank catalogs, coherent skill value/cap and proven prerequisites required. Unknown or affected equipped-item RequiredSpell values in either world defer, including custom items; equipment references, instances and both item-template layouts/requirements are checked at every phase. Stored recipes remain byte-for-byte present; no native unlearn cast or recipe purge occurs. Both builds, skills/caps, all items, active chosen specialty and login flags remain unchanged. Full custom originals, exact source/both-world/DBC/catalog/reader/equipment fingerprints, stopped-copy/custom-start-off assertions and explicit specialization acknowledgement apply; atomic DELETE/checkpoint, guarded reruns/rollback and exact inverse. Source needs DELETE/INSERT on character_spell only. Restore before login or later edits using original toolkit; fresh imports require fresh selections/archives. Full gameplay NOT TESTED; release approval UNREVIEWED.',
        'tc-inactive-ordinary-profession-activation-v1':'Explicitly activate existing ordinary crafting-rank rows only: active=0, disabled=0 becomes active=1, disabled=0. This deliberately makes already-known profession actions usable. Exact reviewed four-family catalog, a sole stored ordinary rank per family and existing compatible skill/cap required; no missing higher-rank inference, specialization activation, spell insertion/deletion, cast effects, recipes, skills/caps, talents, inventory or login changes. Pending resets and unsupported cases defer. Full custom originals, exact source/both-world/DBC/catalog/reader fingerprints, stopped-copy/custom-start-off assertions and profession activation acknowledgement apply. Atomic UPDATE(active), checkpoint, reruns, rollback and guarded exact inverse; source needs UPDATE(active), no INSERT/DELETE. Restore with original toolkit before native login or subsequent edits. Fresh imports require new evidence, selections and archives. Gameplay NOT TESTED; approval UNREVIEWED.',
        'tc-redundant-skill-teaching-wrapper-retirement-v1':'Explicitly retire only enabled redundant wrappers 1710, 5785, 19902 or 65286 under fixed reviewed mechanics. Every taught child must already be known through a retained enabled ordinary rank anchor. Discard the old teaching action, including its skill-cap reset; SQL never casts, inserts spells, changes skills/caps, profession slots, recipes, both selected builds, items or flags. Unsupported metadata, missing/disabled child anchors, wrong classes, invalid ownership, pending resets and unsupported skill/riding tiers defer. Review skill-teaching-native-proof.json and exact selected/deferred rows. Full custom originals, exact source/both-world/DBC/catalog/reader fingerprints, explicit stopped-copy/custom-start-off and @skill_teaching_ack=RETIRE_ONLY_REDUNDANT_KNOWN_SKILL_TEACHERS, atomic deletion/checkpoint, reruns/rollback and guarded exact inverse apply. Restore before native login or further edits with the original toolkit. Fresh snapshots require new sessions/inspections/selections and archives; no historical GUID/count replay. Release approval UNREVIEWED; gameplay NOT TESTED.',
        'tc-unselected-shaman-dual-wield-skill-retirement-v1':'Explicit paired retirement of enabled Dual Wield spell 674 AND existing native skill 118 for offline Shamans with neither spec selecting 30798 and no stored 30798. This deliberately changes skill state: retaining 118 would regrant 674 at login. All other skills/caps, both talent builds, items/inventory, profession slots and flags remain unchanged. Fresh empty off-hand required at planning, prepare, apply and restore; all occupied slots defer, including custom items. Review shaman-native-proof.json. Full custom originals and exact source/world/DBC/selector hashes, atomic paired mutation/checkpoint, guarded reruns/rollback/exact inverse and custom-start-off assertions apply. --expect-rows counts spell/skill pairs. Source DELETE/INSERT needed on both character_spell and character_skills; no automatic source grants. Direct SQL additionally needs @shaman_dual_wield_ack=RETIRE_UNSELECTED_SHAMAN_SPELL_AND_SKILL_EMPTY_OFFHAND plus stopped-copy and both custom-start-off acknowledgements. Fresh snapshots require a new session/inspection/batch; retain old toolkit for exact restore before gameplay. Gameplay NOT TESTED; release approval UNREVIEWED.',
        'tc-inactive-legacy-bloodthirst-retirement-v1':'Separate explicit retirement catalog for old Bloodthirst IDs 23892/23893/23894/25251/30335. Only active=0,disabled=0 rows may be removed; retain existing active catalog spells, current talent 23881, both builds, all skills/caps, profession slots and flags. Do not interpret this list as a rank chain or derive grants. Both effective catalogs must match fixed scriptless/skillless singleton mechanics with no teaching, requirement, aura, default, trainer or trigger routes. Unsupported metadata, mixed disabled history, online/pending resets or invalid builds defer. This deliberately discards unavailable known-spell/retraining history; it is not proof of corrupt source rows. Review inactive-legacy-native-proof.json and exact rows. Strong full-row/both-world/DBC/core/selector hashes, explicit @inactive_legacy_ack=RETIRE_ONLY_INACTIVE_LEGACY_BLOODTHIRST, custom-start-off assertions, transactional deletion/checkpoint and guarded exact custom-row restore apply. Native cast/spellbook tests use mocked state; gameplay NOT TESTED and approval UNREVIEWED. Fresh snapshots need new sessions/selections; retain old toolkits for restoration.',
        'tc-selected-direct-passive-authority-v1':'Retire only enabled higher direct passive ranks unselected in both specs in five reviewed families. Existing lower selected talents are authoritative; TC does NOT reconstruct these lower direct ranks. AC restores exact selected passive auras natively. This corrects effects deliberately; never grants trained ranks or temporary children. Preserve both talent builds, skills/caps, profession slots, flags and unrelated data. Both effective worlds/DBC and protected consumers, exact custom originals and numeric hashes are sealed. Atomic deletion/checkpoint, reruns, rollback and exact inverse use the existing two-world archive template. Pending resets, invalid or unsupported ownership, scripts, learning, skill rewards and other routes defer. Direct SQL requires @direct_passive_ack=SELECTED_LOWER_DIRECT_PASSIVES_AUTHORITATIVE plus ownership/stopped-copy and native custom-start-off assertions. Retain old toolkits for old archives. Gameplay NOT TESTED; approval UNREVIEWED.',
        'tc-selected-known-passive-rank-rekey-v5':'Rekey only enabled non-talent passive child anchors downward to exact active selected ranks already known through the old higher chain. Both selected builds remain authoritative. Only the four protected native passive contracts qualify; every affected chain must have one enabled anchor and an absent strictly lower destination. Parents alone never prove availability. No direct talent rekeys, higher grants, SQL insertion/deletion, flags, skills/caps, profession slots, login flags or unrelated data change. Stock character_spell columns are required; custom spell-specific fields need separate review. Review spell-rekeys.tsv and ownership-native-proof.json. Full original rows, source/world/DBC/reader fingerprints, sealed mapping and expected result, atomic UPDATE/checkpoint, rollback/reruns and guarded exact inverse apply. Source requires UPDATE(spell), not implicit new grants. Direct SQL additionally requires @talent_native_rekey_ack=ONLY_ALREADY_KNOWN_SELECTED_LOWER_PASSIVES and ownership/stopped-copy acknowledgements. Retain original toolkits for old archives. Gameplay NOT TESTED; approval UNREVIEWED.',
        'tc-unselected-reviewed-aura-alias-retirement-v4':'Retire only isolated unselected paladin talent families with exact protected spell_pal_improved_aura registrations and exact area-aura helper mechanics. All other script aliases remain unsupported. Helpers must be absent from stored spellbooks and have no learning, skill, ownership, prerequisite or script routes. Enabled talent availability is deliberately retired; no selected talents, both spec builds, skills/caps, profession slots, character/login flags or unrelated data change. SQL inserts no spells or rewrites flags. Review ownership-native-proof.json, script_alias, constructor_argument, area_aura_helper and exact selected/deferred rows. Direct SQL additionally needs @talent_aura_alias_ack=UNSELECTED_REVIEWED_AURA_ALIASES_ONLY plus ownership and stopped-copy acknowledgements. Full custom originals, exact fractional source/world hashes, source/DBC/reader contracts, atomic apply/checkpoint and rollback/rerun/exact restore remain required. Earlier policy exclusions are unchanged; retain earlier toolkits for their archives. Gameplay remains NOT TESTED and approval UNREVIEWED.',
        'tc-selected-native-passive-prefix-repair-v3':'Retire exact conflicts only in the four reviewed native passive talent families with disabled lower non-talent ranks restorable from retained enabled authorized higher anchors. Every selected root must already have correct source flags; no missing child is assumed restored from its learn-effect parent. Both selected builds remain authoritative. Review ownership-native-proof.json prefix_restore_anchors and retired_prefix_flags, exact selected rows, and any stale unowned enabled higher ranks also retired in those families. SQL inserts no spells, rewrites no flags, changes no talent ownership, spec count, skill/cap, profession, login flag or unrelated data. No rank above a retained authorized anchor is granted. Existing pending-reset, online, foreign/shared, independent/default/script/skill and malformed-metadata guards remain. Complete original custom fields, strong exact numeric/world hashes, atomic deletion/checkpoint, interruption rollback, reruns and guarded exact restoration apply. Direct SQL additionally requires @talent_native_prefix_ack=RETAIN_AUTHORIZED_HIGHER_ANCHORS and both ownership/stopped-copy acknowledgements. Retain prior toolkits for earlier archives. Native consumer checks use mocked state; full gameplay NOT TESTED and approval UNREVIEWED.',
        'tc-pet-teaching-reviewed-cower-retirement-v2':'Extends pet-teaching retirement only for the exact stock Cower child 1742 bindings under --reviewed-cower. Pinned hunter-script/header content and the reviewed Unit.cpp variants are verified and sealed. Both callbacks calculate aura amount only; no pet rows, player spells, skills, talents or professions are granted or rewritten. Review cower-native-contract.json and the native handler/lookup tests. Native getter differences are retained; arbitrary aura-layout gameplay equivalence is not claimed. Wrapper scripts, other child scripts, modified mechanics and all existing exclusions still defer. Full archives, strong metadata fingerprints, explicit Cower acknowledgement, atomic apply/checkpoint and exact restoration remain required. V1 default policy is unchanged.',
        'tc-pet-teaching-wrapper-retirement-v1':'Archives/removes exact verified player-side pet-teaching wrappers, including enabled rows. Loss of the old pet-training action is explicit; no replacement spell is granted. Actual pets and pet_spell, talent selections, skills/caps, professions, login flags and unrelated data remain unchanged. Both worlds/DBC catalogs, exact rank/effect/target contracts and complete source scope are checked. Player-teaching, profession, script, shared/default-route, pending-reset and ambiguous cases defer. Review pet-teaching-native-proof.json and exact selected rows. Full originals, strong numeric hashes, transactional apply/checkpoint/reruns and guarded exact restoration are required.',
        'tc-disabled-ordinary-training-prerequisites-v4':'Only wholly disabled ordinary rank families may be retired. This opt-in contract recognizes exact Divine Spirit/Prayer and Nature Grasp training prerequisites, without following them as learn/grant edges. Every related catalog chain and touching edge must match the reviewed requirement-only graph; scripts, skills, auto rewards, talents and unsupported changes defer. Enabled counterpart rows, both specs, skills/caps, profession slots, login flags and unrelated data are unchanged. No insertion or rank grant. Full originals and strong fractional source/world fingerprints are required; TC PlayerStart.AllSpells=0 and @ordinary_training_ack=REVIEWED_TRAINING_PREREQUISITES_ONLY supplement the stopped-copy acknowledgement. Only exact reviewed training families may have inactive custom-start routes under that setting; unrelated custom-start families defer. The explicit catalog is required and fingerprinted; selected_custom_default_rows and per-proof inactive_custom_default_spells record the allowance. Future reactivation/retraining history is discarded deliberately. Preview reviewed_candidate_rows includes deferred rows: --expect-review-rows must match that count, not selected_rows. Atomic checkpoint/rerun, interruption rollback and exact inverse apply. Retain original toolkits for earlier restores. This source preparation policy does not approve AC gameplay or bypass migration validation; core pins/manifests and UNREVIEWED approval remain unchanged.',
        'tc-ineligible-ordinary-absent-teacher-repair-v2':'Extends ordinary eligibility retirement only under --absent-teachers for exact stock Conjure Water and Doomguard single-child teachers. Every teacher must be absent even as disabled history, singleton, scriptless, skill-free, without incoming learning/prerequisite/talent/aura routes, and have exactly the reviewed mechanics/edges in both catalogs. Known, modified, multi-child and skill teachers defer. Both custom-start settings must remain off. The removed child rank family still must be entirely ineligible with no associated stored skills or talent authority. Full originals, both-world guards, atomic apply/checkpoint and exact restoration remain. No insertion, skill/talent/login/pet change or migration exception. Direct SQL additionally requires @eligibility_absent_teachers_ack=VERIFIED_TEACHERS_ABSENT. V1 behavior is unchanged; retain original toolkits for restoring earlier archives. Review eligibility-native-proof.json including absent_teacher_contract. Gameplay NOT TESTED; approval UNREVIEWED.',
        'tc-ineligible-ordinary-spell-repair-v1':'Explicit ordinary eligibility repair: retire exact stored rank families that AC would delete for race/class incompatibility, including ENABLED rows. Both effective world/DBC catalogs must agree, every rank must be ineligible, and associated stored skills, talents/aura ownership, learning/prerequisite routes, scripts, professions/riding and pending resets defer the family. Weapon proficiency is eligible only without its associated stored skill; no skill is removed or added. TC PlayerStart.AllSpells=0 and AC PlayerStart.CustomSpells=0 are explicit operator assertions. This deliberately removes unsupported source spell availability. SQL inserts no spells and rewrites no flags; both talent builds, skills/caps, profession slots and unrelated/custom data stay unchanged. Review spell-eligibility-review.json, eligibility-native-proof.json, relationship-review.tsv and all full archived originals. --expect-rows equals preview selected_rows, not the saved report count. Direct SQL requires the stopped-copy acknowledgement plus @spell_eligibility_ack=RETIRE_VERIFIED_INELIGIBLE_SPELLS and both @eligibility_tc_all_spells/@eligibility_ac_custom_spells=0. Full source and both world layouts/content are guarded, including direct calls. Apply/checkpoint is atomic and exact inverse restoration rejects later edits. No GM exemptions or migration bypasses. Restore batches in reverse order with original toolkits. Gameplay remains NOT TESTED; approval UNREVIEWED.',
        'tc-unselected-foreign-talent-retirement-v2':'Opt-in foreign-family retirement INCLUDING ENABLED spells. Only isolated families belonging exclusively to a different player class and selected in NEITHER spec qualify. Shared spells such as Dual Wield retain every skill/reward/independent-route exclusion; no shared skill spell may be removed through this option. Same-class families, invalid selections, pending reset, online and unsupported metadata defer. Both selected builds, skills/caps, professions, login flags and unrelated data are preserved. No grants, insertion or flag rewrite. Full originals and exact fractional source/world fingerprints, reader/proof hashes, transactional checkpoint/rerun/rollback and exact inverse apply. Review ownership-native-proof.json for class masks, complete family roots and empty ownership. --expect-rows equals selected_rows, not reviewed_candidate_rows. Direct SQL requires @talent_foreign_family_ack=UNSELECTED_FOREIGN_FAMILIES_ONLY, @talent_ownership_ack=SELECTED_TALENTS_AUTHORITATIVE and the stopped-copy acknowledgement. Retain original toolkits for older archives. Core pins/manifests are unchanged; approval UNREVIEWED and native gameplay NOT TESTED.',
        'tc-selected-talent-ownership-repair-v1':'Explicit ownership reconciliation: existing character_talent selections in BOTH specs are authoritative. Archives/removes conflicting stored spell rows INCLUDING ENABLED spells; this deliberately changes previously unowned or wrong-rank availability. SQL inserts no spells and rewrites no flags. Selected ownership, skills/caps, profession slots and login flags are unchanged. Active native runtime children require correctly enabled selected parents AND retained known child/prefix anchors: TC loading does not recast non-passive learn-effect talents. Missing active anchors, missing retained child anchors, owned-child flag conflicts, unsupported selected dependencies, shared/skill/default/profession routes, invalid ownership, foreign-class, online and pending reset states defer. Review talent-ownership-review.json, relationship-review.tsv and full archived originals. The preview reviews all talent-related conflicts within the captured GUID scope, including failures hidden behind the old first-error report. --expect-rows equals selected_rows, NOT reviewed_candidate_rows. Direct SQL additionally requires SET @talent_ownership_ack=\'SELECTED_TALENTS_AUTHORITATIVE\' with the stopped-copy acknowledgement before each action. Exact full-row inverse is guarded against gameplay or later edits; retain old toolkits and restore batches in reverse order. This does not reset builds, infer talent ownership, exempt staff or bypass migration checks. Gameplay remains NOT TESTED and approval UNREVIEWED.',
        'tc-native-death-coil-base-repair-v3':'Explicit native rank-1 availability repair, separate from inert ordinary-history retirement. Archives/removes only exact disabled trained Death Coil rows in the verified 47541/49892/49893/49894/49895 chain, where base 47541 is absent from storage and existing Unholy skill 772 independently grants it. PlayerStart.AllSpells=0 is required to prevent custom-start higher grants. Native rank 1 becomes available on load; SQL inserts no spells, activates no stored row and changes no skill/cap, talent/spec or login flag. Review native-base-review.json, including old skill values/caps and pre-existing level normalization that both cores already perform before and after this repair. Every related stored rank must be disabled; other skills, routes, classes, chains, metadata, enabled relatives and pending resets retain guards. Full originals, atomic deletion/checkpoint, late-error/disconnect rollback and guarded exact restore remain. Direct SQL additionally requires SET @ordinary_history_native_base=47541, SET @ordinary_history_all_spells=0 and the stopped-copy acknowledgement before each action. Restore before native login or further edits; after gameplay use the untouched baseline if archived-state guards refuse. No automatic GM exclusion or migration validation exemption is introduced. Native gameplay remains NOT TESTED and release approval stays UNREVIEWED.',
        'tc-disabled-ordinary-inactive-custom-defaults-v2':'Explicit extension of isolated ordinary history v1. PlayerStart.AllSpells=0 is an operator assertion recorded in configuration_contract, not a detected server configuration. Only this inactive playercreateinfo_spell_custom route may be disregarded; all skill rewards, profession/riding/Runeforging, talent, dependency, enabled-spell, script, metadata and pending-reset guards remain. Review selected_custom_default_rows and relationship-review.tsv. Full originals, atomic deletion/checkpoint and exact restoration remain required. Console prepare/apply/restore recheck [source] player_start_all_spells=0 and supply a fresh-session SQL assertion. Direct SQL additionally requires SET @ordinary_history_all_spells=0 before each action, as well as the stopped-copy acknowledgement. Restore requires the original assertion and unchanged state. Source/world schemas, GM/staff treatment and migration rejection rules do not change; release approval stays UNREVIEWED.',
        'tc-isolated-disabled-ordinary-spell-history-v1':'Explicit ordinary-spell preparation policy. Archives/removes only exact disabled rows in verified isolated ordinary rank families, including superseded inactive/disabled rows. Every present family row must remain disabled; absent ranks receive no grant. Talent-reachable families in every class, aura helpers, any incoming/outgoing learning or prerequisite route (including cycles), default/skill rewards, profession/riding/Runeforging associations, learn/skill effects, unknown scripts/corrections, invalid ownership, ineligible race/class and pending/online characters defer. Selected talents in either spec, enabled spell rows, skills/caps, profession slots and login flags remain unchanged. Preview candidate counts include exclusions; actual planning revalidates the full captured scope and full affected originals. Review ordinary-first-spell relationship proofs and exact selected/deferred rows before prepare/apply. Deleting unavailable history discards stored future reactivation/retraining state; it does not prove the original rows were corrupt. The existing atomic archive/checkpoint and guarded exact inverse apply. The migrator retains its rejection rules and release approval stays UNREVIEWED.',
        'tc-disabled-unselected-direct-talent-history-v1':'Archives/removes only exact disabled direct talent history with no selected family in either specialization and no enabled family conflict or alternate metadata learning route. Full affected spell/talent/skill/character originals are archived. No activation, reset, grants, caps, profession slots or login flags change. Deferred rows are listed in excluded-rows.tsv. Exact restore requires unchanged affected state and matching metadata.',
        'tc-disabled-reviewed-script-talent-history-v2':'Extends the disabled/unselected direct history policy only to families whose every effective TC script binding has the protected NO_SPELLBOOK_MUTATION contract. Review scripted-family-review.tsv and manifest reviewed_script_bindings. Alternate learning routes, dependencies, mixed chains, selected/ enabled family ranks, skill effects and pending resets remain excluded. Full affected originals are archived; apply removes only selected disabled rows. No activation, talent ownership, skills or login flags change. Exact restore requires unchanged affected state and matching metadata.',
        'tc-disabled-unselected-talent-closure-v3':'Archives/removes isolated wholly disabled direct talent, ordinary rank and dependent history rows, only when the entire verified relationship group has no selected talents or enabled spells. Every script must have the protected NO_SPELLBOOK_MUTATION contract. Shared/incoming routes, skill/default routes, skill effects, cycles and unsupported metadata defer the group. Review relationship-review.tsv (including absent nodes that receive no grant), relationship-edges.tsv, exact selected rows and selected_root_rows/selected_related_rows in the manifest. Full affected originals are archived; no ownership, enabled-spell, skill, login flag or other data changes. Existing v1/v2 policies remain unchanged.',
        'tc-disabled-reviewed-talent-routes-v4':'Extends v3 only for exact reviewed Berserk/Blast Wave teaching wrappers and a single-rank shaman 30798 root-only rule. Teaching wrapper groups must remain isolated and wholly disabled. The shaman exception deletes only inert disabled/unselected 30798, preserves shared spell 674 in every state and all skill 118 records, and does not resolve any remaining shared-spell ownership problem. Review relationship-review.tsv PRESERVED_SHARED_SKILL_ROUTE records, selected roots/related counts and reviewed_teacher_pairs. Complete affected originals and exact restore guards remain. No enabled-spell removal, grants, talent ownership, skills or login flags change. Earlier policy batches keep their original behavior.',
        'tc-disabled-other-selected-talent-rank-v5':'Archives/removes only exact disabled direct ranks selected by neither spec when the same family has a valid selected rank. Preserves every character_talent selection and all counterpart spell rows/flags, including differing selected ranks across both specs. Does not select the highest rank, grant an absent selected spell, activate, reset or alter points/skills/login flags. Mixed chains, teaching/prerequisite/skill/default routes, unsupported metadata and enabled unselected siblings defer the family. Review selected-rank-review.tsv, exact selected rows and complete prepared originals. This corrects stale persisted-rank conflicts against existing ownership; native gameplay remains untested. Full archives, atomic apply and guarded exact restore remain.',
        'tc-disabled-unselected-trained-talent-history-v6':'Archives wholly disabled unselected trained talent rank/dependency groups, including cases where the direct talent root is absent. Existing selected ownership in either spec, enabled related spells, pending resets, invalid class/ownership and independent learning/skill/default routes defer the whole group. Review relationship-review.tsv, exact selected/deferred rows and the captured migration evidence scope. Every affected character/spell/talent/skill original is archived, including custom fields. No new skill, rank, point, ownership, activation or reset is inferred; absent nodes receive no grant. Full live context and effective metadata must still match before planning; guarded atomic apply/restore preserves enabled state and unrelated data. Earlier history policies keep their original behavior.',
        'tc-disabled-unselected-talent-child-history-v7':'Archives wholly disabled unselected TC talent-child families, including their verified rank/dependency closure when direct and trained roots are absent. The candidate count comes from the captured preview; it is distinct from selected rows and affected characters. Both-spec ownership, enabled related spells, pending resets, invalid class/ownership, ambiguous derivations and independent learning/skill/default routes defer the whole family. Review relationship-review.tsv, exact selected/deferred rows and full prepared originals. No enabled spell, talent selection, skill, cap, point or login flag is changed; absent nodes receive no grant. Complete live context and effective metadata must match before planning. Atomic apply/checkpoint and guarded exact restoration use the existing archived-history transaction. Deleting unavailable history also discards stored future reactivation/retraining state; review that consequence before apply. Earlier history policies retain their original behavior.',
        'tc-active-build-native-reset-v1':'Queues a FREE NATIVE ACTIVE RESET PENDING LOGIN and archives/removes only explicitly selected foreign talent 12284. Every active talent row is preserved until native unlearning. All inactive builds must already be empty. Skill values/caps, profession slots, recipes, spec count and other spells are unchanged by SQL. Restore is exact only before native login or further changes.',
        'tc-invalid-talent-rank-v1':'Removes only verified non-rank talent records. No replacement rank or talent points are guessed.',
        'tc-single-character-native-talent-reset-v1':'Archives/removes the reviewed unavailable group and sets only at_login bit 4. APPLIED means FREE NATIVE RESET PENDING NEXT LOGIN. Active ownership stays until the core unlearns its spells and dependencies. Other login flags are preserved.',
        'tc-skill-clamp-stored-cap-v1':'Reduces only the exact audited over-cap skill values to their existing positive stored maximum. Caps, skill ownership, profession slots, spells, recipes and character state remain unchanged. No GM status or replacement cap is inferred. Full original skill rows are retained for exact restoration.',
        'tc-known-generic-switch-skill-v3':'Explicit insertion-only Generic 183 repair. Verified enabled known 63644/63645 use native skill acquisition independently of spec count; one-spec ownership remains one. Native Generic value/cap is level*5. Existing skills, talent selections in both groups, spec count, spells, recipes, profession slots, flags and unrelated data remain unchanged. SQL inserts no spells or talents and buys no second spec. Native skill loading may restore reviewed stock Generic system actions; exact reward IDs are recorded in native-skill-proof.json and unknown learning/skill/script routes defer. 63680 still requires its separately reviewed two-spec teacher policy; Runeforging recipes cannot establish missing skill state. Native skill metadata, race/class, flags, level, reset/online state and 127-slot bound remain required. Full originals and absences, exact fractional source/world fingerprints, layouts, DBC assets, selector/numeric/world reader hashes and proofs protect prepare/apply/restore. Atomic checkpoint, rollback/interruption, rerun and exact inverse apply. Direct SQL requires @native_generic_switch_ack=KNOWN_SWITCH_SKILL_ONLY and @skill_cleanup_ack=STOPPED_PREPARATION_COPY_ONLY. Retain original toolkits for earlier archives. Approval stays UNREVIEWED; gameplay NOT TESTED.',
        'tc-native-generic-skills-v2':'Explicit Generic-only preparation repair. Inserts absent or normalizes existing skill 183 to verified native level*5 value/cap using enabled known anchors or the exact two-spec TC 63680 load route. Existing other skills, spells, talents, specs, profession slots and character state are preserved. Complete originals, prior selected values and absences are archived; exact restore removes only insertions and restores original Generic values/caps, refusing affected-state or metadata drift. No game effect is executed. This is not a migration grant rule. Review native-skill-proof.json and selected-rows.tsv before apply.',
        'tc-missing-native-skills-v1':'Inserts only absent Generic 183 and/or Runeforging 776 rows justified by reviewed enabled known spell anchors. Generic uses native level*5 for value and cap (ALWAYS_MAX_VALUE metadata); Runeforging uses 1/1 for death knights. Existing skills, spells, talents, profession slots and login flags are unchanged. No riding or primary profession is added. This is an explicit preparation exception to exact skill preservation, not a migration grant rule. Native Runeforging skill loading may restore its default enchantments; SQL does not insert recipes/spells. Full original affected state and absence evidence are archived; restore deletes only inserted rows and refuses any affected-state drift.',
        'tc-zero-container-recovery-v1':'Moves only the exact inventory references into native recovery mail, with at most 12 attachments per mail and normal 30-day expiry. Item instances, custom attributes and zero-entry containers remain unchanged. Collect the items during isolated gameplay acceptance before expiry.'}[policy]
    return f'''# Reviewed cleanup candidate

Policy: `{policy}`. Session: `{manifest['cleanup_session']}`.
Archive: `{manifest['archive_schema']}`. Release approval: **UNREVIEWED**.

{details}

No source writes occurred while planning. Setup creates only this fresh archive;
prepare captures complete current original rows. Review `manifest.json`,
`selected-rows.tsv`, SQL, prepared snapshots and the operation's status.tsv.
Never edit generated SQL, weaken a guard, drop/reuse an archive or use --force.
A failed prepare/apply transaction rolls back incomplete changes. Existing
archive state, not this static candidate manifest, tells whether a batch applied.

From the toolkit, with your private cleanup.ini selected:

```
python3 console prepare --batch {manifest['batch_id']}
python3 console status --batch {manifest['batch_id']}
python3 console apply --batch {manifest['batch_id']}
python3 console status --batch {manifest['batch_id']}
```

An apply rerun verifies the same result. Status reconciles a lost connection;
do not infer failure or success merely from a client disconnect. Partial setup
DDL is retained and reported, never automatically dropped or continued blindly.

Exact inverse before native login/gameplay or further preparation:

```
python3 console restore --batch {manifest['batch_id']}
```

Restore batches in reverse application order. A later cleanup may invalidate
an older batch's state checks until the later cleanup is restored. Restore
refuses changed character/talent/item state, changed/claimed/expired mail or
reused original slots. It intentionally reinstates original findings. Archives
remain; apply-after-restore is refused. Use the preserved untouched baseline
for rollback after gameplay rather than forcing a targeted restore.

The audit establishes provenance, not a byte hash of every source field.
Preparation snapshots current complete affected state, including custom fields;
review it. Metadata, exact selected keys and original-value checks block drift.
Reports and packages contain private player data; keep the entire workspace
private. Credentials are not stored in packages or operation arguments.

After apply, rerun `python3 console audit --scope talents` or `--scope all` as
appropriate. Resolve remaining categories under separate reviewed policies.
After importing fresh databases, run `python3 console init --label fresh-import`
to create a NEW session; do not replay this session's old batches. Source edits
require a new migration with fresh target/control schemas.

SQL fixture checks are not native gameplay acceptance. Check casts/trainers,
both available specs and points, professions/recipes/riding/skill values/caps,
recovery mail, save/relog and restart in isolated staging. Gameplay remains
NOT TESTED and PROFILE_APPROVAL remains UNREVIEWED until actually accepted.
'''


def finish(settings,work,output,manifest,setup,selected,status,ack='talent_cleanup_ack'):
    manifest.update(cleanup_session=work.session.name,batch_id=output.name,
        source_uuid=work.current()['identity']['uuid'],source_schema=settings.schemas['characters'],
        core_compatibility=settings.compatibility,
        ack_variable=ack,status='CANDIDATE_FOR_REVIEW_NOT_APPLIED',migration_approval='UNREVIEWED')
    # All files are written into a fresh private package, marked incomplete until sealed.
    output.mkdir(mode=0o700)
    (output/'INCOMPLETE').write_text('Incomplete generation. Do not execute.\n')
    (output/'00-setup.sql').write_text(setup)
    for number,action in ((1,'prepare'),(2,'apply'),(3,'restore')):
        (output/f'0{number}-{action}.sql').write_text(f"CALL `{manifest['archive_schema']}`.{action}_batch();\n")
    (output/'04-status.sql').write_text(status)
    (output/'selected-rows.tsv').write_text(selected)
    write_json(output/'manifest.json',manifest)
    (output/'README.md').write_text(readme(manifest))
    (output/'INCOMPLETE').unlink()
    seal(output)


def plan_talents(settings,work,args,output):
    audit_id=args.audit
    if not audit_id:
        pointer=work.session/'latest-audit.json'
        if not pointer.exists():
            fail('AUDIT_REQUIRED','Run an audit in this session before planning talent cleanup')
        audit_id=json.loads(pointer.read_text())['audit']
    audit=work.session/'audits'/local_id(audit_id)
    if audit.is_symlink():
        fail('SYMLINK_REFUSED','Audit directory cannot be a symlink')
    status=json.loads((audit/'audit.json').read_text())
    if status.get('schemas')!=settings.schemas or status.get('server',{}).get('uuid')!=work.current()['identity']['uuid']:
        fail('AUDIT_SESSION_MISMATCH','Audit source identity differs from the current session')
    archive='tc_cleanup_'+uuid.uuid4().hex[:24]
    manifest=planner.generate(audit,settings.paths['tc_dbc'],args.expect_rows,output,archive)
    manifest.update(cleanup_session=work.session.name,batch_id=output.name,ack_variable='talent_cleanup_ack',audit_id=audit_id,
                    core_compatibility=settings.compatibility)
    write_json(output/'manifest.json',manifest)
    (output/'README.md').write_text(readme(manifest)+'\n'+(output/'README.md').read_text())
    seal(output)


def plan_reset(settings,work,args,output):
    guid=args.guid
    if not 1<=guid<=4294967295:
        fail('INVALID_GUID','Character GUID must fit the native unsigned domain')
    source=identifier(settings.schemas['characters'])
    meta=metadata(settings,['characters','character_talent'])
    state=snapshot(settings,[('character',f'SELECT JSON_ARRAY(guid,account,name,level,class,activeTalentGroup,talentGroupsCount,online) row_value FROM `{source}`.characters WHERE guid={guid}'),
        ('talents',f'SELECT JSON_ARRAY(guid,spell,talentGroup) row_value FROM `{source}`.character_talent WHERE guid={guid} ORDER BY spell,talentGroup'),
        ('count',f'SELECT JSON_ARRAY(COUNT(*)) row_value FROM `{source}`.character_talent')])
    write_json(work.operation/'evidence.json',{'state':state,'metadata':meta})
    if len(state['character'])!=1:
        fail('CHARACTER_MISSING','Character does not exist')
    _,account,name,level,cls,active,count,online=state['character'][0]
    if cls not in (1,2,3,4,5,6,7,8,9,11):
        fail('RESET_CLASS_UNSUPPORTED','Character class is outside the reviewed class catalog')
    if count!=1 or active!=0 or online!=0:
        fail('RESET_STATE_UNSUPPORTED','Reviewed reset policy requires one configured spec, active group 0 and offline state')
    if not isinstance(name,str) or not name or len(name.encode())>256:
        fail('RESET_NAME_UNSUPPORTED','Character name is empty or outside the supported byte bound')
    selected=sorted(tuple(row) for row in state['talents'] if row[2]==1)
    retained=[row for row in state['talents'] if row[2]==0]
    if not selected or len(selected)>1000 or not retained or any(row[2] not in (0,1) for row in state['talents']):
        fail('RESET_STATE_UNSUPPORTED','Reviewed reset needs an exact unavailable group 1 and a nonempty active group 0; other cases require separate review')
    stores,catalog,dbc_hashes=ranks(settings)
    for _,spell,_ in selected+retained:
        matches=[(row[0],i) for row in stores['Talent'].values() for i,value in enumerate(row[4:9])
            if value==spell and stores['TalentTab'].get(row[1],[0]*21)[20] & (1<<(cls-1))]
        if len(matches)!=1 or spell not in stores['Spell']:
            fail('RESET_RANK_UNSUPPORTED',f'Selected spell is not one unambiguous class talent rank: {spell}')
    template=ROOT/'tools/single-character-talent-reset.sql.in'
    batch_key=sha_json({'session':work.session.name,'id':output.name,'state':state,'template':sha(template),'dbc':dbc_hashes})
    archive='tc_reset_'+uuid.uuid4().hex[:24]
    source_count=state['count'][0][0]
    values={'SOURCE':source,'ARCHIVE':archive,'UUID':work.current()['identity']['uuid'],
        'BATCH':batch_key,'AUDIT':sha_json(state),'EXPECTED_HASH':planner.key_hash(selected),
        'RANK_HASH':planner.key_hash([(s,) for s in catalog]),'COUNT':len(selected),
        'SOURCE_COUNT':source_count,'AFTER_COUNT':source_count-len(selected),'RANK_COUNT':len(catalog),
        'EXPECTED_INSERT':planner.insert_values('expected',selected),
        'RANK_INSERT':planner.insert_values('valid_rank_spell',[(s,) for s in catalog]),
        'GUID':guid,'ACCOUNT':account,'NAME':name,'LEVEL':level,'CLASS':cls,
        'ACTIVE_GROUP':active,'SPEC_COUNT':count,'REMOVE_GROUP':1,'RETAINED_ROWS':len(retained)}
    if metadata(settings,['characters','character_talent'])!=meta:
        fail('SCHEMA_DRIFT','Source metadata changed while planning')
    manifest={'policy':'tc-single-character-native-talent-reset-v1','archive_schema':archive,'batch_key':batch_key,
        'selected_rows':len(selected),'affected_characters':1,'character':state['character'][0],
        'before_talent_rows':len(state['talents']),'retained_pending_native_reset':len(retained),
        'audited_source_talent_rows':source_count,'evidence_sha256':sha_json(state),
        'evidence':state,'dbc_sha256':dbc_hashes,'template_sha256':sha(template),
        'native_reset':'PENDING NEXT LOGIN after apply'}
    status=f'SELECT * FROM `{archive}`.batch;\nSELECT guid,account,name,level,activeTalentGroup,talentGroupsCount,at_login,(at_login & 4)<>0 AS native_talent_reset_pending FROM `{source}`.characters WHERE guid={guid};\nSELECT talentGroup,COUNT(*) AS current_rows FROM `{source}`.character_talent WHERE guid={guid} GROUP BY talentGroup;\n'
    finish(settings,work,output,manifest,render(template,values),
        'guid\tspell\ttalentGroup\n'+''.join(':'.join(map(str,row)).replace(':','\t')+'\n' for row in selected),status)


def sha_json(data):
    import hashlib
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def inspect_items(settings,work):
    source=identifier(settings.schemas['characters'])
    state=snapshot(settings,[('contents',f'''SELECT JSON_ARRAY(i.bag,b.owner_guid,i.guid,c.guid IS NOT NULL,i.slot,i.item,t.guid IS NOT NULL,t.itemEntry)
      row_value FROM `{source}`.character_inventory i JOIN `{source}`.item_instance b ON b.guid=i.bag
      LEFT JOIN `{source}`.characters c ON c.guid=i.guid LEFT JOIN `{source}`.item_instance t ON t.guid=i.item
      WHERE i.bag<>0 AND b.itemEntry=0 ORDER BY i.bag,i.guid,i.slot,i.item''')])
    directory=work.session/'inspections'/token('containers')
    directory.mkdir(mode=0o700)
    path=directory/'containers.tsv'
    with path.open('w',newline='') as stream:
        writer=csv.writer(stream,delimiter='\t',lineterminator='\n')
        writer.writerow(['container_guid','container_owner','inventory_character','character_exists','slot','item_guid','item_exists','item_entry'])
        writer.writerows(state['contents'])
    seal(directory)
    print(f"INSPECTED {len(state['contents'])} contained-item references; no changes\nReports: {path}")


def plan_items(settings,work,args,output):
    try:
        bags=[int(value) for value in args.containers.split(',')]
    except ValueError:
        fail('INVALID_CONTAINERS','Use comma-separated numeric container GUIDs')
    if not bags or len(bags)>1000 or len(set(bags))!=len(bags) or any(not 1<=v<=4294967295 for v in bags):
        fail('INVALID_CONTAINERS','Expected 1-1000 distinct positive native container GUIDs')
    tables=['character_inventory','item_instance','mail','mail_items','characters','guild_bank_item','auctionhouse']
    meta=metadata(settings,tables)
    inventory=require_shape(meta,'character_inventory',{'guid','bag','slot','item'},exact=True)
    if inventory!={'guid':('int unsigned','NO','MUL'),'bag':('int unsigned','NO',''),
                   'slot':('tinyint unsigned','NO',''),'item':('int unsigned','NO','PRI')}:
        fail('UNSUPPORTED_SCHEMA','Inventory differs from the reviewed native representation')
    require_shape(meta,'item_instance',{'guid','itemEntry','owner_guid'})
    require_shape(meta,'mail_items',{'mail_id','item_guid','receiver'},exact=True)
    require_shape(meta,'mail',{'id','messageType','stationery','mailTemplateId','sender','receiver','subject','body','has_items','expire_time','deliver_time','money','cod','checked'})
    source=identifier(settings.schemas['characters'])
    auth=identifier(settings.schemas['auth'])
    selectors=','.join(map(str,sorted(bags)))
    state=snapshot(settings,[('contents',f'''SELECT JSON_ARRAY(i.guid,i.bag,i.slot,i.item,t.itemEntry,b.owner_guid,b.itemEntry,t.owner_guid,c.online,a.id)
      row_value FROM `{source}`.character_inventory i LEFT JOIN `{source}`.item_instance b ON b.guid=i.bag
      LEFT JOIN `{source}`.item_instance t ON t.guid=i.item LEFT JOIN `{source}`.characters c ON c.guid=i.guid
      LEFT JOIN `{auth}`.account a ON a.id=c.account WHERE i.bag IN ({selectors}) ORDER BY i.item''')])
    write_json(work.operation/'evidence.json',{'state':state,'metadata':meta})
    raw=state['contents']
    if not raw or len(raw)>10000 or {row[1] for row in raw}!=set(bags):
        fail('ITEM_RECOVERY_BLOCKED','Selected containers have no contents or exceed the 10000-row reviewed batch bound')
    if len({row[3] for row in raw})!=len(raw):
        fail('ITEM_RECOVERY_BLOCKED','An item has multiple selected inventory references')
    for guid,bag,slot,item,entry,bag_owner,bag_entry,item_owner,online,account in raw:
        if (bag_entry!=0 or bag_owner!=guid or item_owner!=guid or online!=0
                or account is None or entry is None or guid==0):
            fail('ITEM_RECOVERY_BLOCKED',f'Container {bag}, item {item}: missing character/account/item, wrong owner, nonzero container entry or online recipient')
    # Split each recipient deterministically into at most 12 existing instances per mail.
    by_recipient=defaultdict(list)
    for row in raw:
        by_recipient[row[0]].append(row[:5])
    expected=[]
    ordinal=0
    for guid,items in sorted(by_recipient.items()):
        for start in range(0,len(items),12):
            ordinal+=1
            expected.extend(tuple(row)+(ordinal,) for row in items[start:start+12])
    expected.sort(key=lambda row:row[3])
    template=ROOT/'tools/container-recovery.sql.in'
    batch_key=sha_json({'session':work.session.name,'id':output.name,'expected':expected,'meta':meta,'template':sha(template)})
    archive='tc_items_'+uuid.uuid4().hex[:24]
    columns={table:len([row for row in meta['columns'] if row[0]==table]) for table in tables}
    values={'SOURCE':source,'AUTH':auth,'ARCHIVE':archive,'UUID':work.current()['identity']['uuid'],
        'BATCH':batch_key,'AUDIT':sha_json(state),'EXPECTED_HASH':planner.key_hash(expected),
        'EXPECTED_INSERT':planner.insert_values('expected',expected),'COUNT':len(expected),
        'RECIPIENTS':len(by_recipient),'CONTAINERS':len(bags),'SNAPSHOTS':len(expected)+len(bags),
        'MAILS':ordinal,'INVENTORY_COLUMNS':columns['character_inventory'],'ITEM_COLUMNS':columns['item_instance'],
        'MAIL_COLUMNS':columns['mail'],'MAIL_ITEM_COLUMNS':columns['mail_items'],
        'ARCHIVE_COLUMNS':sum(columns[t] for t in ('character_inventory','item_instance','mail','mail_items')),
        'CONCAT_LIMIT':max(8192,len(expected)*160),
        'ITEM_EQUAL':equality(meta,'item_instance'),'MAIL_EQUAL':equality(meta,'mail','s','p')}
    if metadata(settings,tables)!=meta:
        fail('SCHEMA_DRIFT','Source metadata changed while planning')
    manifest={'policy':'tc-zero-container-recovery-v1','archive_schema':archive,'batch_key':batch_key,
        'selected_rows':len(expected),'containers':sorted(bags),'recipients':len(by_recipient),'mails':ordinal,
        'expected_sha256':planner.key_hash(expected),'expected_inventory':expected,'evidence':state,
        'metadata_sha256':sha_json(meta),'template_sha256':sha(template),
        'item_policy':'Preserve all instances and custom fields; no missing-template item deletion'}
    selected='guid\tbag\tslot\titem\titemEntry\tmail_ordinal\n'+''.join('\t'.join(map(str,row))+'\n' for row in expected)
    status=f'SELECT * FROM `{archive}`.batch;\nSELECT COUNT(*) AS archived_inventory_rows FROM `{archive}`.original_inventory;\nSELECT COUNT(*) AS full_item_snapshots FROM `{archive}`.item_snapshot;\nSELECT id,receiver,deliver_time,expire_time FROM `{archive}`.planned_mail ORDER BY id;\nSELECT * FROM `{archive}`.planned_mail_items ORDER BY mail_id,item_guid;\n'
    finish(settings,work,output,manifest,render(template,values),selected,status,'recovery_ack')


def plan(settings,work,args,output):
    if args.kind=='native-skills':
        from cleanup_native_skills import plan_native_skills
        return plan_native_skills(settings,work,args,output)
    if args.kind in ('disabled-talent-history','disabled-spell-history','talent-ownership','spell-eligibility','pet-teaching','inactive-legacy-spells','skill-teaching','profession-activation','specialization-retirement'):
        from cleanup_disabled_history import plan_history
        return plan_history(settings,work,args,output)
    if args.kind=='reset-active-talents':
        from cleanup_active_reset import plan_active_reset
        return plan_active_reset(settings,work,args,output)
    if args.kind=='skills':
        from cleanup_skills import plan_skills
        return plan_skills(settings,work,args,output)
    {'talents':plan_talents,'reset-talents':plan_reset,'items':plan_items}[args.kind](settings,work,args,output)
