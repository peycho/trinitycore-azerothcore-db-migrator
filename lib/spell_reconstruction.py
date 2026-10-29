"""Per-character spell reconstruction and deterministic authorization
proofs.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, TYPE_CHECKING

from cleanup_types import (
    Character,
    Direction,
    Evidence,
    Skills,
    SpellBook,
    SpellResult,
    SpellResults,
    TalentMasks,
)
from spell_common import DUAL_WIELD, HIDDEN, LEARN, PASSIVE, SKILL_STEP, reject
from spell_rules import (
    assert_acyclic,
    consumed_teacher_rule,
    known_ranked_language_without_skill,
    known_runeforging_without_skill,
    native_passive_rule,
    ordinary_teacher_rule,
    ranked_world_talent_aura_rule,
    seal_rank_split_rule,
    world_talent_aura_rule,
)

if TYPE_CHECKING:
    from spell_metadata import Metadata


class SpellReconstruction:
    """Own one character reconstruction; never share working state across
    calls.
    """

    absent_runeforging_proofs: dict[int, Evidence]
    ac: Metadata
    active_group: int
    aura_helpers: dict[int, dict[int, int]]
    authorization: dict[int, int]
    authorization_owners: dict[int, dict[int, int]]
    character: Character
    class_mask: int
    cls: int
    consumed_teachers: dict[int, Evidence]
    direction: Direction
    groups: int
    inactive_skill_proofs: dict[int, Evidence]
    independent_routes: dict[int, list[tuple[Any, ...]]]
    known_rank_prefix: set[int]
    level: int | None
    native_passive_catalog: set[int]
    native_passive_owners: dict[int, dict[int, int]]
    ordinary_training_requirements: dict[int, Evidence | None]
    owners: dict[int, int]
    passive_higher_masks: dict[int, int]
    pending: deque[tuple[int, int, int, list[int], str]]
    persistent_dependencies: dict[int, list[int]]
    race: int
    race_mask: int
    ranked_aura_helpers: dict[int, Evidence]
    result: SpellResults
    seal_split: Evidence | None
    seeds: set[int]
    skill_delegates: dict[int, list[int]]
    skills: Skills
    source: Metadata
    source_passive_masks: dict[int, int]
    stored: SpellBook
    talents: TalentMasks
    target: Metadata
    tc: Metadata
    temporary_spells: set[int]
    world_aura_helpers: dict[int, Evidence]

    def __init__(
        self,
        character: Character,
        stored: SpellBook,
        talents: TalentMasks,
        skills: Skills,
        source: Metadata,
        target: Metadata,
        direction: Direction,
        level: int | None = None,
    ) -> None:
        self.character = character
        self.stored = stored
        self.talents = talents
        self.skills = skills
        self.source = source
        self.target = target
        self.direction = direction
        self.level = level

    def run(self) -> SpellResults:
        """Validate and reconstruct one character through ordered phases."""
        self._validate_ownership()
        self._resolve_aura_ownership()
        self._resolve_temporary_spells()
        self._authorize_talents()
        self._resolve_skill_delegation()
        self._seed_spells()
        self._expand_dependencies()
        self._finalize_results()
        return self.result

    def _validate_ownership(self) -> None:
        self.race, self.cls, self.active_group, self.groups = self.character
        if (not (1 <= self.race <= 32 and 1 <= self.cls <= 32 and self.groups
            in (1, 2) and 0 <= self.active_group < self.groups)):
            reject('INVALID_SPELL_CHARACTER_STATE', str(self.character))
        self.tc, self.ac = ((self.source, self.target) if self.direction
            == 'tc-to-ac' else(self.target, self.source))
        self.class_mask, self.race_mask = 1 << (self.cls - 1), 1 << (self.race
            - 1)
        self.owners = defaultdict(int)
        for spell, mask in self.talents.items():
            if (spell not in self.source.talents or spell not
                in self.target.talents or self.source.talents[spell]
                != self.target.talents[spell]):
                reject('INVALID_TALENT_OWNERSHIP', str(spell))
            for metadata in (self.source, self.target):
                row = metadata.talent_rows[spell]
                tab = metadata.stores['TalentTab'].get(row[1])
                if (not tab or not tab[20] & self.class_mask or not mask
                    or mask & ~((1 << self.groups) - 1)):
                    reject('INVALID_TALENT_OWNERSHIP',
                        f'{metadata.core}: {spell}: mask={mask}')
            self.owners[spell] |= mask
        selected = defaultdict(list)
        for spell, mask in self.owners.items():
            for group in range(self.groups):
                if mask & (1 << group):
                    selected[(self.tc.talents[spell][0], group)].append(spell)
        if any(len(values) > 1 for values in selected.values()):
            reject('CONFLICTING_TALENT_RANKS',
                'multiple selected ranks of one talent in one '
                'specialization')
        self.seeds = set(self.stored) | set(self.owners)
        for metadata in (self.tc, self.ac):
            assert_acyclic(metadata, self.seeds)

    def _resolve_aura_ownership(self) -> None:
        self.seal_split = None
        if (self.seeds & {20154, 21084} and self.tc.chain(21084)
            != self.ac.chain(21084)):
            self.seal_split = seal_rank_split_rule(self.tc, self.ac, self.cls)
        self.consumed_teachers = {}
        self.aura_helpers = defaultdict(dict)
        for spell in self.stored:
            if (self.tc.aura_owners.get(spell) or self.ac.aura_owners.get(
                spell)
                or spell in self.tc.world_aura_owners or spell
                in self.ac.world_aura_owners):
                reject('UNSUPPORTED_AURA_HELPER_SPELL_ROW',
                    f'{spell}: native aura/temporary state must not be '
                    'persisted')
        self.world_aura_helpers = {}
        for owner, mask in sorted(self.owners.items()):
            rule = world_talent_aura_rule(owner, self.tc, self.ac, self.cls)
            if rule:
                child = rule['children'][rule['owners'].index(owner)]
                self.aura_helpers[child][owner] = mask
                self.world_aura_helpers[child] = {'parent': owner,
                    'tc_active': 0, 'tc_dependent': True,
                    'ac_script': rule['script'], 'form_callbacks': rule[
                        'forms'],
                    'target_representation': 'AC_SELECTED_TALENT_AURA'
                    if self.direction == 'tc-to-ac'
                    else 'TC_NATIVE_DEPENDENT_RESTORE',
                    'native_lifetime': 'SELECTED_TALENT_ACTIVE_SPEC_AND_MATCHING_FORM'}
        self.ranked_aura_helpers = {}
        for owner, mask in sorted(self.owners.items()):
            ranked_rule = ranked_world_talent_aura_rule(owner, self.tc,
                self.ac, self.cls)
            bindings = []
            for metadata in (self.tc, self.ac):
                metadata.check_spell(owner)
                bindings.append({name: metadata.aura_talent_scripts[name][
                    'parents'][str(owner)]
                    for name in metadata.scripts[owner] if name
                    in metadata.aura_talent_scripts})
            if bindings[0] != bindings[1]:
                reject('INCOMPATIBLE_TALENT_AURA_SCRIPT',
                    f'{owner}: source/target bindings differ')
            for name, entry in bindings[0].items():
                child = entry['child']
                # A cast alone has no known-rank obligation. The optional
                # reviewed
                # TC world edge also learns a prefix; AC owns the exact helper
                # only.
                if self.tc.predecessors(child) != self.ac.predecessors(child):
                    reject('INCOMPATIBLE_TALENT_AURA_SCRIPT',
                        f'{owner}:{child}: helper ranks differ')
                self.aura_helpers[child][owner] = mask
                if ranked_rule:
                    self.ranked_aura_helpers[child] = {
                        'parent': owner, 'tc_active': 0, 'tc_dependent': True,
                        'tc_known_predecessors': list(self.tc.predecessors(
                            child)),
                        'ac_script': name, 'target_representation':
                        'AC_NATIVE_EXACT_TEMPORARY' if self.direction
                        == 'tc-to-ac'
                        else 'TC_NATIVE_DEPENDENT_PREFIX_RESTORE',
                        'native_lifetime': 'SELECTED_TALENT_ACTIVE_SPEC_HELPER_CAT_FORM',
                    }

    def _resolve_temporary_spells(self) -> None:
        self.temporary_spells = set()
        self.native_passive_owners = defaultdict(dict)
        self.native_passive_catalog = {spell for rule
            in self.tc.native_passive_ranks.values()
            for chain in rule['chains'] for spell
            in chain}
        for owner, mask in sorted(self.owners.items()):
            rule = native_passive_rule(owner, self.tc, self.ac, self.cls)
            if rule:
                for child in rule['children'][rule['owners'].index(owner)]:
                    self.native_passive_owners[child][owner] = mask
        temporary_queue = deque(child for owner in self.owners for child, _, _
            in self.ac.effect_learns[owner]
            if child not in self.ac.additional)
        while temporary_queue:
            child = temporary_queue.popleft()
            if child in self.temporary_spells:
                continue
            self.temporary_spells.add(child)
            effects = ([effect for effect in self.ac.spells[child][71:74]
                if effect])
            if LEARN in effects:
                if any(effect != LEARN for effect in effects):
                    reject('UNSUPPORTED_TEMPORARY_LEARN_EFFECT', str(child))
                temporary_queue.extend(row[0] for row in self.ac.effect_learns[
                    child])
            elif (self.tc.predecessors(child) and child not
                in self.native_passive_owners):
                reject('UNSUPPORTED_TEMPORARY_RANK_CHAIN', str(child))

    def _authorize_talents(self) -> None:
        self.authorization = defaultdict(int)
        self.authorization_owners = defaultdict(dict)
        queue = deque((spell, mask, spell) for spell, mask in sorted(
            self.owners.items()))
        while queue:
            spell, mask, owner = queue.popleft()
            new = mask & ~self.authorization_owners[spell].get(owner, 0)
            if not new:
                continue
            self.authorization[spell] |= new
            self.authorization_owners[spell][owner] = (
                self.authorization_owners[spell].get(owner, 0) | new)
            for child, _, _ in self.tc.effect_learns[spell]:
                if any(self.tc.spells[spell][71 + i] == LEARN
                    and self.tc.spells[spell][116 + i] == child
                    and self.tc.spells[spell][86 + i] == 5 for i in range(
                        3)):
                    continue
                queue.append((child, new, owner))
        for child, helper_owners in self.aura_helpers.items():
            for owner, mask in helper_owners.items():
                self.authorization[child] |= mask
                self.authorization_owners[child][owner] = mask
        if self.direction == 'ac-to-tc':
            for child, child_owners in self.native_passive_owners.items():
                for previous in self.tc.predecessors(child):
                    for owner, mask in child_owners.items():
                        self.authorization[previous] |= mask
                        self.authorization_owners[previous][owner] = (
                            self.authorization_owners[previous].get(owner, 0)
                            | mask)
        self.source_passive_masks = defaultdict(int)
        self.passive_higher_masks = defaultdict(int)
        for child, child_owners in self.native_passive_owners.items():
            for mask in child_owners.values():
                self.source_passive_masks[child] |= mask
                for previous in self.tc.predecessors(child):
                    self.source_passive_masks[previous] |= mask
                    self.passive_higher_masks[previous] |= mask

    def _resolve_skill_delegation(self) -> None:
        self.independent_routes = {}

        self.ordinary_training_requirements = {}


        self.known_rank_prefix = set(self.stored)
        for anchor in self.stored:
            if anchor not in self.tc.talents:
                # Do not use a source-only relationship to authorize anything.
                # Direct talent rank lists never establish lower talent
                # ownership.
                self.compatible(anchor)
                self.known_rank_prefix.update(self.tc.predecessors(anchor))

        self.skill_delegates = defaultdict(list)
        for parent, flags in sorted(self.stored.items()):
            rule = self.tc.skill_reward_dependencies.get(str(parent))
            if not rule or self.eligible(parent) != 3 or self.cls != 6:
                continue
            if (self.tc.spells[parent][71:74] != rule['parent_effects']
                or self.ac.spells[parent][71:74] != rule['parent_effects']):
                continue
            for child, active, auto in self.tc.learns[parent]:
                if child not in rule['children'] or not active or auto:
                    continue
                pairs = []
                for metadata in (self.tc, self.ac):
                    if metadata.spells[child][71:74] != rule['child_effects']:
                        break
                    abilities = [a for a in metadata.abilities[child]
                        if a[1] == rule['skill'] and a[4] == rule[
                            'class_mask']
                        and (not a[3] or a[3] & self.race_mask) and a[
                            9] == rule['acquire']
                        and a[7] == rule['minimum'] and not a[8]]
                    pairs.append({tuple(a[1:12]): a[0] for a in sorted(
                        abilities)})
                if len(pairs) != 2:
                    continue
                for relationship in sorted(pairs[0].keys() & pairs[1].keys()):
                    self.skill_delegates[child].append({'parent': parent,
                        'skill': rule['skill'],
                        'value': rule['value'], 'max': rule['max'],
                        'tc_ability': pairs[0][relationship],
                        'ac_ability': pairs[1][relationship], 'acquire': rule[
                            'acquire'], 'minimum': rule['minimum']})

        self.persistent_dependencies = defaultdict(list)

        self.inactive_skill_proofs = {}
        self.absent_runeforging_proofs = {}

        # Validate the selected parent even if a changed pet-target/learn
        # relation
        # would prevent its child from reaching add(). No changed relationship
        # may
        # silently turn a reviewed runtime child into an omitted spell.
        self.inactive_dual_wield(674, self.owners.get(30798, 0))

    def _seed_spells(self) -> None:
        self.result = {}

        # Selected direct talents are legitimate ownership, not evidence that
        # their trainable higher ability ranks have been learned.
        for spell, mask in sorted(self.owners.items()):
            self.add(spell, mask, spell, [spell], 'SELECTED_TALENT')
        self.pending = deque()
        for spell, flags in sorted(self.stored.items()):
            mask = self.eligible(spell)
            source_mask = (self.source_passive_masks.get(spell, mask)
                if self.direction == 'tc-to-ac' else mask)
            if not source_mask:
                root = self.tc.first(spell)
                family = self.tc.talents.get(spell, self.tc.talents.get(root))
                selected_family = [(s, m) for s, m in sorted(self.owners.items(
                ))
                    if m and family and self.tc.talents[s][0]
                    == family[0]]
                required = self.tc.requires[spell] | self.ac.requires[spell]
                reason = ('UNAUTHORIZED_TALENT_SPELL'
                    if self.talent_restricted(spell)
                    or any(self.talent_restricted(parent) for parent
                        in required)
                    else 'MISSING_SPELL_PREREQUISITE')
                reject(reason,
                    f'{spell}: stored_flags={flags}; rank_root={root}; '
                    f'selected_same_talent={selected_family}; '
                    f'eligible_mask=0; required_spells={sorted(required)}'
                    '; known_prerequisites='
                    f'{sorted(required & self.known_rank_prefix)}')
            if self.direction == 'tc-to-ac':
                active, disabled = flags
                if active not in (0, 1) or disabled not in (0, 1):
                    reject('INVALID_TC_SPELL_FLAGS', str(spell))
                if disabled:
                    if (source_mask == 3 or source_mask & (
                        1 << self.active_group) or not source_mask):
                        reject('UNREPRESENTABLE_DISABLED_SPELL', str(spell))
                elif not source_mask & (1 << self.active_group):
                    reject('TC_SPELL_OWNERSHIP_CONFLICT', str(spell))
                if not active:
                    higher = [s for s in self.stored if spell
                        in self.tc.predecessors(s) and self.stored[s][0]
                        and self.stored[s][1] == disabled
                        and self.eligible(s) & mask == mask]
                    superseded_mask = (source_mask if disabled
                        else 1 << self.active_group)
                    native_superseded = (spell in self.source_passive_masks
                        and self.passive_higher_masks[spell]
                        & superseded_mask == superseded_mask)
                    seal_superseded = (self.seal_split and spell == 20154
                        and 21084 in higher)
                    # TC AddSpell's initial passive-cast branch ignores
                    # `active`;
                    # disabled already returned above. Exact reviewed hidden
                    # child
                    # ranks selected in the active build therefore retain their
                    # native aura behavior with active=0. Ordinary spells still
                    # require supersession; no parent-only child grant is
                    # inferred.
                    native_inactive = (not disabled and spell
                        in self.native_passive_owners
                        and bool(mask & (
                            1 << self.active_group)))
                    if ((self.tc.stackable(spell) or self.ac.stackable(spell))
                        and not seal_superseded
                        or (not higher and not native_superseded)):
                        # Direct hidden/passive talent rows are represented by
                        # AC's talent loader, not an inferred active spell.
                        if (not native_inactive and (spell not in self.owners
                            or not self.ac.spells[spell][4] & (PASSIVE
                                | HIDDEN))):
                            reject('UNREPRESENTABLE_INACTIVE_SPELL', str(
                                spell))
                if not mask and spell in self.source_passive_masks:
                    # Approved TC-only predecessor. Its exact source row and
                    # masks
                    # are retained on the owning native child's provenance
                    # below.
                    continue
            else:
                original_mask = flags[0]
                if (not original_mask or original_mask & ~3 or original_mask
                    != mask):
                    reject('UNREPRESENTABLE_AC_SPELL_MASK',
                        f'{spell}: stored={original_mask}; eligible='
                        f'{mask}')
            self.pending.append((spell, mask, spell, [spell], 'STORED_SPELL'))

    def _expand_dependencies(self) -> None:
        for owner, mask in sorted(self.owners.items()):
            if ({row[0] for row in self.tc.effect_learns[owner]} != {row[0]
                for row in self.ac.effect_learns[owner]}):
                reject('INCOMPATIBLE_TALENT_LEARN_EFFECT', str(owner))
            for child, _, _ in self.tc.effect_learns[owner]:
                if any(self.tc.spells[owner][71 + i] == LEARN
                    and self.tc.spells[owner][116 + i] == child
                    and self.tc.spells[owner][86 + i] == 5
                    for i in range(3)):
                    # Pet teaching effects cannot authorize a player spell.
                    continue
                self.pending.append((child, mask, owner, [owner, child],
                    'TALENT_LEARN_EFFECT'))
        for child, helper_owners in sorted(self.aura_helpers.items()):
            for owner, mask in sorted(helper_owners.items()):
                self.pending.append((child, mask, owner, [owner, child],
                    'TC_WORLD_RANKED_TALENT_AURA' if child
                    in self.ranked_aura_helpers else
                    'TC_WORLD_TALENT_AURA' if child
                    in self.world_aura_helpers else 'NATIVE_TALENT_AURA'))
        visited = set()
        while self.pending:
            spell, mask, anchor, path, reason = self.pending.popleft()
            key = (spell, mask, anchor)
            if key in visited:
                continue
            visited.add(key)
            self.add(spell, mask, anchor, path, reason)
            if spell in self.aura_helpers:
                # Cast-only helpers have no TC known-rank obligation. Reviewed
                # world helpers have verified singleton/exact-rank contracts
                # and
                # no outgoing routes; their TC-only prefixes remain
                # native-owned.
                continue
            # Direct talent rank lists must never be expanded.
            if (spell not in self.tc.talents and not (self.direction
                == 'tc-to-ac' and spell in self.native_passive_owners)):
                for previous in self.tc.predecessors(spell)[-1:]:
                    self.pending.append((previous, mask, anchor, path + [
                        previous], 'LOWER_RANK'))
            for child, child_active, auto in self.tc.learns[spell]:
                if not auto:
                    skill_reward = any(r['parent'] == spell for r
                        in self.skill_delegates.get(child, []))
                    native = (any(row[0] == child for row
                        in self.ac.effect_learns[spell]) or child
                        in self.tc.predecessors(spell) or skill_reward)
                    world_aura = (child in self.world_aura_helpers
                        and self.world_aura_helpers[child]['parent'] == spell)
                    ranked_aura = (child in self.ranked_aura_helpers
                        and self.ranked_aura_helpers[child]['parent'] == spell)
                    native = native or world_aura or ranked_aura
                    persistent = (not native
                        and self.persistent_world_dependency(spell, child))
                    if not native and not persistent:
                        reject('UNSUPPORTED_DEPENDENT_LEARN',
                            f'{spell}:{child}: no verified native AC '
                            'dependency')
                    if (not child_active and child not in self.tc.talents
                        and not self.ac.spells[child][4] & HIDDEN):
                        reject('UNREPRESENTABLE_INACTIVE_DEPENDENCY',
                            f'{spell}:{child}')
                    self.pending.append((child, mask, anchor, path + [child],
                        'TC_WORLD_RANKED_TALENT_AURA'
                        if ranked_aura else
                        'TC_WORLD_TALENT_AURA' if world_aura else
                        'TC_WORLD_PERSISTENT_DEPENDENCY'
                        if persistent else 'TC_DEPENDENT_LEARN'))
            # Passive non-talent learn effects run during TC loading even when
            # its world learn map is empty. Conditional aura/stance casts
            # cannot
            # be inferred from a stored spell row alone.
            if (spell not in self.tc.talents and self.tc.spells[spell][4]
                & PASSIVE):
                for child, _, _ in self.tc.effect_learns[spell]:
                    if self.tc.spells[spell][12] or self.tc.spells[spell][20]:
                        reject('CONDITIONAL_DEPENDENT_LEARN', str(spell))
                    if (child not in {row[0] for row in self.ac.effect_learns[
                        spell]}):
                        reject('UNSUPPORTED_DEPENDENT_LEARN',
                            f'{spell}:{child}')
                    if any(self.tc.spells[spell][71 + i] == LEARN
                        and self.tc.spells[spell][116 + i] == child
                        and self.tc.spells[spell][86 + i] == 5 for i in range(
                            3)):
                        continue
                    self.pending.append((child, mask, anchor, path + [child],
                        'PASSIVE_LEARN_EFFECT'))
            if (len(visited) > len(self.tc.spells) * max(len(self.seeds),
                1) * 3):
                reject('SPELL_TRAVERSAL_BOUND', str(spell))

    def _finalize_results(self) -> None:
        for spell, row in self.result.items():
            self._validate_autolearn_skill(spell, row)
            self._authorize_result(spell, row)
            self._attach_native_proofs(spell, row)
            self._attach_talent_proofs(spell, row)
            self._finalize_flags(spell, row)

    def _validate_autolearn_skill(self, spell: int, row: SpellResult) -> None:
        for ability in self.ac.abilities[
            spell] if spell not in self.inactive_skill_proofs else():
            skill = ability[1]
            if ((ability[9] == 2 or (skill in (633, 776) and ability[10]
                == 0)) and skill not in self.skills):
                proof = known_ranked_language_without_skill(spell, skill,
                    self.character, self.stored, self.skills, self.tc,
                    self.ac, self.direction)
                if proof is None:
                    reject('SPELL_WOULD_ADD_SKILL',
                        f'{spell}: skill={skill}')
                row.setdefault('native_skill_noops', []).append(proof)

    def _authorize_result(self, spell: int, row: SpellResult) -> None:
        row['proofs'].sort()
        row['original'] = list(self.stored.get(spell, ()))
        authorized_by = ({} if spell in self.aura_helpers else
            dict(self.authorization_owners.get(self.tc.first(
                spell), {})))
        authorized_by.update(self.authorization_owners.get(spell, {}))
        if spell in self.native_passive_owners:
            authorized_by = dict(self.authorization_owners[spell])
        requirements = sorted(self.tc.requires[spell] | self.ac.requires[
            spell])
        for prerequisite in requirements:
            authorized_by.update(self.authorization_owners.get(
                prerequisite, {}))
            authorized_by.update(self.authorization_owners.get(
                self.tc.first(prerequisite), {}))
        row['authorization'] = {
            'policy': 'TALENT_AND_REQUIREMENT_AUTHORIZATION'
            if authorized_by or requirements else 'ORDINARY_BOTH_SPECS',
            'rank_root': self.tc.first(spell), 'owner_masks': sorted(
                authorized_by.items()),
            'required_spells': requirements,
        }

    def _attach_native_proofs(self, spell: int, row: SpellResult) -> None:
        if row.get('native_skill_noops'):
            row['authorization']['absent_ranked_language_skill'] = row.pop(
                'native_skill_noops')
        if spell in self.absent_runeforging_proofs:
            row['authorization']['absent_runeforging_skill'] = (
                self.absent_runeforging_proofs[spell])
        if spell in self.inactive_skill_proofs:
            row['authorization']['policy'] = 'NATIVE_INACTIVE_TALENT_SKILL'
            row['authorization']['inactive_talent_skill'] = (
                self.inactive_skill_proofs[spell])
        training = self.training_only_requirements(spell)
        if training:
            row['authorization'][
                'policy'] = 'ORDINARY_TRAINING_PREREQUISITES'
            row['authorization']['training_prerequisites'] = training
        routes = self.independent_skill_routes(spell)
        if routes:
            row['authorization']['policy'] = 'ORDINARY_SKILL_AUTHORIZATION'
            row['authorization']['independent_skill_routes'] = routes
        if spell in self.skill_delegates:
            row['authorization']['policy'] = 'NATIVE_SKILL_REWARD'
            row['authorization']['native_skill_rewards'] = (
                self.skill_delegates[spell])
        if spell in self.aura_helpers:
            row['authorization']['policy'] = 'NATIVE_TALENT_AURA'
            row['authorization']['aura_owners'] = sorted(self.aura_helpers[
                spell].items())
        if spell in self.world_aura_helpers:
            row['authorization']['policy'] = 'TC_WORLD_NATIVE_TALENT_AURA'
            row['authorization']['world_talent_aura'] = (
                self.world_aura_helpers[spell])
        if spell in self.ranked_aura_helpers:
            row['authorization'][
                'policy'] = 'TC_WORLD_NATIVE_RANKED_TALENT_AURA'
            row['authorization']['ranked_world_talent_aura'] = (
                self.ranked_aura_helpers[spell])
        if spell in self.consumed_teachers:
            row['authorization']['policy'] = ('CONSUMED_ORDINARY_TEACHER'
                if str(spell) in self.tc.ordinary_teachers
                else 'CONSUMED_DUAL_SPEC_TEACHER')
            row['authorization']['consumed_teacher'] = (
                self.consumed_teachers[spell])
        teacher_sources = ([parent for parent, proof
            in self.consumed_teachers.items() if spell in proof[
                'children']])
        if teacher_sources:
            row['authorization'][
                'consumed_teacher_sources'] = teacher_sources
        if spell in self.persistent_dependencies:
            row['authorization']['persistent_world_dependencies'] = sorted(
                self.persistent_dependencies[spell], key=lambda item: (
                    item['parent'], item['child']))

    def _attach_talent_proofs(self, spell: int, row: SpellResult) -> None:
        if spell in self.native_passive_owners:
            row['authorization']['native_passive_rank'] = {
                'policy': 'NATIVE_AC_EXACT_PASSIVE_RANK',
                'owner_masks': sorted(self.native_passive_owners[
                    spell].items()),
                'tc_predecessors': list(self.tc.predecessors(spell)),
                'tc_known_mask': self.source_passive_masks[spell],
                'stored_predecessors': [[previous, *self.stored[previous]]
                    for previous in self.tc.predecessors(spell)
                    if previous in self.stored],
                'target_predecessors_persisted': any(self.result[p][
                    'disposition'] == 'PERSISTENT'
                    for p in self.tc.predecessors(spell) if p
                    in self.result),
                'target_representation': 'AC_NATIVE_EXACT'
                if self.direction == 'tc-to-ac'
                else 'TC_ACTIVE_EXACT_NATIVE_PREFIX',
                'native_lifetime': 'SELECTED_TALENT_AND_ACTIVE_SPEC',
                'inactive_source_passive_cast': self.direction
                == 'tc-to-ac' and self.stored.get(spell) == (0, 0),
            }
        aura_contracts = sorted(
            (metadata.core, name, metadata.aura_talent_scripts[name][
                'mode'],
                metadata.aura_talent_scripts[name]['parents'][str(spell)][
                    'child'])
            for metadata in (self.tc, self.ac) for name
            in metadata.scripts[spell]
            if name in metadata.aura_talent_scripts)
        if aura_contracts:
            row['authorization']['aura_script_contracts'] = aura_contracts
        load_contracts = sorted(
            (metadata.core, name, 'CAST_ONLY_RESEARCH_EXISTING_SKILL',
                metadata.cast_only_scripts[name]['spell_skills'][str(
                    spell)])
            for metadata in (self.tc, self.ac) for name
            in metadata.scripts[spell]
            if str(spell) in metadata.cast_only_scripts.get(name, {}).get(
                'spell_skills', {}))
        if load_contracts:
            row['authorization']['load_script_contracts'] = load_contracts

    def _finalize_flags(self, spell: int, row: SpellResult) -> None:
        row['derived'] = spell not in self.stored
        if self.seal_split and spell in (20154, 21084):
            row['authorization']['seal_rank_split'] = self.seal_split
        row['active'] = 1
        row['disabled'] = int(not row['mask'] & (1 << self.active_group))
        if self.direction == 'ac-to-tc' and not self.tc.stackable(spell):
            if any(spell in self.tc.predecessors(other) and other_row[
                'mask'] & (1 << self.active_group)
                for other, other_row in self.result.items()):
                row['active'] = 0

    def compatible(self, spell: int) -> None:
        self.tc.check_spell(spell)
        self.ac.check_spell(spell)
        source_prefix, target_prefix = self.tc.predecessors(
            spell), self.ac.predecessors(spell)
        if (spell in (20154, 21084) and source_prefix != target_prefix
            and self.seal_split is None):
            self.seal_split = seal_rank_split_rule(self.tc, self.ac, self.cls)
        # An AC-only rank prefix is harmless for a hidden/passive child that
        # native talents own temporarily, provided TC knows no preceding rank.
        # No persistent row or target predecessor is granted by this exception.
        runtime_exact = (spell in self.temporary_spells and not source_prefix
            and bool(self.tc.spells[spell][4] & (PASSIVE
                | HIDDEN)))
        split_seal = self.seal_split and spell in (20154, 21084)
        if (source_prefix != target_prefix and not runtime_exact
            and not split_seal):
            reject('INCOMPATIBLE_SPELL_CHAIN',
                f'{spell}: tc_predecessors={source_prefix}; '
                f'ac_predecessors={target_prefix}; stored_flags='
                f'{self.stored.get(spell)}; selected_learn_owners='
                f'{sorted(self.authorization_owners.get(spell, {}).items())}')
        if (spell in self.tc.talents) != (spell in self.ac.talents):
            reject('INCOMPATIBLE_TALENT_CLASSIFICATION', str(spell))
        if self.tc.skill_effect(spell) != self.ac.skill_effect(spell):
            reject('INCOMPATIBLE_SKILL_EFFECT', str(spell))
        if ((self.tc.spells[spell][4] & (PASSIVE | HIDDEN)) != (self.ac.spells[
            spell][4] & (PASSIVE | HIDDEN))):
            reject('INCOMPATIBLE_SPELL_VISIBILITY', str(spell))

    def independent_skill_routes(self, spell: int) -> list[tuple[Any, ...]]:
        """Prove a native ordinary route despite another class's talent
        learn.

        This authorizes only a reached known spell, never a skill-based
        grant. Existing skill values/caps are still checked by add().
        Require matching TC/AC skill rewards, explicit class masks and
        trainable race/class skill metadata; an applicable or unknown
        talent owner keeps its restrictions.
        """
        if spell in self.independent_routes:
            return self.independent_routes[spell]
        self.independent_routes[spell] = []
        candidates = []
        for metadata in (self.tc, self.ac):
            if (spell in metadata.talents or metadata.first(spell)
                in metadata.talents):
                return []
            catalog_owners = (metadata.talent_learn_owners.get(spell, set())
                | metadata.talent_learn_owners.get(
                    metadata.first(spell), set()))
            if not catalog_owners:
                return []
            for owner in catalog_owners:
                tab = metadata.stores['TalentTab'].get(metadata.talent_rows[
                    owner][1])
                if not tab or not tab[20] or tab[20] & self.class_mask:
                    return []
            routes = {}
            for ability in metadata.abilities[spell]:
                if (ability[9] not in (1, 2) or not ability[4]
                    & self.class_mask
                    or (ability[3] and not ability[3] & self.race_mask)):
                    continue
                for info in metadata.stores['SkillRaceClassInfo'].values():
                    if (info[1] != ability[1] or not info[3] & self.class_mask
                        or (info[2] and not info[2] & self.race_mask)
                        or info[4] & 0x100):
                        continue
                    # Compare all relevant relationships, including acquisition
                    # thresholds and trainability, rather than only table IDs.
                    key = tuple(ability[1:10] + info[1:7])
                    routes[key] = [metadata.core, ability[0], info[0], ability[
                        1], ability[9], ability[7], info[4]]
            candidates.append(routes)
        common = sorted(candidates[0].keys() & candidates[1].keys())
        self.independent_routes[spell] = ([routes[key] for key in common
            for routes in candidates])
        return self.independent_routes[spell]

    def talent_restricted(
        self,
        spell: int,
        include_requirements: bool = True,
    ) -> bool:
        ordinary_route = self.independent_skill_routes(spell)
        return any(spell in metadata.talents or metadata.first(spell)
            in metadata.talents
            or ((metadata.talent_learn_owners.get(spell)
                or metadata.talent_learn_owners.get(metadata.first(
                    spell))) and not ordinary_route)
            or metadata.aura_owners.get(spell)
            or (include_requirements and (spell in metadata.additional
                or metadata.first(spell)
                in metadata.additional))
            for metadata in (self.tc, self.ac))

    def training_only_requirements(self, spell: int) -> Evidence | None:
        """Native loaders preserve known ordinary spells without learning
        prerequisites.

        AC GetLearnSpellSpecMask returns BOTH before inspecting
        requirements for ordinary spells. Keep every talent-linked
        relationship on the existing strict authorization path,
        including indirect prerequisite ancestry.
        """
        if spell in self.ordinary_training_requirements:
            return self.ordinary_training_requirements[spell]
        requirements = self.tc.requires[spell] | self.ac.requires[spell]
        self.ordinary_training_requirements[spell] = None
        if not requirements or self.talent_restricted(spell):
            return None
        pending = [(required, False) for required in sorted(requirements)]
        visited, visiting = set(), set()
        while pending:
            required, leaving = pending.pop()
            if leaving:
                visiting.discard(required)
                visited.add(required)
                continue
            if required in visiting:
                reject('CYCLIC_SPELL_RELATIONSHIP', str(required))
            if required in visited:
                continue
            if self.talent_restricted(required):
                return None
            visiting.add(required)
            pending.append((required, True))
            pending.extend((parent, False) for parent in sorted(
                self.tc.requires[required] | self.ac.requires[required]))
            if len(visiting) > max(len(self.tc.spells), len(self.ac.spells)):
                reject('SPELL_TRAVERSAL_BOUND', str(spell))
        proof = {'policy': 'NATIVE_ORDINARY_KNOWN_STATE',
            'tc_required_spells': sorted(self.tc.requires[spell]),
            'ac_required_spells': sorted(self.ac.requires[spell]),
            'ordinary_ancestry': sorted(visited),
            'missing_from_known_state': sorted(requirements
                - self.known_rank_prefix),
            'prerequisites_granted': False}
        self.ordinary_training_requirements[spell] = proof
        return proof

    def eligible(self, spell: int) -> int:
        if spell in self.aura_helpers or spell in self.native_passive_catalog:
            # Native ownership follows the exact selected child, not another
            # rank selected in the other spec. Reverse authorization may also
            # include the TC-only prefix explicitly restored above.
            return self.authorization.get(spell, 0)
        root = self.tc.first(spell)
        if spell in self.tc.talents:
            return self.owners.get(spell, 0)
        mask = (self.authorization.get(root, 0) or self.authorization.get(
            spell, 0))
        dependencies = self.tc.requires[spell] | self.ac.requires[spell]
        if self.training_only_requirements(spell):
            return 3
        if dependencies:
            required_mask = 3
            for prerequisite in dependencies:
                if self.talent_restricted(prerequisite):
                    required_mask &= (self.authorization.get(prerequisite, 0)
                        or self.authorization.get(self.tc.first(prerequisite),
                            0))
                else:
                    # A prerequisite may be a trained spell, but it may not
                    # manufacture authorization for a talent-based ability.
                    # TC may persist only a higher rank of this prerequisite.
                    # Count its verified known prefix, not just stored rows.
                    required_mask &= (3 if prerequisite
                        in self.known_rank_prefix else 0)
            # A talent requirement can itself authorize an otherwise ordinary
            # spell. Ordinary prerequisites cannot authorize an unowned talent
            # or learned child just because they are known.
            fallback = (0 if self.talent_restricted(spell,
                include_requirements=False) else 3)
            mask = (mask or fallback) & required_mask
        talent_based = self.talent_restricted(spell)
        return mask if talent_based or dependencies else 3

    def persistent_world_dependency(self, parent: int, child: int) -> bool:
        rule = self.tc.persistent_world_dependencies.get(str(parent))
        if (not rule or rule != self.ac.persistent_world_dependencies.get(str(
            parent))
            or child != rule['child'] or self.cls != rule['class']
            or self.talent_restricted(parent) or self.talent_restricted(
                child)
            or self.eligible(parent) != 3 or self.eligible(child) != 3
            or self.tc.learns[parent].count((child, 1, False)) != 1):
            return False
        ranks = rule['ranks']
        for metadata in (self.tc, self.ac):
            if (metadata.spells[parent][71:74] != rule['parent_effects']
                or metadata.spells[parent][95:98] != rule['parent_auras']
                or metadata.spells[parent][4] & (PASSIVE | HIDDEN)
                or metadata.skill_effect(parent) is not None
                or list(metadata.predecessors(child)) + [child] != ranks
                or metadata.stores['SkillLine'].get(rule['skill'], [0, 0])[
                    1] != rule['skill_category']):
                return False
            for step, rank in enumerate(ranks, 1):
                if (metadata.spells[rank][71:74] != rule['child_effects']
                    or metadata.skill_effect(rank) != (rule['skill'], step,
                        step * 75, step * 75)
                    or rank in metadata.talents
                    or metadata.spells[rank][4] & (PASSIVE | HIDDEN)
                    != rule['child_visibility']
                    or rank in self.temporary_spells or rank
                    in self.aura_helpers
                    or self.talent_restricted(rank) or self.eligible(rank)
                    != 3):
                    return False
        skill = rule['skill']
        if skill not in self.skills:
            reject('SPELL_WOULD_ADD_SKILL',
                f'{parent}:{child}: existing riding skill={skill} '
                'required')
        if (list(self.skills[skill]) not in rule['skill_states']
            or (self.skills[skill][0] > 225 and rule['higher_anchor'] not
                in self.known_rank_prefix)):
            reject('SPELL_WOULD_CHANGE_SKILL',
                f'{parent}:{child}: skill={skill}; stored='
                f'{self.skills[skill]}; requires riding 225/225 or '
                '300/300 with a known higher riding anchor')
        proof = {'parent': parent, 'child': child,
            'policy': 'TC_WORLD_LOAD_PERSISTENT_RIDING',
            'skill': skill, 'skill_category': rule['skill_category'],
            'stored_skill': list(self.skills[skill]), 'ranks': ranks}
        if proof not in self.persistent_dependencies[child]:
            self.persistent_dependencies[child].append(proof)
        return True

    def inactive_dual_wield(self, spell: int, mask: int) -> Evidence | None:
        """An inactive Shaman talent does not load its child or create a
        skill.

        This is deliberately limited to the stock 30798 -> 674
        relationship. Stored child rows, active/shared ownership and
        other skill effects keep the normal preservation checks. Both
        native talent loaders defer the inactive build; switching specs
        remains the cores' responsibility.
        """
        if (spell != 674 or self.cls != 7 or self.groups != 2 or spell
            in self.stored or 118 in self.skills
            or mask != 1 << (1 - self.active_group) or self.owners.get(
                30798) != mask):
            return None
        if (spell not in self.temporary_spells
            or self.authorization_owners.get(spell) != {30798: mask}):
            reject('INCOMPATIBLE_INACTIVE_TALENT_SKILL',
                '30798:674: native child authorization differs')
        for metadata in (self.tc, self.ac):
            parent, child = metadata.spells[30798], metadata.spells[674]
            if (metadata.talents.get(30798) != (1690, 1)
                or parent[71:74] != [LEARN, 0, 0] or parent[116:119] != [
                    674, 0, 0]
                or parent[86:92] != [1, 0, 0, 0, 0, 0]
                or child[4:13] != [80, 0, 0, 0, 0, 0, 0, 0, 0]
                or child[71:74] != [DUAL_WIELD, 0, 0]
                or child[86:98] != [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
                or any(child[110:119]) or metadata.skill_effect(674) != (
                    118, 1, 1, 1)
                or metadata.stores['SkillLine'].get(118, [0, 0])[1] != 6
                or metadata.scripts[30798] or metadata.scripts[674]
                or metadata.predecessors(30798) or metadata.predecessors(
                    674)
                or metadata.requires[30798] or metadata.requires[674]
                or metadata.learns[674] or 674 in metadata.additional
                or metadata.aura_owners.get(674)
                or metadata.learns[30798] != [(674, True, True)]):
                reject('INCOMPATIBLE_INACTIVE_TALENT_SKILL',
                    '30798:674: native Dual Wield contract differs')
        proof = {'policy': 'NATIVE_INACTIVE_DUAL_WIELD', 'parent': 30798,
            'child': 674,
            'owner_mask': mask, 'active_spec': self.active_group,
            'skill': 118,
            'skill_present': False, 'skill_granted': False,
            'target_representation': 'NATIVE_ON_SPEC_ACTIVATION'}
        self.inactive_skill_proofs[spell] = proof
        return proof

    def add(
        self,
        spell: int,
        mask: int,
        anchor: int,
        path: list[int],
        reason: str,
    ) -> None:
        self.compatible(spell)
        if (str(spell) in self.tc.consumed_teachers and spell not
            in self.consumed_teachers):
            self.consumed_teachers[spell] = consumed_teacher_rule(
                spell, self.character, self.stored.get(spell, ()), self.skills,
                self.tc, self.ac, self.direction, self.level)
        if (str(spell) in self.tc.ordinary_teachers and spell not
            in self.consumed_teachers):
            self.consumed_teachers[spell] = ordinary_teacher_rule(
                spell, self.character, self.stored.get(spell, ()), self.skills,
                self.tc, self.ac, self.direction)
        allowed = self.eligible(spell)
        # All sources of provenance may be unioned, but no source can widen
        # the verified specialization authorization.
        mask &= allowed
        if not mask:
            reject('UNAUTHORIZED_TALENT_SPELL', f'{spell}: anchor={anchor}')
        inactive_skill = self.inactive_dual_wield(spell, mask)
        self._validate_spell_abilities(spell, anchor)
        self._validate_skill_effect(spell, inactive_skill)
        disposition = self._spell_disposition(spell, mask, inactive_skill)
        row = self.result.setdefault(spell, {'mask': 0,
            'disposition': disposition, 'proofs': []})
        if row['disposition'] != disposition:
            reject('CONFLICTING_SPELL_REPRESENTATION', str(spell))
        row['mask'] |= mask
        proof = [anchor, path, reason]
        if proof not in row['proofs']:
            row['proofs'].append(proof)

    def _race_class_rows(
        self,
        metadata: Metadata,
        skill: int,
    ) -> list[list[int]]:
        return [r for _, r in sorted(metadata.stores[
            'SkillRaceClassInfo'].items())
            if r[1] == skill and (not r[2] or r[2] & self.race_mask)
            and (not r[3] or r[3] & self.class_mask)]

    def _validate_spell_abilities(self, spell: int, anchor: int) -> None:
        for metadata in (self.tc, self.ac):
            for script in metadata.scripts[spell]:
                skill = metadata.cast_only_scripts.get(script, {}).get(
                    'spell_skills', {}).get(str(spell))
                if (skill and (skill not in self.skills or min(self.skills[
                    skill]) <= 0)):
                    reject('RESEARCH_SKILL_MISSING',
                        f'{spell}: skill={skill}; existing profession '
                        'required')

        target_skill_abilities = [ability for ability in self.ac.abilities[
            spell]
            if ability[1] in self.ac.stores['SkillLine']]

        if (target_skill_abilities and not any(self._race_class_rows(self.ac,
            ability[1]) for ability in target_skill_abilities)):
            source_skills = sorted({ability[1] for ability
                in self.tc.abilities[spell]
                if ability[1] in self.tc.stores[
                    'SkillLine']})
            source_eligible = (not source_skills or any(self._race_class_rows(
                self.tc, skill) for skill in source_skills))
            reject('AC_WOULD_DELETE_SPELL',
                f'{spell}: race={self.race}; class={self.cls}; anchor='
                f'{anchor}; stored_anchor_flags='
                f'{self.stored.get(anchor, ())}; source_skill_ids='
                f'{source_skills}; target_skill_ids='
                f'{sorted({ability[1] for ability in target_skill_abilities})}'
                f'; source_skill_eligible={source_eligible}; no eligible '
                'target SkillRaceClassInfo')

        if any(ability[1] == 776 for ability in self.ac.abilities[spell]):
            # Both native skill loaders normalize Runeforging's mono range
            # to 1/1; some addSpell paths also call LearnDefaultSkill. Refuse
            # nonstandard stored state instead of relying on that correction.
            if 776 not in self.skills:
                proof = known_runeforging_without_skill(spell, self.character,
                    self.stored, self.skills, self.tc, self.ac, self.direction)
                if proof is None:
                    reject('SPELL_WOULD_ADD_SKILL', f'{spell}: skill=776')
                self.absent_runeforging_proofs[spell] = proof
            layouts = []
            for metadata in (self.tc, self.ac):
                infos = self._race_class_rows(metadata, 776)
                line = metadata.stores['SkillLine'].get(776)
                if (not line or line[1] != 7 or not infos
                    or any(info[6] in metadata.stores['SkillTiers']
                        for info in infos)):
                    reject('INCOMPATIBLE_SKILL_METADATA',
                        f'{spell}: skill=776; expected mono Runeforging '
                        'metadata')
                layouts.append(sorted(tuple(info[1:7]) for info in infos))
            if layouts[0] != layouts[1]:
                reject('INCOMPATIBLE_SKILL_METADATA',
                    f'{spell}: skill=776; race/class metadata differ')
            if 776 in self.skills and tuple(self.skills[776]) != (1, 1):
                reject('SPELL_WOULD_CHANGE_SKILL',
                    f'{spell}: skill=776; native value=1; cap=1; stored='
                    f'{self.skills[776]}')

    def _validate_skill_effect(
        self,
        spell: int,
        inactive_skill: Evidence | None,
    ) -> None:
        effect = self.ac.skill_effect(spell)
        if effect:
            skill, _, minimum, maximum = effect
            if (not inactive_skill and (skill not in self.skills
                or self.skills[skill][0] < minimum or self.skills[skill][
                    1] < maximum)):
                reject('SPELL_WOULD_CHANGE_SKILL',
                    f'{spell}: skill={skill}; minimum={minimum}; cap='
                    f'{maximum}')
            rows, source_rows = self._race_class_rows(self.ac,
                skill), self._race_class_rows(self.tc, skill)
            if not rows or not source_rows:
                reject('SPELL_SKILL_NOT_ELIGIBLE', f'{spell}: skill={skill}')
            if rows[0][6] and rows[0][6] not in self.ac.stores['SkillTiers']:
                reject('MISSING_SKILL_TIER', f'{spell}: skill={skill}')
            source_line, target_line = self.tc.stores['SkillLine'].get(
                skill), self.ac.stores['SkillLine'].get(skill)
            source_tier = (self.tc.stores['SkillTiers'].get(source_rows[0][6],
                [0] * 33)[17:33])
            target_tier = (self.ac.stores['SkillTiers'].get(rows[0][6], [
                0] * 33)[17:33])
            if (not source_line or not target_line or source_line[1]
                != target_line[1]
                or source_rows[0][4:7] != rows[0][4:7] or source_tier
                != target_tier):
                reject('INCOMPATIBLE_SKILL_METADATA',
                    f'{spell}: skill={skill}; category/flags/tier differ')
        if SKILL_STEP in self.ac.spells[spell][71:74]:
            reject('UNSUPPORTED_SKILL_STEP_SPELL', str(spell))

    def _spell_disposition(
        self,
        spell: int,
        mask: int,
        inactive_skill: Evidence | None,
    ) -> str:
        direct = spell in self.tc.talents
        runtime = False
        if direct:
            row = self.ac.talent_rows[spell]
            persistent = (bool(row[19]) and not self.ac.spells[spell][4]
                & PASSIVE and LEARN not in self.ac.spells[spell][71:74])
            disposition = 'PERSISTENT' if persistent else 'TALENT'
        else:
            runtime = spell in self.temporary_spells
            disposition = ('AURA' if spell in self.aura_helpers else 'SKILL'
                if spell in self.skill_delegates
                else 'RUNTIME' if runtime else 'PERSISTENT')
        if spell in self.consumed_teachers:
            disposition = 'TEACHER'
        if (disposition == 'PERSISTENT' and LEARN in self.ac.spells[spell][
            71:74]):
            reject('UNSUPPORTED_PERSISTENT_LEARN_EFFECT', str(spell))
        if self.direction == 'ac-to-tc' and spell in self.source_passive_masks:
            # Store only an active exact child. TC restores its prefix itself;
            # an inactive higher row could disable an active lower rank during
            # AddSpell loading. Other selected specs restore through their
            # unchanged talent rows when natively activated.
            exact_mask = 0
            for owner_mask in self.native_passive_owners.get(spell, {}).values(
            ):
                exact_mask |= owner_mask
            disposition = ('PERSISTENT' if exact_mask & (
                1 << self.active_group) else 'RUNTIME')
        elif (self.direction == 'ac-to-tc' and disposition not in ('SKILL',
            'AURA')):
            # TC removes alternate direct talent ranks when AddSpell runs.
            # Only the active selected rank belongs in its stored spellbook;
            # character_talent retains the other specialization's selection.
            if direct and not mask & (1 << self.active_group):
                disposition = 'TALENT'
            else:
                disposition = 'PERSISTENT'
        if inactive_skill:
            disposition = 'RUNTIME'
        return disposition


def reconstruct(
    character: Character,
    stored: SpellBook,
    talents: TalentMasks,
    skills: Skills,
    source: Metadata,
    target: Metadata,
    direction: Direction,
    level: int | None = None,
) -> SpellResults:
    """Return deterministic spell rows without mutating character inputs."""
    return SpellReconstruction(
        character, stored, talents, skills, source, target, direction, level
    ).run()
