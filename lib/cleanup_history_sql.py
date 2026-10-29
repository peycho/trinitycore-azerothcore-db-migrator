"""SQL template values and native policy acknowledgement guards."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from cleanup_active_reset import TABLES
from cleanup_disabled_history import check_sets
import cleanup_eligibility as eligibility
from cleanup_files import fail
import cleanup_foreign_skills as foreign_skills
from cleanup_history_models import (
    HistoryBatch,
    HistoryEvidence,
    HistoryOptions,
    HistoryPolicy,
    HistorySelection,
    HistorySnapshot,
)
import cleanup_obsolete_riding as riding
import cleanup_pet_teaching as pet_teaching
from cleanup_plans import planner
import cleanup_shaman_dual_wield as shaman
import cleanup_shaman_offhand as offhand_repair
import cleanup_specializations as specializations

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


def build_history_sql_values(
    settings: Settings,
    work: Workspace,
    options: HistoryOptions,
    snapshot: HistorySnapshot,
    batch: HistoryBatch,
    evidence: HistoryEvidence,
    selection: HistorySelection,
    policy: HistoryPolicy,
) -> dict[str, Any]:
    blocks = check_sets(snapshot.meta, snapshot.source, batch.archive,
        snapshot.counts, changed_table= ('character_spell',
            'character_skills') if options.shaman_mode or options.riding_mode
        or options.foreign_skill_mode else 'character_spell',
        exact_numeric=options.exact_mode)
    values = {'SOURCE': snapshot.source, 'ARCHIVE': batch.archive,
        'UUID': work.current()['identity']['uuid'],
        'BATCH': batch.batch, 'AUDIT': evidence.audit[
            'audited_results_sha256'], 'COUNT': len(selection.selected),
        'GUID_COUNT': len(selection.guids),
        'EXPECTED_HASH': planner.key_hash(selection.selected),
        'SNAPSHOT_COUNT': len(snapshot.cells),
        'SNAPSHOT_HASH': planner.key_hash(snapshot.cells),
        'COLUMN_COUNT': len(snapshot.meta['columns']),
        'COLUMN_HASH': planner.key_hash(snapshot.meta['columns']),
        'CONCAT_LIMIT': max(6400001, len(snapshot.cells) * 160, len(
            selection.selected) * 80, len(snapshot.meta['columns']) * 2048),
        'EXPECTED_INSERT': planner.insert_values('expected_spells',
            selection.selected),
        'SNAPSHOT_INSERT': planner.insert_values('expected_snapshot',
            snapshot.cells),
        'AFTER_INSERT': planner.insert_values('expected_after',
            snapshot.after),
        'AFTER_COUNT': len(snapshot.after), 'AFTER_HASH': planner.key_hash(
            snapshot.after),
        'COLUMN_INSERT': planner.insert_values('reviewed_columns',
            snapshot.meta['columns']),
        'GUID_INSERT': planner.insert_values('affected', [(guid,) for guid
            in selection.guids]),
        'CHECK_ORIGINAL': blocks['original'], 'CHECK_ARCHIVE': blocks[
            'archive'], 'CHECK_APPLIED': blocks['applied'],
        'ARCHIVE_INSERT': '\n'.join(
            f'  INSERT INTO {table}_before SELECT s.* FROM `{snapshot.source}'
            f'`.{table} s JOIN affected g ON g.guid=s.guid;' for table
            in TABLES)}
    if options.foreign_skill_mode:
        skill_keys = [(g, k) for g, k, v, c in selection.retired_skill_rows]
        values.update(SKILL_INSERT=planner.insert_values('expected_skills',
            skill_keys), SKILL_COUNT=len(skill_keys),
            SKILL_HASH=planner.key_hash(skill_keys))
    if options.parent_mode:
        parent_rows = [(g, 9787, 1, 0) for g in selection.guids]
        values.update(PARENT_INSERT=planner.insert_values('expected_parents',
            parent_rows),
            PARENT_HASH=planner.key_hash(parent_rows))
    if options.rekey_mode:
        values.update(MAPPING_INSERT=planner.insert_values('expected_rekeys',
            selection.rekeys),
            MAPPING_HASH=planner.key_hash(selection.rekeys))
    world_checks = []
    for table, count, checksum in evidence.world['digests']:
        fields = ([row[1] for row in evidence.world['layout']['columns']
            if row[0] == table])
        hashed = ("SHA2(CONCAT_WS('|'," + ','.join(
            f"IFNULL(HEX(`{name}`),'N')" for name in fields) + '),256)')
        world_checks.append(
            f'''IF (SELECT COUNT(*) FROM `{settings.schemas['world']}`.`{table}`)<>{count}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT({hashed} ORDER BY BINARY {hashed} SEPARATOR ''),''),256)
     FROM `{settings.schemas['world']}`.`{table}`)<=>'{checksum}') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='World metadata content changed: {table}'; END IF;''')
    values['WORLD_CHECKS'] = (eligibility.world_checks(settings.schemas[
        'world'], evidence.world) if options.strong_history_mode
        else '\n'.join(world_checks))
    if options.ownership_mode:
        schema = settings.schemas['world']
        names = ','.join("'" + r[0] + "'" for r in evidence.world['layout'][
            'tables'])
        layout_checks = f"""IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<>{len(evidence.world['layout']['columns'])}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION,EXTRA)
 ORDER BY BINARY TABLE_NAME,ORDINAL_POSITION SEPARATOR '|'),''),256) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<=>'{planner.key_hash(evidence.world['layout']['columns'])}')
 OR (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<>{len(evidence.world['layout']['tables'])}
 OR NOT ((SELECT SHA2(COALESCE(GROUP_CONCAT(CONCAT_WS(':',TABLE_NAME,ENGINE,TABLE_TYPE) ORDER BY BINARY TABLE_NAME SEPARATOR '|'),''),256)
 FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME IN ({names}))<=>'{planner.key_hash(evidence.world['layout']['tables'])}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Ownership world layout or engine drift'; END IF;
"""
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @talent_ownership_ack <=> BINARY 'SELECTED_TALENTS_AUTHORITATIVE') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit selected-talent ownership repair acknowledgement required'; END IF;
""" + layout_checks + values['WORLD_CHECKS']
    if options.foreign_mode:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @talent_foreign_family_ack <=> BINARY 'UNSELECTED_FOREIGN_FAMILIES_ONLY') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit unselected foreign-family acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.prefix_mode:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @talent_native_prefix_ack <=> BINARY 'RETAIN_AUTHORIZED_HIGHER_ANCHORS') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit retained native passive prefix acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.rekey_mode:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @talent_native_rekey_ack <=> BINARY 'ONLY_ALREADY_KNOWN_SELECTED_LOWER_PASSIVES') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit already-known selected lower passive acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.alias_mode:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @talent_aura_alias_ack <=> BINARY 'UNSELECTED_REVIEWED_AURA_ALIASES_ONLY') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit reviewed aura alias acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.config_contract is not None and not options.two_world_mode:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @ordinary_history_all_spells <=> BINARY '0') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit PlayerStart.AllSpells=0 assertion required for ordinary history v2'; END IF;
""" + values['WORLD_CHECKS']
    if options.training_prerequisites:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @ordinary_training_ack <=> BINARY 'REVIEWED_TRAINING_PREREQUISITES_ONLY') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit reviewed ordinary training prerequisites acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.native_death_coil:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @ordinary_history_native_base <=> BINARY '47541') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit native Death Coil rank 1 availability assertion required'; END IF;
""" + values['WORLD_CHECKS']
    if options.two_world_mode:
        ack_var = ('foreign_skill_family_ack' if options.foreign_skill_mode
            else 'obsolete_riding_ack' if options.riding_mode
            else 'specialization_retirement_ack'
            if options.specialization_mode else 'profession_activation_ack'
            if options.profession_mode else 'skill_teaching_ack'
            if options.skill_teaching_mode else 'shaman_dual_wield_ack'
            if options.shaman_mode else 'direct_passive_ack'
            if options.direct_mode else 'inactive_legacy_ack'
            if options.legacy_mode else 'pet_teaching_ack' if options.pet_mode
            else 'spell_eligibility_ack')
        native_ack = (foreign_skills.policy_ack(policy.policy)
            if options.foreign_skill_mode else riding.HORSE_ACK
            if options.riding_horse else riding.INVALID_ITEMS_ACK
            if options.riding_invalid_items else options.native_selector.ACK)
        config_prefix = 'pet_teaching' if options.pet_mode else 'eligibility'
        values[
            'WORLD_CHECKS'] = f"""IF NOT (BINARY @{ack_var} <=> BINARY '{native_ack}')
 OR NOT (BINARY @{config_prefix}_tc_all_spells <=> BINARY '0')
 OR NOT (BINARY @{config_prefix}_ac_custom_spells <=> BINARY '0') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit {"pet-teaching" if options.pet_mode else "eligibility"} repair and native custom-start-off assertions required'; END IF;
""" + eligibility.world_checks(settings.schemas['world'],
    evidence.world) + '\n' + eligibility.world_checks(
        options.config_contract['target_world'], policy.target_world)
    if options.foreign_skill_mode:
        values['WORLD_CHECKS'] = (riding.items_guard(settings,
            selection.foreign_selected_items, selection.guids,
            native_invalid_items=True) + '\n' + offhand_repair.evidence_guard(
                settings, selection.foreign_selected_equipment) + '\n' + (''
                    if options.foreign_inventory_mode
                    else offhand_repair.inventory_check(snapshot.source,
                        'character_inventory',
                        selection.foreign_selected_equipment[
                            'inventory'], selection.guids,
                        'Foreign skill source')) + '\n'
            + values['WORLD_CHECKS'])
        values['WORLD_CHECKS'] += ('\n' + '\n'.join(eligibility.world_checks(w[
            'schema'], w) for w in selection.foreign_defaults.values()))
        if options.foreign_inventory_mode:
            move_sql = offhand_repair.sql_parts(settings,
                selection.foreign_selected_equipment, selection.guids,
                selection.foreign_inventory_moves, batch.archive)
            values['WORLD_CHECKS'] = (move_sql['guard'] + '\n' + values[
                'WORLD_CHECKS'])
            for name, phase in (('CHECK_ORIGINAL', 'original'), (
                'CHECK_ARCHIVE', 'archive'), ('CHECK_APPLIED', 'applied')):
                values[name] += '\n' + move_sql[phase]
            values['ARCHIVE_INSERT'] += (
                '\n INSERT INTO inventory_before SELECT i.* FROM `'
                f'{snapshot.source}`.character_inventory i JOIN affected '
                'g ON g.guid=i.guid;'
            )
            values.update(MOVE_INSERT=planner.insert_values('expected_moves',
                selection.foreign_inventory_moves), MOVE_COUNT=len(
                    selection.foreign_inventory_moves),
                MOVE_HASH=planner.key_hash(
                    selection.foreign_inventory_moves))

    if options.specialization_mode:
        values['WORLD_CHECKS'] = (specializations.equipment_guard(settings,
            selection.equipment, selection.guids) + '\n' + values[
                'WORLD_CHECKS'])
    if options.shaman_mode:
        if options.offhand_mode:
            offhand_sql = offhand_repair.sql_parts(settings,
                selection.selected_offhand_capture, selection.guids,
                selection.inventory_moves, batch.archive)
            values['WORLD_CHECKS'] = (offhand_sql['guard'] + values[
                'WORLD_CHECKS'])
            for name, phase in (('CHECK_ORIGINAL', 'original'), (
                'CHECK_ARCHIVE', 'archive'), ('CHECK_APPLIED', 'applied')):
                values[name] += '\n' + offhand_sql[phase]
            values['ARCHIVE_INSERT'] += (
                '\n INSERT INTO inventory_before SELECT i.* FROM `'
                f'{snapshot.source}`.character_inventory i JOIN affected '
                'g ON g.guid=i.guid;'
            )
            values.update(MOVE_INSERT=planner.insert_values('expected_moves',
                selection.inventory_moves), MOVE_COUNT=len(
                    selection.inventory_moves), MOVE_HASH=planner.key_hash(
                        selection.inventory_moves))
        else:
            values['WORLD_CHECKS'] = (shaman.inventory_guard(snapshot.source,
                selection.inventory_meta) + values['WORLD_CHECKS'])
        values['WORLD_CHECKS'] += ('\n' + '\n'.join(eligibility.world_checks(w[
            'schema'], w) for w in selection.default_skills.values()))
    if options.riding_mode:
        values['WORLD_CHECKS'] = (riding.items_guard(settings,
            selection.riding_items, selection.guids,
            native_invalid_items=options.riding_invalid_items) + values[
                'WORLD_CHECKS'])
        values['WORLD_CHECKS'] += ('\n' + '\n'.join(eligibility.world_checks(w[
            'schema'], w) for w in selection.riding_defaults.values()))
    if options.direct_mode:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @talent_ownership_ack <=> BINARY 'SELECTED_TALENTS_AUTHORITATIVE') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit selected-talent ownership repair acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.cast_script_mode:
        values['WORLD_CHECKS'] = (
            "IF NOT(BINARY @eligibility_cast_scripts_ack <=> BINARY '"
            f"{eligibility.CAST_SCRIPT_ACK}') THEN SIGNAL SQLSTATE "
            "'45000' SET MESSAGE_TEXT='Explicit reviewed nonlearning "
            "callback acknowledgement required'; END IF;\n"
        ) + values['WORLD_CHECKS']
    if options.racial_mode:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @eligibility_racials_ack <=> BINARY 'RETIRE_ONLY_REVIEWED_WRONG_RACE_RACIALS') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit reviewed racial retirement acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.action_mode:
        values[
            'WORLD_CHECKS'] = f"""IF NOT (BINARY @eligibility_foreign_action_ack <=> BINARY '{eligibility.ACTION_ACK}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit inactive foreign action acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.swipe_mode:
        values[
            'WORLD_CHECKS'] = f"""IF NOT (BINARY @eligibility_swipe_ack <=> BINARY '{eligibility.SWIPE_ACK}') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit inactive foreign Swipe acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.absent_teachers:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @eligibility_absent_teachers_ack <=> BINARY 'VERIFIED_TEACHERS_ABSENT') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit absent-teacher eligibility acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
    if options.reviewed_cower:
        values[
            'WORLD_CHECKS'] = """IF NOT (BINARY @pet_teaching_cower_ack <=> BINARY 'REVIEWED_COWER_CHILD_ONLY') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Explicit reviewed Cower child acknowledgement required'; END IF;
""" + values['WORLD_CHECKS']
        if pet_teaching.cower_sources(settings.paths) != options.cower_proof:
            fail('COWER_NATIVE_SOURCE_DRIFT',
                'Cower source contract changed during planning')
    return values
