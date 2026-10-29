"""Reviewed compatibility rules for native spell, talent and skill behavior."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

from cleanup_types import (
    Character,
    Direction,
    Evidence,
    Skills,
    SpellBook,
    SpellFlags,
)
from spell_common import (
    DUAL_WIELD,
    HIDDEN,
    LEARN,
    PASSIVE,
    SKILL,
    SKILL_STEP,
    Unsupported,
    reject,
    signed,
)

if TYPE_CHECKING:
    from spell_metadata import Metadata


def known_runeforging_without_skill(
    spell: int,
    character: Character,
    stored: SpellBook,
    skills: Skills,
    tc: Metadata,
    ac: Metadata,
    direction: Direction,
) -> Evidence | None:
    """Preserve known enchantments whose native addSpell path acquires no
    skill.

    AcquireMethod 1 with high=510 is a reward threshold, not an
    acquisition instruction. Neither a skill nor another enchantment is
    inferred here.
    """
    recipes = {53323, 53331, 53341, 53342, 53343, 53344, 54446, 54447, 62158,
        70164}
    race, cls, _, _ = character
    flags = stored.get(spell)
    # The streamed CLI pads AC's mask with zero; pure readers may omit it.
    enabled = (flags == (1, 0) if direction == 'tc-to-ac' else flags in ((3,),
        (3, 0)))
    if (spell not in recipes or cls != 6 or not 1 <= race <= 32 or 776
        in skills or not enabled):
        return None
    layouts = []
    for meta in (tc, ac):
        row = meta.spells.get(spell, [])
        ability = [a for a in meta.abilities[spell] if a[1] == 776]
        infos = sorted(r[1:] for r in meta.stores['SkillRaceClassInfo'].values(
        ) if r[1] == 776)
        method = int(spell in (53341, 53343))
        if (len(row) < 212 or row[4] & PASSIVE or row[71:74] != [53, 3, 0]
            or any(row[116:119]) or meta.chain(spell) != (spell,)
            or meta.skill_effect(spell) or meta.learns[spell]
            or meta.effect_learns[spell]
            or meta.requires[spell] or spell in meta.talents or spell
            in meta.additional
            or meta.talent_learn_owners.get(spell) or meta.aura_owners.get(
                spell)
            or spell in meta.world_aura_owners
            or len(ability) != 1 or ability[0][1:] != [776, spell, 0, 32,
                0, 0, 1, 0, method, 510, 500, 0, 0]
            or meta.stores['SkillLine'].get(776, [0, 0])[1] != 7
            or not infos
            or any(r[2:] != [32, 128, 0, 0, 0] or r[1] and not r[1] & (
                1 << (race - 1)) for r in infos)):
            return None
        layouts.append(infos)
    if layouts[0] != layouts[1]:
        return None
    return {'policy': 'KNOWN_RUNEFORGING_NO_SKILL_ACQUISITION', 'skill': 776,
        'skill_present': False, 'skill_granted': False, 'spell': spell,
        'acquire_method': method, 'trivial_high': 510, 'trivial_low': 500,
        'known_before': True, 'new_enchantments_granted': False}


def known_ranked_language_without_skill(
    spell: int,
    skill: int,
    character: Character,
    stored: SpellBook,
    skills: Skills,
    tc: Metadata,
    ac: Metadata,
    direction: Direction,
) -> Evidence | None:
    """Native LearnDefaultSkill(skill, 0) is inert for a ranked language.

    GetSkillRangeType checks a present SkillTiers record before the
    language category. Rank zero exits that branch without SetSkill.
    Preserve only an already-known singleton language, never a new
    learned or derived spell.
    """
    race, cls, active, groups = character
    if skill in skills or spell not in stored:
        return None
    flags = stored[spell]
    if direction == 'tc-to-ac':
        if tuple(flags) != (1, 0):
            return None
    elif not flags or flags[0] != 3 or any(flags[1:]):
        return None
    layouts = []
    for m in (tc, ac):
        row = m.spells[spell]
        line = m.stores['SkillLine'].get(skill, [])
        infos = [r for _, r in sorted(m.stores['SkillRaceClassInfo'].items())
            if r[1] == skill
            and (not r[2] or r[2] & (1 << (race - 1))) and (not r[3] or r[
                3] & (1 << (cls - 1)))]
        abilities = [a[1:] for a in m.abilities[spell]]
        if (len(line) < 2 or line[1] != 10 or not infos or infos[0][6] not
            in m.stores['SkillTiers']
            or m.chain(spell) != (spell,) or set(row[71:74]) != {0, 39}
            or row[4] != 192 or any(row[86:92]) or any(row[95:98]) or any(
                row[116:119])
            or m.scripts[spell] or m.learns[spell] or m.effect_learns[
                spell]
            or m.requires[spell] or m.learn_parents[spell] or spell
            in m.talents or m.talent_learn_owners.get(spell)
            or len(abilities) != 1 or abilities[0][0] != skill
            or abilities[0][8] != 2):
            return None
        layouts.append((infos[0][1:], m.stores['SkillTiers'][infos[0][6]],
            abilities))
    if layouts[0] != layouts[1]:
        return None
    return {'policy': 'KNOWN_RANKED_LANGUAGE_ZERO_RANK_NOOP', 'skill': skill,
        'known_before': True,
        'skill_present': False, 'skill_granted': False,
        'native_default_rank': 0,
        'native_range': 'RANK', 'native_tier': layouts[0][0][5],
        'race_class_info': layouts[0][0], 'ability': layouts[0][2][0]}


def script_review(
    metadata: Sequence[Metadata],
    stored_counts: Mapping[int, int],
    talent_counts: Mapping[int, int],
) -> list[Evidence]:
    """Inventory every binding on stored/selected IDs, including later
    failures.

    This is not a grant set or a source cleanup selection. Counts are
    per character, with selected groups merged. Derived-only IDs are
    outside scope.
    """
    rows = []
    for core in sorted(metadata, key=lambda item: item.core):
        for spell in sorted(stored_counts.keys() | talent_counts.keys()):
            for name in sorted(core.scripts.get(spell, ())):
                row = {'core': core.core, 'spell': spell, 'script': name,
                    'stored_characters': stored_counts[spell],
                    'talent_characters': talent_counts[spell],
                    'status': 'REVIEWED', 'reason_code': '', 'detail': ''}
                try:
                    core.check_script(spell, name)
                except Unsupported as error:
                    row.update(status='REVIEW_REQUIRED',
                        reason_code=error.reason, detail=str(error))
                rows.append(row)
    return rows


def assert_acyclic(metadata: Metadata, seeds: Iterable[int]) -> None:
    done, visiting = set(), set()
    for root in seeds:
        stack = [(root, False)]
        while stack:
            spell, leaving = stack.pop()
            if leaving:
                visiting.discard(spell)
                done.add(spell)
                continue
            if spell in visiting:
                reject('CYCLIC_SPELL_RELATIONSHIP', str(spell))
            if spell in done:
                continue
            metadata.check_spell(spell)
            visiting.add(spell)
            stack.append((spell, True))
            previous = metadata.predecessors(spell)[-1:]
            edges = (list(previous) + [row[0] for row in metadata.learns[
                spell]] + sorted(metadata.requires[spell]))
            stack.extend((child, False) for child in reversed(edges))
            if len(visiting) > len(metadata.spells):
                reject('SPELL_TRAVERSAL_BOUND', str(root))


def native_passive_rule(
    owner: int,
    tc: Metadata,
    ac: Metadata,
    cls: int,
) -> Evidence | None:
    """Prove a reviewed exact-child contract; an unknown chain gets no
    exception.
    """
    family = str(tc.talents[owner][0])
    rule = tc.native_passive_ranks.get(family)
    if not rule:
        return None
    def blocked(detail: str) -> None:
        reject('UNSUPPORTED_NATIVE_PASSIVE_RANK', f'{owner}: {detail}')
    if (rule != ac.native_passive_ranks.get(family) or cls != rule['class']
        or owner not in rule['owners']):
        blocked('profile/class/selected owner contract differs')
    children = rule['children'][rule['owners'].index(owner)]
    for metadata in (tc, ac):
        for rank, parent in enumerate(rule['owners'], 1):
            record = metadata.spells.get(parent, [])
            expected = rule['children'][rank - 1]
            if (metadata.talents.get(parent) != (int(family), rank)
                or not record or record[20]
                or sorted(r[0] for r in metadata.effect_learns[parent])
                != sorted(expected)
                or record[71:74] != rule['parent_effects']
                or any(record[71 + i] == LEARN and record[86 + i] != 1
                    for i in range(3))):
                blocked(
                    f'{metadata.core}: parent={parent}: talent rank, learn '
                    'effect or self-target differs')
        for chain in rule['chains']:
            if metadata.chain(chain[0]) != tuple(chain):
                blocked(f'{metadata.core}: chain={chain[0]}: rank '
                    'membership/order differs')
            for spell in chain:
                record = metadata.spells[spell]
                parents = ({p for p, items in zip(rule['owners'], rule[
                    'children']) if spell in items})
                if (spell in metadata.talents or spell in metadata.additional
                    or record[4] & (PASSIVE | HIDDEN) != PASSIVE | HIDDEN
                    or not any(record[71:74]) or any(effect not in (0, 6)
                        for effect in record[71:74])
                    or metadata.requires[spell]
                    or metadata.prerequisite_users[spell]
                    or spell in metadata.trainer_taught
                    or metadata.learns[spell] or metadata.effect_learns[
                        spell]
                    or metadata.learn_parents[spell] != parents):
                    blocked(f'{metadata.core}: child={spell}: passive '
                        'visibility, ownership, incoming route or dependency '
                        'differs')
                trigger = rule['triggers'].get(str(chain[0]), 0)
                if any(value != (trigger if i == 0 else 0) for i, value
                    in enumerate(record[116:119])):
                    blocked(
                        f'{metadata.core}: child={spell}: proc trigger '
                        'differs')
                if trigger:
                    metadata.check_spell(trigger)
                    proc = metadata.spells[trigger]
                    if (any(effect in (LEARN, SKILL, SKILL_STEP, DUAL_WIELD)
                        for effect in proc[71:74])
                        or metadata.learns[trigger]
                        or metadata.effect_learns[trigger]):
                        blocked(
                            f'{metadata.core}: child={spell}: proc={trigger}'
                            ': unsupported learned/skill effect')
                for ability in metadata.abilities[spell]:
                    if (ability[9] or ability[1] in (633, 762, 776)
                        or metadata.stores['SkillLine'].get(ability[1], [0,
                            0])[1] != 7):
                        blocked(f'{metadata.core}: child={spell}: ability='
                            f'{ability[0]}: unsafe skill route')
    # The selected exact children must retain their effect/stance/state data.
    # Superseded predecessors remain uncast in AC's approved representation.
    for child in children:
        left, right = tc.spells[child], ac.spells[child]
        if (left[71:119] != right[71:119] or left[12] != right[12] or left[20]
            != right[20]):
            blocked(
                f'child={child}: source/target selected effects, stance or '
                'aura state differ')
    if tc.spells[owner][71:119] != ac.spells[owner][71:119]:
        blocked('source/target selected parent effect data differ')
    for trigger in rule['triggers'].values():
        if tc.spells[trigger][71:119] != ac.spells[trigger][71:119]:
            blocked(f'proc={trigger}: source/target effect data differ')
    return rule


def world_talent_aura_rule(
    owner: int,
    tc: Metadata,
    ac: Metadata,
    cls: int,
) -> Evidence | None:
    """Reviewed TC inactive known helper -> AC selected-talent aura
    contract.

    No spell, skill or talent ownership is inferred. Verify the entire
    small family, including Bear form callbacks and exclusion routes,
    before allowing any exact helper to be delegated. A different world
    relationship blocks.
    """
    family = str(tc.talents[owner][0])
    rule = tc.world_talent_auras.get(family)
    if not rule:
        return None
    def blocked(detail: str) -> None:
        reject('INCOMPATIBLE_WORLD_TALENT_AURA', f'{owner}: {detail}')
    if (rule != ac.world_talent_auras.get(family) or cls != rule['class']
        or owner not in rule['owners']):
        blocked('profile/class/selected owner differs')
    expected_bindings = set(rule['owners'] + rule['forms'])
    for metadata in (tc, ac):
        bindings = ({s for s, names in metadata.scripts.items() if rule[
            'script'] in names})
        if bindings != (expected_bindings if metadata.core == 'ac' else set()):
            blocked(
                f'{metadata.core}: selected-talent/form script bindings '
                'differ')
        for index, (parent, child) in enumerate(zip(rule['owners'], rule[
            'children'])):
            p, h = metadata.spells.get(parent, []), metadata.spells.get(child,
                [])
            if (metadata.talents.get(parent) != (int(family), index + 1)
                or metadata.chain(parent) != tuple(rule['owners'])
                or not p or p[4] != rule['parent_flags'] or p[12] != rule[
                    'parent_stances']
                or p[20] or p[71:74] != [6, 0, 0] or p[95:98] != [rule[
                    'parent_aura'], 0, 0]
                or signed(p[80]) != rule['parent_basepoints'][index] or p[
                    86:92] != [1, 0, 0, 0, 0, 0]
                or p[116:119] != [0, 0, 0] or metadata.effect_learns[
                    parent]
                or metadata.learns[parent] != ([(child, 0, False)]
                    if metadata.core == 'tc' else[])
                or metadata.requires[parent] or metadata.learn_parents[
                    parent]
                or child in metadata.talents or metadata.chain(child) != (
                    child,)
                or not h or h[4] != rule['helper_flags'] or h[12] != rule[
                    'helper_stances']
                or h[20] or h[71:74] != [6, 0, 0] or h[95:98] != [rule[
                    'helper_aura'], 0, 0]
                or signed(h[80]) != rule['helper_basepoints'][index] or h[
                    86:92] != [1, 0, 0, 0, 0, 0]
                or h[116:119] != [0, 0, 0] or metadata.scripts[child]
                or metadata.requires[child] or metadata.prerequisite_users[
                    child]
                or metadata.learns[child] or metadata.effect_learns[child]
                or metadata.learn_parents[child] != ({parent}
                    if metadata.core == 'tc' else set())
                or metadata.abilities[child] or child
                in metadata.trainer_taught
                or parent in metadata.trainer_taught):
                blocked(f'{metadata.core}: parent={parent}, helper={child}: '
                    'effects/ownership/routes differ')
            for spell, record in ((parent, p), (child, h)):
                metadata.check_spell(spell)
                if (record[74:80] != [1, 0, 0, 0, 0, 0] or record[81:86] != [0,
                    0, 0, 0, 0]
                    or any(record[98:116]) or record[92:95] != [0, 0, 0]
                    or record[5:12] != (rule['parent_attributes_ex'][
                        index] if spell == parent else rule[
                            'helper_attributes_ex'])
                    or any(record[13:20])
                    or any(record[20:28]) or any(record[31:35]) or record[
                        36] or record[49]
                    or record[40] != rule['parent_duration' if spell
                        == parent else 'helper_duration']
                    or record[68:71] != [0xffffffff, 0, 0] or any(record[
                        119:131])
                    or metadata.scripts[spell] != ({rule['script']}
                        if metadata.core == 'ac' and spell == parent else set(
                        ))):
                    blocked(
                        f'{metadata.core}: spell={spell}: unreviewed effect '
                        'magnitude, target or script')
            # Parent skill associations are passive class associations only;
            # they must not add a skill or profession on either core.
            if any(row[1] != 134 or row[9] or row[8] for row
                in metadata.abilities[parent]):
                blocked(
                    f'{metadata.core}: parent={parent}: unsafe skill '
                    'route')
        for form in rule['forms']:
            r = metadata.spells.get(form, [])
            metadata.check_spell(form)
            if (not r or form in metadata.talents or r[71:74] != [6, 6, 0]
                or r[95:98] != [36, 77, 0] or r[12] or r[20]
                or r[110] != (5 if form == rule['forms'][0] else 8)
                or metadata.skill_effect(form) or metadata.effect_learns[
                    form]):
                blocked(f'{metadata.core}: form={form}: native shapeshift '
                    'contract differs')
    for spell in rule['owners'] + rule['children'] + rule['forms']:
        left, right = tc.spells[spell], ac.spells[spell]
        if (left[71:119] != right[71:119] or left[12] != right[12] or left[20]
            != right[20]):
            blocked(
                f'{spell}: source/target effects, stance or aura state '
                'differ')
    return rule


def ranked_world_talent_aura_rule(
    owner: int,
    tc: Metadata,
    ac: Metadata,
    cls: int,
) -> Evidence | None:
    """Optional TC known-helper edges plus the reviewed exact AC aura
    script.

    A script-only world retains its cast-only semantics. Once a world
    learning route exists, verify the entire ranked family, including
    the TC prefix that AC deliberately does not learn. Never use that
    prefix as AC ownership.
    """
    family = str(tc.talents[owner][0])
    rule = tc.world_ranked_talent_auras.get(family)
    if not rule or not any(tc.learns[parent] for parent in rule['owners']):
        return None
    def blocked(detail: str) -> None:
        reject('INCOMPATIBLE_WORLD_TALENT_AURA', f'{owner}: {detail}')
    if (rule != ac.world_ranked_talent_auras.get(family) or cls != rule[
        'class']):
        blocked('ranked profile/class differs')
    # Attributes, stances, aura gates, proc/interrupt state, duration, item
    # requirements, effect values/targets/masks and family flags are protected.
    fields = (*range(4, 28), *range(31, 35), 36, 40, 49, *range(68, 131),
        *range(208, 212))
    for metadata in (tc, ac):
        bindings = ({s for s, names in metadata.scripts.items() if rule[
            'script'] in names})
        if bindings != set(rule['owners']):
            blocked(f'{metadata.core}: ranked script bindings differ')
        if metadata.chain(rule['children'][0]) != tuple(rule['children']):
            blocked(f'{metadata.core}: helper chain membership/order differs')
        for index, (parent, child) in enumerate(zip(rule['owners'], rule[
            'children'])):
            if (metadata.talents.get(parent) != (int(family), index + 1)
                or metadata.chain(parent) != tuple(rule['owners'])
                or metadata.learns[parent] != ([(child, 0, False)]
                    if metadata.core == 'tc' else[])
                or metadata.effect_learns[parent]
                or metadata.learn_parents[parent]
                or metadata.requires[parent] or parent
                in metadata.trainer_taught):
                blocked(f'{metadata.core}: parent={parent}: selected '
                    'ownership/world route differs')
            for spell in (parent, child):
                metadata.check_spell(spell)
                record = metadata.spells[spell]
                shape = rule['mechanics'][str(spell)]
                if any(record[field] != shape.get(str(field), 0) for field
                    in fields):
                    blocked(
                        f'{metadata.core}: spell={spell}: ranked aura '
                        'mechanics differ')
                if (metadata.scripts[spell] != ({rule['script']} if spell
                    == parent else set())):
                    blocked(
                        f'{metadata.core}: spell={spell}: unexpected '
                        'script')
            if (child in metadata.talents or child in metadata.additional
                or metadata.learn_parents[child] != ({parent}
                    if metadata.core == 'tc' else set())
                or metadata.learns[child] or metadata.effect_learns[child]
                or metadata.requires[child] or metadata.prerequisite_users[
                    child]
                or metadata.abilities[child] or child
                in metadata.trainer_taught
                or any(row[1] != 134 or row[9] or row[8] for row
                    in metadata.abilities[parent])):
                blocked(f'{metadata.core}: helper={child}: unreviewed '
                    'incoming/outgoing/skill route')
    return rule


def ordinary_teacher_rule(
    spell: int,
    character: Character,
    flags: SpellFlags,
    skills: Skills,
    tc: Metadata,
    ac: Metadata,
    direction: Direction,
) -> Evidence:
    """Persist verified TC load-derived ordinary children without executing
    LEARN.

    Class skills/professions must already exist. Child skill effects and
    native eligibility still go through the normal reconstruction
    checks.
    """
    rule = tc.ordinary_teachers[str(spell)]
    if (direction != 'tc-to-ac' or flags != (1, 0) or (rule['class']
        and character[1] != rule['class'])):
        reject('UNREPRESENTABLE_TEACHER_STATE',
            f'{spell}: enabled TC anchor and reviewed class required')
    def blocked(detail: str) -> None:
        reject('INCOMPATIBLE_CONSUMED_TEACHER', f'{spell}: {detail}')
    if rule != ac.ordinary_teachers.get(str(spell)):
        blocked('ordinary teacher profiles differ')
    for metadata in (tc, ac):
        expected = [(child, 1, False) for child in rule['children']]
        if (metadata.learns[spell] != expected or metadata.effect_learns[
            spell] != expected
            or metadata.chain(spell) != (spell,) or metadata.abilities[
                spell]
            or metadata.learn_parents[spell] or metadata.scripts[spell]
            or metadata.requires[spell] or metadata.prerequisite_users[
                spell]):
            blocked(f'{metadata.core}: wrapper routes differ')
        for member in [spell, *rule['children']]:
            metadata.check_spell(member)
            record = metadata.spells[member]
            shape = rule['mechanics'][str(member)]
            if any(record[field] != shape.get(str(field), 0) for field in (
                *range(4, 131), *range(208, 212))):
                blocked(f'{metadata.core}: spell={member}: mechanics differ')
            if (member in metadata.talents or member in metadata.additional
                or metadata.talent_learn_owners.get(member)
                or metadata.aura_owners.get(member)
                or member in metadata.world_aura_owners):
                blocked(
                    f'{metadata.core}: spell={member}: unexpected '
                    'talent/aura route')
        for child in rule['children']:
            if (list(metadata.chain(child)) != rule['chains'][metadata.core][
                str(child)]
                or metadata.scripts[child] != set(rule['scripts'][
                    metadata.core].get(str(child), []))
                or metadata.requires[child] != set(rule['requirements'][
                    metadata.core].get(str(child), []))
                or metadata.learn_parents[child] != {spell}
                or metadata.learns[child]
                or metadata.effect_learns[child]
                or metadata.prerequisite_users[child]
                or [row[1:] for row in metadata.abilities[child]] != [rule[
                    'abilities'][str(child)]]):
                blocked(
                    f'{metadata.core}: child={child}: relationships '
                    'differ')
        for skill in rule['skills']:
            if skill not in skills:
                reject('SPELL_WOULD_ADD_SKILL',
                    f'{spell}: skill={skill}; existing teacher child '
                    'skill required')
            if not 0 < skills[skill][0] <= skills[skill][1]:
                reject('SPELL_WOULD_CHANGE_SKILL',
                    f'{spell}: skill={skill}; invalid stored range')
            if (metadata.stores['SkillLine'].get(skill, [0, 0])[1] != (11
                if skill == 202 else 7)):
                blocked(f'{metadata.core}: skill={skill}: category differs')
    return {'policy': 'TC_KNOWN_ORDINARY_TEACHER', 'children': rule[
        'children'],
        'class': rule['class'], 'skills': [[skill, *skills[skill]]
            for skill in rule['skills']],
        'source_flags': list(flags), 'effects_executed': False,
        'target_representation': 'PERSISTENT_CHILDREN_WITH_RECORDED_WRAPPER'}


def consumed_teacher_rule(
    spell: int,
    character: Character,
    flags: SpellFlags,
    skills: Skills,
    tc: Metadata,
    ac: Metadata,
    direction: Direction,
    level: int | None,
) -> Evidence:
    """A verified TC wrapper becomes its load-derived buttons, without
    casting.

    Its original stock row remains control provenance. Reverse
    conversion preserves buttons without inventing an absent TC wrapper.
    """
    rule = tc.consumed_teachers[str(spell)]
    if (direction != 'tc-to-ac' or character[3] != rule['spec_count'] or flags
        != (1, 0)):
        reject('UNREPRESENTABLE_TEACHER_STATE',
            f'{spell}: requires enabled TC stored anchor and existing '
            f"{rule['spec_count']} specs; direction={direction}; flags="
            f'{flags}; groups={character[3]}')
    def blocked(detail: str) -> None:
        reject('INCOMPATIBLE_CONSUMED_TEACHER', f'{spell}: {detail}')
    if rule != ac.consumed_teachers.get(str(spell)):
        blocked('source/target profile differs')
    fields = (*range(4, 131), *range(208, 212))
    race_mask, class_mask = 1 << (character[0] - 1), 1 << (character[1] - 1)
    skill_layouts = []
    for metadata in (tc, ac):
        if (metadata.learns[spell] != [(child, 1, False) for child in rule[
            'children']]):
            blocked(f'{metadata.core}: effective load dependencies differ')
        if (metadata.effect_learns[spell] != [(child, 1, False) for child
            in rule['children']]):
            blocked(f'{metadata.core}: self-target teaching effects differ')
        if metadata.abilities[spell] or metadata.learn_parents[spell]:
            blocked(
                f'{metadata.core}: wrapper has a skill or incoming learning '
                'route')
        for member in [spell, *rule['children']]:
            metadata.check_spell(member)
            record = metadata.spells[member]
            shape = rule['mechanics'][str(member)]
            for field in fields:
                if record[field] != shape.get(str(field), 0):
                    blocked(f'{metadata.core}: spell={member}: mechanic field='
                        f'{field} differs')
            if (member in metadata.talents or member in metadata.additional
                or metadata.chain(member) != (member,) or metadata.scripts[
                    member]
                or metadata.requires[member]
                or metadata.prerequisite_users[member]
                or metadata.talent_learn_owners.get(member)):
                blocked(f'{metadata.core}: spell={member}: '
                    'rank/talent/script/prerequisite differs')
        for child in rule['children']:
            if metadata.learns[child] or metadata.effect_learns[child]:
                blocked(
                    f'{metadata.core}: button={child}: unexpected outgoing '
                    'learning route')
            expected = [rule['skill'], child, rule['race_mask'], rule[
                'class_mask'], 0, 0, 1, 0, 2, 0, 0, 0, 0]
            if (len(metadata.abilities[child]) != 1 or metadata.abilities[
                child][0][1:] != expected
                or metadata.stores['SkillLine'].get(rule['skill'], [0, 0])[
                    1] != rule['skill_category']):
                blocked(
                    f'{metadata.core}: button={child}: native Generic skill '
                    'association differs')
        infos = sorted(tuple(row[1:7]) for row in metadata.stores[
            'SkillRaceClassInfo'].values()
            if row[1] == rule['skill'] and (not row[2] or row[2]
                & race_mask)
            and (not row[3] or row[3] & class_mask))
        if not infos or any(row[3:] != (1170, 0, 0) for row in infos):
            blocked(
                f'{metadata.core}: native always-max Generic skill range '
                'differs')
        skill_layouts.append(infos)
    if skill_layouts[0] != skill_layouts[1]:
        blocked('source/target Generic race/class ranges differ')
    if rule['skill'] not in skills:
        reject('SPELL_WOULD_ADD_SKILL',
            f"{spell}: skill={rule['skill']}; existing native Generic skill "
            'required')
    if level is None or not 1 <= level <= 80:
        reject('UNREPRESENTABLE_TEACHER_STATE',
            f'{spell}: verified character level in 1..80 required')
    native_skill = level * 5
    if tuple(skills[rule['skill']]) != (native_skill, native_skill):
        reject('SPELL_WOULD_CHANGE_SKILL',
            f"{spell}: skill={rule['skill']}; stored={skills[rule['skill']]}"
            f'; native level={level} requires {native_skill}/{native_skill}')
    return {'policy': 'TC_KNOWN_DUAL_SPEC_TEACHER', 'children': rule[
        'children'],
        'spec_count': rule['spec_count'], 'skill': rule['skill'],
        'level': level, 'native_skill': native_skill,
        'stored_skill': list(skills[rule['skill']]), 'source_flags': list(
            flags),
        'target_representation': 'PERSISTENT_BUTTONS_WITH_RECORDED_WRAPPER',
        'effects_executed': False}


def seal_rank_split_rule(tc: Metadata, ac: Metadata, cls: int) -> Evidence:
    """TC rank prefix -> AC singleton seals, with identical replacement
    metadata.

    AC retains both known IDs; its client-facing skill ability still
    supersedes 20154 with 21084. This rule never learns the upper seal
    from the lower one. Incoming trainers are not grant sources and
    teaching wrappers remain blocked.
    """
    def blocked(detail: str) -> None:
        reject('INCOMPATIBLE_SEAL_RANK_SPLIT', f'20154:21084: {detail}')
    if (cls != 2 or tc.chain(20154) != (20154, 21084)
        or tc.chain(21084) != (20154, 21084)
        or ac.chain(20154) != (20154,) or ac.chain(21084) != (21084,)):
        blocked('class or exact source/target chains differ')
    for metadata in (tc, ac):
        for spell in (20154, 21084):
            metadata.check_spell(spell)
            record = metadata.spells[spell]
            upper = spell == 21084
            # Exact relevant mechanics, including judgement's extra aura on
            # the upper seal. Equality between two changed inputs is not proof.
            effects = ([6, 6, 6] if upper else[6, 6, 0])
            expected = (effects + [1, 1, int(upper)] + [0, 0, 0]
                + [0xffffffff, 0xffffffff, 20186 if upper else 0]
                + [0, 0, 0] + [1, 1, int(upper)] + [0, 0, 0] + [0, 0,
                    0]
                + [4, 108, 4 if upper else 0] + [0] * 12
                + [0, 14, 0] + [0] * 6)
            scripts = {'spell_pal_seal_of_righteousness'}
            if metadata.core == 'tc':
                scripts.add('spell_pal_seals')
            if (record[4:13] != [327680, 0, 0, 524288, 0, 0, 0, 0, 0]
                or record[20] or record[41] or record[71:119] != expected
                or record[208:212] != [10, 0x08000000, 0x20000000, 0]
                or spell in metadata.talents or spell
                in metadata.additional
                or metadata.talent_learn_owners.get(spell)
                or metadata.aura_owners.get(spell)
                or metadata.skill_effect(spell) is not None
                or metadata.requires[spell] or metadata.prerequisite_users[
                    spell]
                or metadata.learns[spell] or metadata.effect_learns[spell]
                or metadata.learn_parents[spell] != ({10321} if upper
                    else set())
                or metadata.scripts[spell] != scripts):
                blocked(f'{metadata.core}: {spell}: mechanics, ownership or '
                    'learning routes differ')
            abilities = metadata.abilities[spell]
            expected_ability = [594, spell, 0, 2, 0, 0, 1, 0 if upper
                else 21084, 2, 0, 0]
            if (len(abilities) != 1 or abilities[0][1:12] != expected_ability
                or metadata.stores['SkillLine'].get(594, [0, 0])[1] != 7
                or sorted(r[1:7] for r in metadata.stores[
                    'SkillRaceClassInfo'].values()
                    if r[1] == 594) != [[594, 0xffffffff, 2, 1040, 0,
                        0]]):
                blocked(
                    f'{metadata.core}: {spell}: class skill/replacement '
                    'link differs')
    return {'policy': 'NATIVE_SEAL_RANK_SPLIT', 'tc_chain': [20154, 21084],
        'ac_chains': [[20154], [21084]], 'skill': 594,
        'superseded_by': {'20154': 21084}, 'higher_rank_granted': False}
