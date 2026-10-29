"""Argument parsing for the cleanup console."""

from __future__ import annotations

import argparse
import os


def parser() -> argparse.ArgumentParser:
    """Build the existing CLI from focused command and policy registrations."""
    argument_parser = argparse.ArgumentParser(
        description='Audit and reviewed reversible cleanup of a stopped TrinityCore '
        'preparation copy.')
    argument_parser.add_argument('--config', default=os.environ.get(
        'MIGRATOR_CLEANUP_CONFIG', 'cleanup.ini'),
        help='Private INI file (default: ./cleanup.ini)')
    command_parsers = argument_parser.add_subparsers(dest='command',
        required=True)
    _add_session_commands(command_parsers)
    _add_plan_commands(command_parsers)
    _add_batch_commands(command_parsers)
    return argument_parser


def _add_session_commands(command_parsers: argparse._SubParsersAction) -> None:
    init = command_parsers.add_parser('init',
        help='Start a NEW session after importing fresh preparation '
        'databases; retain old sessions')
    init.add_argument('--label', default='')
    sessions = command_parsers.add_parser('sessions',
        help='List retained sessions or explicitly select one for '
        'inspection/restore')
    sessions.add_argument('--use',
        help='Session ID; must match the configured server and schemas')
    audit = command_parsers.add_parser('audit',
        help='Run read-only source audit; exit 1 means findings, not a failed '
        'audit')
    audit.add_argument('--scope', choices= ('talents', 'character-state',
        'all'), default='all')
    inspect = command_parsers.add_parser('inspect-items',
        help='Report zero-entry containers and their contents; no item '
        'deletion')
    history = command_parsers.add_parser('inspect-spell-history',
        help='Review direct talent history against both talent groups; no '
        'cleanup or preflight')
    history.add_argument('--audit',
        help='Full audit ID in this session; defaults to latest completed '
        'audit')
    blockers = command_parsers.add_parser('inspect-migration-blockers',
        help='Capture read-only source context for every character in a saved '
        'migration blocker TSV; no cleanup or preflight')
    blocker_scope = blockers.add_mutually_exclusive_group(required=True)
    blocker_scope.add_argument('--report',
        help='Path to saved spell-state-blockers.tsv from the migration '
        'toolkit')
    blocker_scope.add_argument('--all-characters', action='store_true',
        help='Capture the entire current source for preparation; no '
        'first-failure report or historical GUID filter')
    blockers.add_argument('--bundle', action='store_true',
        help='Also create a private tar.gz in the operation directory for '
        'offline review')


def _add_talents_plan(plan_parsers: argparse._SubParsersAction) -> None:
    talents = plan_parsers.add_parser('talents',
        help='Only verified TALENT_VALUE_IS_NOT_RANK_SPELL rows')
    talents.add_argument('--audit',
        help='Audit ID in this session; defaults to latest completed audit')
    talents.add_argument('--expect-rows', type=int, required=True)


def _add_skills_plan(plan_parsers: argparse._SubParsersAction) -> None:
    skills = plan_parsers.add_parser('skills',
        help='Clamp exact audited over-cap values to their existing positive '
        'stored maximum')
    skills.add_argument('--audit',
        help='Full audit ID in this session; defaults to latest completed '
        'audit')
    skills.add_argument('--expect-rows', type=int, required=True)


def _add_native_skills_plan(plan_parsers: argparse._SubParsersAction) -> None:
    native_skills = plan_parsers.add_parser('native-skills',
        help='Review insertion of missing native Generic/Runeforging skill '
        'rows from already known enabled spells')
    native_skills.add_argument('--migration-inspection',
        help='Sealed migration blocker context ID; defaults to latest '
        'captured context in this session')
    native_skills.add_argument('--skills', nargs='+', choices= ('generic',
        'runeforging', 'racial'), default= ['generic', 'runeforging'])
    native_policy = native_skills.add_mutually_exclusive_group()
    native_policy.add_argument('--normalize-generic', action='store_true',
        help='Opt in to v2: verified dual-spec teacher anchors and exact '
        'native level*5 normalization of existing Generic only; requires '
        '--skills generic')
    native_policy.add_argument('--known-racials', action='store_true',
        help='Separate v5: restore four fixed absent racial skills from '
        'existing legitimate known spells; explicitly allow verified '
        'stock racial rewards; requires --skills racial')
    native_policy.add_argument('--pending-generic', action='store_true',
        help='Separate v4: insert absent Generic only from enabled known 2382 '
        'on pending-reset characters; retain reset flags, talents and '
        'every spell; no reset execution')
    native_policy.add_argument('--known-generic-switch', action='store_true',
        help='Opt in to v3: insert absent Generic from verified enabled '
        'switch spells even with one spec; no spec grant or existing '
        'skill update; requires --skills generic')
    native_mode = native_skills.add_mutually_exclusive_group(required=True)
    native_mode.add_argument('--expect-rows', type=int,
        help='Exact eligible skill change count from preview')
    native_mode.add_argument('--preview', action='store_true',
        help='Review the captured selection without a SQL package, '
        'active-batch change or source writes')


def _add_disabled_talent_history_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    history = plan_parsers.add_parser('disabled-talent-history',
        help='Archive eligible disabled direct talent history; selected '
        'families and enabled spells excluded')
    evidence = history.add_mutually_exclusive_group(required=True)
    evidence.add_argument('--inspection',
        help='Retained spell-history inspection ID in this session')
    evidence.add_argument('--audit',
        help='Full audit ID in this session; create a fresh read-only '
        'spell-history inspection before planning')
    evidence.add_argument('--migration-inspection',
        help='Sealed migration blocker context ID or latest in this session; '
        'v6 trained ranks or explicit v7 talent children')
    history_review = history.add_mutually_exclusive_group(required=True)
    history_review.add_argument('--expect-review-rows', type=int,
        help='Exact candidate total for the chosen category; v7 uses the '
        'preview reviewed_candidate_rows, not selected rows or characters')
    history_review.add_argument('--preview', action='store_true',
        help='V7 only: review captured talent-child state without creating a '
        'SQL package or changing the active batch')
    history.add_argument('--orphaned-talent-children', action='store_true',
        help='Use v7 with --migration-inspection: wholly disabled unselected '
        'talent-child families, including absent direct/trained roots; '
        'enabled rows remain untouched')
    history.add_argument('--include-reviewed-scripts', action='store_true',
        help='Use v2 policy for families whose every binding has the '
        'protected NO_SPELLBOOK_MUTATION contract; other exclusions '
        'remain')
    history.add_argument('--include-inert-relations', action='store_true',
        help='Use v3 policy to archive isolated wholly disabled direct '
        'talent/rank/dependency groups, including exact related rows; '
        'implies reviewed scripts')
    history.add_argument('--include-reviewed-routes', action='store_true',
        help='Use v4 exact Berserk/Blast Wave teacher rules and inert shaman '
        '30798 root-only rule preserving 674/skill 118; implies v3 review')
    history.add_argument('--pending-reset-history', action='store_true',
        help='Separate v8: archive wholly disabled unselected talent families '
        'on pending-reset characters; retain selected ownership, enabled '
        'spells, skills and reset flags; no reset executed')
    history.add_argument('--selected-rank-history', action='store_true',
        help='Use v5 for disabled ranks selected by neither spec when another '
        'direct rank is selected; preserve all selected ranks; cannot '
        'combine with other modes')


def _add_disabled_spell_history_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    ordinary = plan_parsers.add_parser('disabled-spell-history',
        help='Opt-in archive of isolated wholly disabled ordinary ranks; '
        'preserve enabled and talent-linked families')
    ordinary.set_defaults(ordinary_spell_history=True, inspection=None,
        audit=None)
    ordinary.add_argument('--migration-inspection', required=True,
        help='Sealed migration-blocker inspection ID or latest in this session')
    ordinary_modes = ordinary.add_mutually_exclusive_group()
    ordinary_modes.add_argument('--pending-inactive-defaults',
        action='store_true',
        help='Separate pending-reset policy for wholly disabled Dash/Death '
        'Pact families under verified inactive custom defaults; no reset '
        'or login changes')
    ordinary_modes.add_argument('--inactive-custom-defaults',
        action='store_true',
        help='Explicit v2: allow inactive custom-start routes only with '
        '[source] player_start_all_spells=0; other guards remain')
    ordinary_modes.add_argument('--pending-native-death-coil',
        action='store_true',
        help='Separate pending-reset Death Coil rank-1 policy; retain all '
        'reset flags, selected talents and skills; no reset execution')
    ordinary_modes.add_argument('--native-death-coil', action='store_true',
        help='Separate v3: retire eligible disabled Death Coil training '
        'history, allowing native rank 1 from existing Unholy skill; '
        'requires player_start_all_spells=0')
    ordinary_modes.add_argument('--training-prerequisites',
        action='store_true',
        help='Separate v4: exact reviewed disabled ordinary training '
        'prerequisites; preserve enabled counterparts, skills and talents')
    ordinary_review = ordinary.add_mutually_exclusive_group(required=True)
    ordinary_review.add_argument('--preview', action='store_true',
        help='Read-only review; no SQL package, source change or active-batch '
        'change')
    ordinary_review.add_argument('--expect-review-rows', type=int,
        help='Exact reviewed_candidate_rows from this policy preview, '
        'including exclusions')


def _add_talent_ownership_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    ownership = plan_parsers.add_parser('talent-ownership',
        help='Explicit archived repair of conflicting enabled/disabled spell '
        'rows; preserve selected builds and native authorized state')
    ownership.set_defaults(talent_ownership=True, inspection=None, audit=None)
    ownership.add_argument('--migration-inspection', required=True,
        help='Sealed migration-blocker inspection ID or latest')
    ownership_policy = ownership.add_mutually_exclusive_group()
    ownership_policy.add_argument('--unselected-overlevel-talents',
        action='store_true',
        help='Separate policy: retire verified unselected talent history on '
        'level 81..255 characters with no selected builds; preserve '
        'exact level, skills and flags')
    ownership_policy.add_argument('--pending-reset-ownership',
        action='store_true',
        help='Separate ownership repair on pending-reset characters only; '
        'retain both selected builds, skills and reset flags; no reset '
        'execution')
    ownership_policy.add_argument('--foreign-class-families',
        action='store_true',
        help='Separate v2: retire only isolated unselected foreign-class '
        'talent families; retain shared skill spells and selected '
        'ownership')
    ownership_policy.add_argument('--native-passive-prefixes',
        action='store_true',
        help='Separate v3: retire disabled passive predecessors only with '
        'retained enabled authorized higher anchors; no missing child '
        'grants or talent/skill changes')
    ownership_policy.add_argument('--selected-direct-passives',
        action='store_true',
        help='Separate policy: retire unselected higher direct passive ranks; '
        'restore existing lower selected auras through native AC talent '
        'loading; both worlds required')
    ownership_policy.add_argument('--reconcile-shaman-offhand',
        action='store_true',
        help='Separate coupled spell/skill repair: retain verified shield or '
        'stow verified weapon into empty native backpack/bank slot; '
        'archive exact placement inverse; preserve pending reset flags')
    ownership_policy.add_argument('--unselected-shaman-dual-wield',
        action='store_true',
        help='Separate coupled repair: retire unselected Shaman spell 674 AND '
        'skill 118 only with an empty off-hand; --expect-rows counts '
        'pairs')
    ownership_policy.add_argument('--native-passive-rekey',
        action='store_true',
        help='Separate v5: rekey conflicting enabled passive child anchors '
        'downward to already-known active selected ranks; stock spell '
        'columns only')
    ownership_policy.add_argument('--reviewed-aura-aliases',
        action='store_true',
        help='Separate v4: retire isolated unselected paladin aura talent '
        'history under exact protected registration/helper contracts')
    ownership_review = ownership.add_mutually_exclusive_group(required=True)
    ownership_review.add_argument('--preview', action='store_true',
        help='Read-only complete captured-scope review; no active batch or '
        'SQL package')
    ownership_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows',
        help='Exact selected_rows printed by this policy preview')


def _add_obsolete_riding_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    riding = plan_parsers.add_parser('obsolete-riding',
        help='Archived paired retirement of forbidden Wolf Riding 825 and '
        'skill 149; retain modern Riding and mounts')
    riding.set_defaults(obsolete_riding=True, inspection=None, audit=None)
    riding.add_argument('--horse', action='store_true',
        help='Separate v3: forbidden legacy Horse Riding 824 AND skill 148, '
        'with retained modern riding and full native-invalid item guards')
    riding.add_argument('--native-invalid-items', action='store_true',
        help='Separate v2: retain verified missing-instance references and '
        'zero-entry instances unchanged; unknown nonzero templates still '
        'defer')
    riding.add_argument('--migration-inspection', required=True,
        help='Current sealed migration-blocker inspection ID or latest')
    riding_review = riding.add_mutually_exclusive_group(required=True)
    riding_review.add_argument('--preview', action='store_true',
        help='Read-only spell/skill/item requirement review; no SQL package')
    riding_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows',
        help='Exact selected spell/skill pairs from the current preview')


def _add_specialization_retirement_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    specialties = plan_parsers.add_parser('specialization-retirement',
        help='Separate archived retirement of inactive competitors to one '
        'verified active profession specialization')
    specialties.set_defaults(specialization_retirement=True, inspection=None,
        audit=None)
    specialties.add_argument('--native-invalid-items', action='store_true',
        help='Separate reviewed policy: retain exact '
        'missing-instance/zero-entry equipment rows; check all valid '
        'items and defer unknown nonzero templates')
    specialties.add_argument('--migration-inspection', required=True,
        help='Current sealed migration-blocker inspection ID or latest')
    specialty_review = specialties.add_mutually_exclusive_group(required=True)
    specialty_review.add_argument('--preview', action='store_true',
        help='Read-only specialization/equipped-item review; no SQL package')
    specialty_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows',
        help='Exact selected_rows from the current preview')


def _add_specialization_parent_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    parents = plan_parsers.add_parser('specialization-parent',
        help='Restore reviewed missing Weaponsmith parent, retain active '
        'Master Axesmith and retire three inactive competitors')
    parents.set_defaults(specialization_retirement=True,
        parent_specialization=True, inspection=None, audit=None)
    parents.add_argument('--native-invalid-items', action='store_true',
        help='Separate reviewed policy: retain exact '
        'missing-instance/zero-entry equipment rows; check all valid '
        'items and defer unknown nonzero templates')
    parents.add_argument('--migration-inspection', required=True,
        help='Current sealed migration-blocker inspection ID or latest')
    parent_review = parents.add_mutually_exclusive_group(required=True)
    parent_review.add_argument('--preview', action='store_true',
        help='Read-only review; no SQL package or source changes')
    parent_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows',
        help='Exact original selected rows from this preview, three per '
        'selected character')


def _add_profession_activation_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    professions = plan_parsers.add_parser('profession-activation',
        help='Separate archived activation of existing ordinary profession '
        'ranks; preserve skills and recipes')
    professions.set_defaults(profession_activation=True, inspection=None,
        audit=None)
    professions.add_argument('--pending-reset', action='store_true',
        help='Separate v2: activate reviewed existing ordinary profession '
        'ranks only on pending-reset characters; preserve every reset '
        'flag and selected talent')
    professions.add_argument('--migration-inspection', required=True,
        help='Current sealed migration-blocker inspection ID or latest')
    profession_review = professions.add_mutually_exclusive_group(required=True)
    profession_review.add_argument('--preview', action='store_true',
        help='Read-only review; no SQL package or active batch')
    profession_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows',
        help='Exact selected_rows from the current preview')


def _add_native_actions_plan(plan_parsers: argparse._SubParsersAction) -> None:
    actions = plan_parsers.add_parser('native-actions',
        help='Separate fixed native teacher, unusable specialization or '
        'transient combat spellbook retirement; no casts, grants or '
        'selected build changes')
    actions.set_defaults(foreign_skill_families=True, inspection=None,
        audit=None)
    actions.add_argument('--action', dest='native_action', choices= (
        'forbidden-pairs-stowing', 'forbidden-pairs', 'redundant-teachers',
        'obsolete-teachers', 'unusable-specializations', 'transient-combat'),
        required=True)
    actions.add_argument('--migration-inspection', required=True)
    action_review = actions.add_mutually_exclusive_group(required=True)
    action_review.add_argument('--preview', action='store_true')
    action_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows')


def _add_foreign_skill_families_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    foreign = plan_parsers.add_parser('foreign-skill-families',
        help='Retire complete forbidden native playerbook skill families AND '
        'corresponding stored skills; retain every selected talent and '
        'item; no grants')
    foreign.set_defaults(foreign_skill_families=True, inspection=None,
        audit=None)
    foreign.add_argument('--absent-training-actions', action='store_true',
        help='Separate v2: include verified pure training actions with '
        'native-forbidden children even if child rows are absent; no '
        'grants or casts')
    foreign.add_argument('--migration-inspection', required=True)
    foreign_review = foreign.add_mutually_exclusive_group(required=True)
    foreign_review.add_argument('--preview', action='store_true')
    foreign_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows')


def _add_dual_spec_teacher_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    dual = plan_parsers.add_parser('dual-spec-teacher',
        help='Retire unavailable dual-spec purchase wrapper on one-spec '
        'pending-reset characters; no spec or button grants')
    dual.set_defaults(dual_spec_teacher=True, inspection=None, audit=None)
    dual.add_argument('--migration-inspection', required=True)
    dual_review = dual.add_mutually_exclusive_group(required=True)
    dual_review.add_argument('--preview', action='store_true')
    dual_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows')


def _add_skill_teaching_plan(plan_parsers: argparse._SubParsersAction) -> None:
    teachers = plan_parsers.add_parser('skill-teaching',
        help='Archived retirement of redundant skill-step teaching wrappers; '
        'retain known taught spells and every skill')
    teachers.set_defaults(skill_teaching=True, inspection=None, audit=None)
    teachers.add_argument('--migration-inspection', required=True,
        help='Current sealed migration-blocker inspection ID or latest')
    teachers_review = teachers.add_mutually_exclusive_group(required=True)
    teachers_review.add_argument('--preview', action='store_true',
        help='Read-only review; no SQL package or active batch')
    teachers_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows',
        help='Exact selected_rows from the current preview')


def _add_pet_teaching_plan(plan_parsers: argparse._SubParsersAction) -> None:
    pet = plan_parsers.add_parser('pet-teaching',
        help='Archived retirement of verified player-side pet-teaching '
        'wrappers; preserve actual pets, talents and skills')
    pet.set_defaults(pet_teaching=True, inspection=None, audit=None)
    pet.add_argument('--migration-inspection', required=True,
        help='Sealed migration-blocker inspection ID or latest')
    pet.add_argument('--reviewed-cower', action='store_true',
        help='Separate v2 contract for exact reviewed Cower pet-child amount '
        'callbacks; other scripts still defer')
    pet_review = pet.add_mutually_exclusive_group(required=True)
    pet_review.add_argument('--preview', action='store_true',
        help='Read-only review; no SQL package or active batch')
    pet_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows',
        help='Exact selected_rows from this policy preview')


def _add_spell_eligibility_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    eligibility = plan_parsers.add_parser('spell-eligibility',
        help='Separate archived repair of ordinary rank families rejected by '
        'AC race/class validation')
    eligibility.set_defaults(spell_eligibility=True, inspection=None,
        audit=None)
    eligibility.add_argument('--migration-inspection', required=True,
        help='Sealed migration-blocker inspection ID or latest')
    eligibility_mode = eligibility.add_mutually_exclusive_group()
    eligibility_mode.add_argument('--reviewed-cast-scripts',
        action='store_true',
        help='Separate v6: ineligible ordinary families with protected '
        'NO_SPELLBOOK_MUTATION cast callbacks; retain all other route, '
        'skill, talent and ownership guards')
    eligibility_mode.add_argument('--inactive-foreign-actions',
        action='store_true',
        help='Separate v5: fixed inactive foreign Lockpicking action with '
        'absent skill and whole teacher chain; no grants')
    eligibility_mode.add_argument('--inactive-foreign-swipes',
        action='store_true',
        help='Separate v4: only inactive foreign Swipe ranks with absent Bear '
        'Form and Feral skill; no grants')
    eligibility_mode.add_argument('--reviewed-racials', action='store_true',
        help='Separate v3 fixed-catalog wrong-race racial retirement; no '
        'languages, riding or replacement racials')
    eligibility_mode.add_argument('--absent-teachers', action='store_true',
        help='Separate v2 contract for exact reviewed absent single-child '
        'teachers; other dependencies still defer')
    eligibility_review = eligibility.add_mutually_exclusive_group(
        required=True)
    eligibility_review.add_argument('--preview', action='store_true',
        help='Read-only review; no SQL package or active batch')
    eligibility_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows',
        help='Exact selected_rows from this policy preview')


def _add_inactive_legacy_spells_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    legacy = plan_parsers.add_parser('inactive-legacy-spells',
        help='Separate opt-in retirement of uncastable inactive legacy '
        'Bloodthirst book history; no active spell or talent changes')
    legacy.set_defaults(inactive_legacy=True, inspection=None, audit=None)
    legacy.add_argument('--migration-inspection', required=True,
        help='Sealed migration-blocker inspection ID or latest')
    legacy_review = legacy.add_mutually_exclusive_group(required=True)
    legacy_review.add_argument('--preview', action='store_true',
        help='Read-only review; no SQL package or active batch')
    legacy_review.add_argument('--expect-rows', type=int,
        dest='expect_review_rows',
        help='Exact selected_rows from this policy preview')


def _add_reset_talents_plan(plan_parsers: argparse._SubParsersAction) -> None:
    reset = plan_parsers.add_parser('reset-talents',
        help='One character: archive unavailable group 1 and queue free '
        'native reset')
    reset.add_argument('--guid', type=int, required=True)


def _add_reset_active_talents_plan(
    plan_parsers: argparse._SubParsersAction) -> None:
    active_reset = plan_parsers.add_parser('reset-active-talents',
        help='Queue one native active reset; inactive builds must be empty; '
        'archive explicit foreign talent 12284')
    active_reset.add_argument('--guid', type=int, required=True)
    active_reset.add_argument('--remove-spells', required=True)
    active_reset.add_argument('--expect-talent-rows', type=int, required=True)


def _add_items_plan(plan_parsers: argparse._SubParsersAction) -> None:
    items = plan_parsers.add_parser('items',
        help='Recover exact contents of selected zero-entry containers to '
        'native mail')
    items.add_argument('--containers', required=True,
        help='Comma-separated container GUIDs from inspect-items')


def _add_plan_commands(command_parsers: argparse._SubParsersAction) -> None:
    plans = command_parsers.add_parser('plan',
        help='Generate private SQL and a reviewable manifest; no source writes')
    plan_parsers = plans.add_subparsers(dest='kind', required=True)
    _add_talents_plan(plan_parsers)
    _add_skills_plan(plan_parsers)
    _add_native_skills_plan(plan_parsers)
    _add_disabled_talent_history_plan(plan_parsers)
    _add_disabled_spell_history_plan(plan_parsers)
    _add_talent_ownership_plan(plan_parsers)
    _add_obsolete_riding_plan(plan_parsers)
    _add_specialization_retirement_plan(plan_parsers)
    _add_specialization_parent_plan(plan_parsers)
    _add_profession_activation_plan(plan_parsers)
    _add_native_actions_plan(plan_parsers)
    _add_foreign_skill_families_plan(plan_parsers)
    _add_dual_spec_teacher_plan(plan_parsers)
    _add_skill_teaching_plan(plan_parsers)
    _add_pet_teaching_plan(plan_parsers)
    _add_spell_eligibility_plan(plan_parsers)
    _add_inactive_legacy_spells_plan(plan_parsers)
    _add_reset_talents_plan(plan_parsers)
    _add_reset_active_talents_plan(plan_parsers)
    _add_items_plan(plan_parsers)


def _add_batch_commands(command_parsers: argparse._SubParsersAction) -> None:
    for name in ('prepare', 'apply', 'restore', 'status'):
        action = command_parsers.add_parser(name, help={
            'prepare': 'Set up archive and snapshot originals; source unchanged',
            'apply': 'Execute the selected reviewed batch transaction',
            'restore': 'Exact inverse before gameplay/further changes',
            'status': 'Query authoritative archive states; --batch shows detailed '
            'status'} [name])
        action.add_argument('--batch',
            help='Batch ID in this session; prepare/apply/restore default to the '
            'selected plan')
