"""Sealed SQL package publication and supporting proof artifacts."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, TYPE_CHECKING

import cleanup_death_coil as death_coil
from cleanup_disabled_history import render_text
from cleanup_files import ROOT, sha, write_json
from cleanup_history_models import (
    HistoryBatch,
    HistoryEvidence,
    HistoryOptions,
    HistoryPolicy,
    HistorySelection,
    HistorySnapshot,
)
import cleanup_ordinary_history as ordinary_history
import cleanup_ownership as ownership
from cleanup_plans import finish
import cleanup_professions as professions
import cleanup_trained_history as trained_history
from cleanup_types import Evidence

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


def publish_history_package(
    settings: Settings,
    work: Workspace,
    output: Path,
    batch: HistoryBatch,
    selection: HistorySelection,
    options: HistoryOptions,
    policy: HistoryPolicy,
    manifest: Evidence,
    snapshot: HistorySnapshot,
    values: Mapping[str, Any],
    evidence: HistoryEvidence,
) -> None:
    status = f'''SELECT * FROM `{batch.archive}`.batch;
SELECT 'expected' AS object,COUNT(*) rows_found FROM `{batch.archive}`.expected_spells
UNION ALL SELECT 'characters_before',COUNT(*) FROM `{batch.archive}`.characters_before
UNION ALL SELECT 'talent_before',COUNT(*) FROM `{batch.archive}`.character_talent_before
UNION ALL SELECT 'spell_before',COUNT(*) FROM `{batch.archive}`.character_spell_before
UNION ALL SELECT 'skills_before',COUNT(*) FROM `{batch.archive}`.character_skills_before;
SELECT COUNT(*) AS selected_rows,SUM(s.spell IS NOT NULL) AS still_stored,SUM(s.spell IS NULL) AS absent
FROM `{batch.archive}`.expected_spells e LEFT JOIN `{snapshot.source}`.character_spell s ON s.guid=e.guid AND s.spell=e.spell;
-- Exact selection is retained in selected-rows.tsv and expected_spells;
-- bound terminal/status preview independently of the cleanup population.
SELECT e.guid,e.spell,e.active,e.disabled,s.spell IS NOT NULL AS still_stored
FROM `{batch.archive}`.expected_spells e LEFT JOIN `{snapshot.source}`.character_spell s ON s.guid=e.guid AND s.spell=e.spell ORDER BY e.guid,e.spell LIMIT 100;
'''
    if options.profession_mode:
        status = status[:status.index(
            'SELECT COUNT(*) AS selected_rows')] + f'''SELECT COUNT(*) selected_rows,
SUM(s.spell IS NOT NULL AND s.active=0 AND s.disabled=0) inactive_rows,
SUM(s.spell IS NOT NULL AND s.active=1 AND s.disabled=0) activated_rows
FROM `{batch.archive}`.expected_spells e LEFT JOIN `{snapshot.source}`.character_spell s ON s.guid=e.guid AND s.spell=e.spell;
SELECT e.guid,e.spell,e.active AS original_active,s.active AS current_active,s.disabled
FROM `{batch.archive}`.expected_spells e LEFT JOIN `{snapshot.source}`.character_spell s ON s.guid=e.guid AND s.spell=e.spell
ORDER BY e.guid,e.spell LIMIT 100;
'''
    if options.foreign_skill_mode:
        status += f'''SELECT COUNT(*) selected_skill_rows,COALESCE(SUM(s.skill IS NOT NULL),0) still_stored,
COALESCE(SUM(s.skill IS NULL),0) absent FROM `{batch.archive}`.expected_skills e
LEFT JOIN `{snapshot.source}`.character_skills s ON s.guid=e.guid AND s.skill=e.skill;
SELECT e.guid,e.skill,a.value AS archived_value,a.max AS archived_cap,s.skill IS NOT NULL AS still_stored
FROM `{batch.archive}`.expected_skills e JOIN `{batch.archive}`.character_skills_before a ON a.guid=e.guid AND a.skill=e.skill
LEFT JOIN `{snapshot.source}`.character_skills s ON s.guid=e.guid AND s.skill=e.skill ORDER BY e.guid,e.skill LIMIT 100;
'''
    if options.shaman_mode:
        status += f'''SELECT a.guid,a.skill,a.value,a.max AS archived_cap,s.skill IS NOT NULL AS still_stored
FROM `{batch.archive}`.character_skills_before a JOIN `{batch.archive}`.affected g ON g.guid=a.guid
LEFT JOIN `{snapshot.source}`.character_skills s ON s.guid=a.guid AND s.skill=a.skill WHERE a.skill=118 ORDER BY a.guid LIMIT 100;
'''
    if options.riding_mode:
        status += f'''SELECT a.guid,a.skill,a.value,a.max AS archived_cap,s.skill IS NOT NULL AS still_stored
FROM `{batch.archive}`.character_skills_before a JOIN `{batch.archive}`.affected g ON g.guid=a.guid
LEFT JOIN `{snapshot.source}`.character_skills s ON s.guid=a.guid AND s.skill=a.skill WHERE a.skill={148 if options.riding_horse else 149} ORDER BY a.guid LIMIT 100;
SELECT s.guid,s.skill,s.value,s.max AS current_cap FROM `{snapshot.source}`.character_skills s
JOIN `{batch.archive}`.affected g ON g.guid=s.guid WHERE s.skill=762 ORDER BY s.guid LIMIT 100;
'''
    if options.parent_mode:
        status += f'''SELECT p.guid,p.spell AS restored_parent,s.active,s.disabled
FROM `{batch.archive}`.expected_parents p LEFT JOIN `{snapshot.source}`.character_spell s ON s.guid=p.guid AND s.spell=p.spell ORDER BY p.guid;
SELECT s.guid,s.spell AS retained_axesmith,s.active,s.disabled FROM `{snapshot.source}`.character_spell s
JOIN `{batch.archive}`.affected g ON g.guid=s.guid WHERE s.spell=17041 ORDER BY s.guid;
'''
    if options.rekey_mode:
        status += f'''SELECT e.guid,e.from_spell,e.to_spell,s.active,s.disabled
FROM `{batch.archive}`.expected_rekeys e LEFT JOIN `{snapshot.source}`.character_spell s
ON s.guid=e.guid AND s.spell=e.to_spell ORDER BY e.guid,e.from_spell LIMIT 100;
'''
    if (options.pending_history or options.pending_death_coil
        or options.pending_defaults):
        manifest.update(numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=options.numeric_reader,
            world_guard_reader_sha256=options.world_guard_reader)
    values['RESET_STATE_TEST'] = ('(c.at_login & 4)=0'
        if options.pending_history or options.pending_death_coil
        or options.pending_ownership or options.pending_professions
        or options.pending_defaults else '(c.at_login & 4)<>0')
    if options.pending_history:
        manifest.update(pending_history_ack=trained_history.PENDING_ACK,
            pending_native_sources=options.pending_native_sources,
            pending_history_reader_sha256=sha(
                ROOT / 'lib/cleanup_trained_history.py'))
        values['WORLD_CHECKS'] = (
            "IF NOT (BINARY @pending_history_ack <=> BINARY '"
            f"{trained_history.PENDING_ACK}') THEN SIGNAL SQLSTATE "
            "'45000' SET MESSAGE_TEXT='Explicit pending-history "
            "acknowledgement required'; END IF;\n"
        ) + values['WORLD_CHECKS']
    if options.pending_death_coil:
        manifest.update(pending_death_coil_ack=death_coil.PENDING_ACK,
            pending_native_sources=options.pending_native_sources,
            pending_ordinary_reader_sha256=sha(
                ROOT / 'lib/cleanup_ordinary_history.py'),
            pending_death_coil_reader_sha256=sha(
                ROOT / 'lib/cleanup_death_coil.py'))
        values['WORLD_CHECKS'] = (
            "IF NOT (BINARY @pending_death_coil_ack <=> BINARY '"
            f"{death_coil.PENDING_ACK}') THEN SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT='Explicit pending Death Coil "
            "acknowledgement required'; END IF;\n"
        ) + values['WORLD_CHECKS']
    if options.pending_ownership:
        manifest.update(pending_ownership_ack=ownership.PENDING_ACK,
            pending_native_sources=options.pending_native_sources,
            numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=options.numeric_reader,
            world_guard_reader_sha256=options.world_guard_reader)
        values['WORLD_CHECKS'] = (
            "IF NOT (BINARY @pending_ownership_ack <=> BINARY '"
            f"{ownership.PENDING_ACK}') THEN SIGNAL SQLSTATE '45000' SET "
            "MESSAGE_TEXT='Explicit pending-ownership acknowledgement "
            "required'; END IF;\n"
        ) + values['WORLD_CHECKS']
    if options.pending_professions:
        manifest.update(pending_profession_ack=professions.PENDING_ACK,
            pending_native_sources=options.pending_native_sources)
        values['WORLD_CHECKS'] = (
            "IF NOT (BINARY @pending_profession_ack <=> BINARY '"
            f"{professions.PENDING_ACK}') THEN SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT='Explicit pending-profession "
            "acknowledgement required'; END IF;\n"
        ) + values['WORLD_CHECKS']
    if options.pending_defaults:
        manifest.update(
            pending_default_ack=ordinary_history.PENDING_DEFAULT_ACK,
            pending_native_sources=options.pending_native_sources,
            pending_ordinary_reader_sha256=sha(
                ROOT / 'lib/cleanup_ordinary_history.py'))
        values['WORLD_CHECKS'] = (
            "IF NOT (BINARY @pending_default_ack <=> BINARY '"
            f"{ordinary_history.PENDING_DEFAULT_ACK}') THEN SIGNAL "
            "SQLSTATE '45000' SET MESSAGE_TEXT='Explicit pending-default "
            "acknowledgement required'; END IF;\n"
        ) + values['WORLD_CHECKS']
    if options.overlevel_unselected:
        manifest.update(overlevel_ownership_ack=ownership.OVERLEVEL_ACK,
            numeric_fingerprint='EXACT_FRACTIONAL_V1',
            numeric_reader_sha256=options.numeric_reader,
            world_guard_reader_sha256=options.world_guard_reader)
        values['WORLD_CHECKS'] = (
            "IF NOT (BINARY @overlevel_ownership_ack <=> BINARY '"
            f"{ownership.OVERLEVEL_ACK}') THEN SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT='Explicit overlevel unselected-history "
            "acknowledgement required'; END IF;\n"
        ) + values['WORLD_CHECKS']
    rendered = render_text(batch.template, values)
    if options.specialization_mode:
        rendered = rendered.replace('ineligible ordinary',
            'inactive competing specialization')
    if options.skill_teaching_mode:
        rendered = rendered.replace('ineligible ordinary',
            'redundant skill-teaching wrapper')
    finish(settings, work, output, manifest, rendered,
        'guid\tspell\tactive\tdisabled\n' + ''.join('\t'.join(map(str,
            row)) + '\n' for row in selection.selected), status)
    (output / 'excluded-rows.tsv').write_text('guid\tspell\treason\n'
        + ''.join('\t'.join(map(str, row)) + '\n' for row
            in selection.excluded))
    if options.training_prerequisites:
        write_json(output / 'ordinary-training-proof.json',
            selection.training_proofs)
    if options.native_death_coil:
        write_json(output / 'native-base-review.json', {
            'policy': policy.policy,
            'configuration_contract': options.config_contract,
            'proofs': selection.native_base_proofs,
            'sql_spell_rows_inserted': 0, 'sql_skill_rows_changed': 0,
            'native_availability_change': 'Only rank 1 from existing Unholy skill; no higher-rank '
            'inference'})
    if options.rekey_mode:
        (output / 'spell-rekeys.tsv').write_text(
            'guid\tfrom_spell\tto_spell\n' + ''.join('\t'.join(map(str, row))
                + '\n' for row in selection.rekeys))
    if options.ownership_mode:
        write_json(output / 'ownership-native-proof.json',
            selection.ownership_native_proofs)
    if options.two_world_mode:
        write_json(output / ('obsolete-riding-native-proof.json'
            if options.riding_mode else 'specialization-native-proof.json'
            if options.specialization_mode
            else 'profession-activation-native-proof.json'
            if options.profession_mode else 'skill-teaching-native-proof.json'
            if options.skill_teaching_mode else 'shaman-native-proof.json'
            if options.shaman_mode else 'selected-passive-native-proof.json'
            if options.direct_mode else 'inactive-legacy-native-proof.json'
            if options.legacy_mode else 'pet-teaching-native-proof.json'
            if options.pet_mode else 'eligibility-native-proof.json'),
            selection.eligibility_proofs)
        write_json(output / 'target-metadata.json', policy.target_world)
    if options.reviewed_cower:
        write_json(output / 'cower-native-contract.json', options.cower_proof)
    if policy.include_scripts:
        script_family_column = ('ordinary_first_spell'
            if options.ordinary_mode else 'talent_entry')
        (output / 'scripted-family-review.tsv').write_text(
            script_family_column + '\tspell\tscript\tstatus\treason\n'
            + ''.join(
                '\t'.join(map(str, (family, spell, name, 'DEFERRED' if reason
                    else 'REVIEWED_NO_SPELLBOOK_MUTATION', reason))) + '\n'
                for family, spell, name, reason in selection.bindings))
    if policy.include_relations:
        family_column = ('ordinary_first_spell' if options.ordinary_mode
            or options.two_world_mode else 'talent_entry')
        (output / 'relationship-review.tsv').write_text('guid\t'
            + family_column + '\tspell\trole\tdisposition\tactive\tdisabled\n'
            +
            ''.join('\t'.join(map(str, r)) + '\n' for r
                in selection.relation_proof))
        selected_nodes = {r[2] for r in selection.relation_proof}
        (output / 'relationship-edges.tsv').write_text(
            'parent\tchild\trelationship\n' + ''.join(
                '\t'.join(map(str, r)) + '\n' for r in selection.relation_edges
                if r[0] in selected_nodes and r[1] in selected_nodes))
    if options.selected_mode:
        (output / 'selected-rank-review.tsv').write_text(
            'guid\tspell\ttalent_rank\tactive\tdisabled\ttalent_entry\t'
            'selected_spell_group_rank\tselected_spell_flags\tdecision\n' +
            ''.join('\t'.join(map(str, r)) + '\n' for r
                in selection.rank_proof))
    write_json(output / 'metadata.json', evidence.world)
    from cleanup_files import seal
    seal(output)
