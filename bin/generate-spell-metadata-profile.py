#!/usr/bin/env python3
"""Generate conservative, reviewable DBC layouts and spell correction guards.

This never runs core code. Corrections affecting reconstruction are unsupported
unless their relevance can be excluded using the original effect type. The
profile reviewer must review this artifact together with the protected C++.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

STORES = {
    'Spell': ('spell_dbc', 'SpellEntryfmt'),
    'Talent': ('talent_dbc', 'TalentEntryfmt'),
    'TalentTab': ('talenttab_dbc', 'TalentTabEntryfmt'),
    'SkillLine': ('skillline_dbc', 'SkillLinefmt'),
    'SkillLineAbility': ('skilllineability_dbc', 'SkillLineAbilityfmt'),
    'SkillRaceClassInfo': ('skillraceclassinfo_dbc', 'SkillRaceClassInfofmt'),
    'SkillTiers': ('skilltiers_dbc', 'SkillTiersfmt'),
}

# Reviewed encounter handlers do not mutate persistent spell ownership.
# Keep complete files protected; unreviewed handlers in those files still block.
REVIEWED_ENCOUNTER_SCRIPTS = {
    'src/server/scripts/Outland/Auchindoun/ShadowLabyrinth/boss_murmur.cpp': {
        'spell_murmur_sonic_boom','spell_murmur_sonic_boom_effect'},
    'src/server/scripts/Outland/BlackTemple/boss_teron_gorefiend.cpp': {
        'spell_teron_gorefiend_shadow_of_death'},
}
REVIEWED_CORE_SCRIPTS = {
    'tc': {'src/server/scripts/EasternKingdoms/ScarletEnclave/chapter1.cpp': {
        'spell_chapter1_runeforging_credit'}},
}
# Constructor template arguments can change the spells an implementation casts.
# Resolve only aliases whose actual registration arguments were reviewed.
REVIEWED_LEGACY_ALIASES = {
    'spell_pal_seal_of_corruption':'spell_pal_seal_of_vengeance',
}
# These protected SpellScript handlers mutate recipes only when explicitly
# cast. Do not relabel them as non-mutating or accept other attached spell IDs.
REVIEWED_CAST_ONLY_SCRIPTS = {
    'spell_gen_profession_research': {
        'spell_skills': {'60893':171, '61177':773, '61288':773},
        'effects': [157,77,0],
    },
}
# TC casts/removes these helper auras; AC adds/removes temporary spells.
# Neither representation belongs in the persistent spellbook.
REVIEWED_AURA_TALENT_SCRIPTS = {
    'spell_dru_nurturing_instinct': {
        'parents': {'33872': {'rank':1,'child':47179}, '33873': {'rank':2,'child':47180}},
        'effects': [6,0,0], 'aura':175,
        'helper_effects': [6,0,0], 'helper_aura':118, 'helper_stances':1,
    },
}
REVIEWED_SKILL_REWARD_DEPENDENCIES = {
    '53428': {'skill':776, 'children':[53341,53343], 'value':1, 'max':1,
              'parent_effects':[47,0,0], 'child_effects':[53,3,0],
              'class_mask':32, 'acquire':1, 'minimum':1},
}
CORRECTION_DEFINITIONS = (
    'src/server/shared/SharedDefines.h',
    'src/server/game/Spells/SpellDefines.h',
    'src/server/game/Spells/Auras/SpellAuraDefines.h',
)
EFFECT_FIELDS = {'Effect': 71, 'TriggerSpell': 116, 'MiscValue': 110,
                 'BasePoints': 80, 'DieSides': 74, 'TargetA': 86, 'ApplyAuraName': 95}


def integer(expression, constants):
    """Only integer expressions; never execute text from a C++ source tree."""
    node = ast.parse(expression, mode='eval').body
    def visit(item):
        if isinstance(item, ast.Constant) and type(item.value) is int:
            return item.value
        if isinstance(item, ast.Name):
            return constants[item.id]
        if isinstance(item, ast.UnaryOp):
            value = visit(item.operand)
            if isinstance(item.op, ast.USub):
                return -value
            if isinstance(item.op, ast.Invert):
                return ~value
        if isinstance(item, ast.BinOp):
            left, right = visit(item.left), visit(item.right)
            for kind, operation in [(ast.BitOr, lambda: left | right), (ast.BitAnd, lambda: left & right),
                                    (ast.LShift, lambda: left << right), (ast.Add, lambda: left + right),
                                    (ast.Mult, lambda: left * right)]:
                if isinstance(item.op, kind):
                    return operation()
        raise ValueError('Unsupported integer expression')
    return visit(node)


def strip_comments(source):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)


def indexed_family_corrections(body, constants):
    """Read only bounded integer writes; report every unsupported access."""
    indexed=list(re.finditer(r'spellInfo->SpellFamilyFlags\s*\[([012])\]\s*([|&]?=)\s*([^;]+);',body))
    changes=[]
    guarded=len(re.findall(r'SpellFamilyFlags\s*\[',body))!=len(indexed)
    for assignment in indexed:
        try:
            if re.search(r'\b(if|else|for|while|do|switch|goto)\b',body):
                raise ValueError('Conditional indexed family correction')
            changes.append([209+int(assignment[1]),assignment[2],integer(assignment[3].strip(),constants)])
        except (ValueError,KeyError,SyntaxError):
            guarded=True
    return changes,guarded


def script_policies(content, reviewed=None, legacy_aliases=None):
    """Follow native named registrations without weakening mutation guards."""
    classes, scripts = {}, {}
    legacy_aliases = REVIEWED_LEGACY_ALIASES if legacy_aliases is None else legacy_aliases
    def store(name, policy):
        if scripts.get(name) != 'UNSUPPORTED_SPELLBOOK_MUTATION':
            scripts[name] = policy
    for match in re.finditer(r'\b(?:class|struct)\s+(spell_\w+)\b[^;{]*\{', content):
        if reviewed is not None and match[1] not in reviewed:
            continue
        start, end, depth = match.end(), match.end(), 1
        while depth and end < len(content):
            depth += (content[end] == '{') - (content[end] == '}')
            end += 1
        body = content[start:end - 1]
        mutation = bool(re.search(r'\b(?:LearnSpell|learnSpell|RemoveSpell|removeSpell|AddSpell|addSpell)\s*\(', body))
        policy = 'UNSUPPORTED_SPELLBOOK_MUTATION' if mutation else 'NO_SPELLBOOK_MUTATION'
        if classes.get(match[1]) != 'UNSUPPORTED_SPELLBOOK_MUTATION':
            classes[match[1]] = policy
        for name in {match[1]} | set(re.findall(r'"(spell_\w+)"', body)):
            store(name, policy)
    for implementation, alias in re.findall(
            r'\bRegister(?:Spell|Aura)ScriptWithArgs\(\s*(spell_\w+)\s*,\s*"(spell_\w+)"', content):
        if implementation in classes:
            store(alias, classes[implementation])
    # TC also registers legacy loaders with new Class<T1,T2>("alias").
    # Follow only resolved implementations, preserving any mutation rejection.
    for implementation, alias in re.findall(
            r'\bnew\s+(spell_\w+)\s*(?:<[^;{}()]+>\s*)?\(\s*"(spell_\w+)"', content):
        if implementation in classes and legacy_aliases.get(alias)==implementation:
            store(alias, classes[implementation])
    for first, second, alias in re.findall(
            r'\bRegisterSpellAndAuraScriptPair(?:WithArgs)?\(\s*(spell_\w+)\s*,\s*(spell_\w+)'
            r'(?:\s*,\s*"(spell_\w+)")?', content):
        if first in classes and second in classes:
            policy = ('UNSUPPORTED_SPELLBOOK_MUTATION' if any(
                classes[name] == 'UNSUPPORTED_SPELLBOOK_MUTATION' for name in (first, second))
                else 'NO_SPELLBOOK_MUTATION')
            store(alias or first, policy)
    return scripts


def generate(tc, ac):
    result = {'version': 1, 'stores': {}, 'corrections': {}, 'scripts': {}, 'inputs': {}}
    result['skill_reward_dependencies'] = REVIEWED_SKILL_REWARD_DEPENDENCIES
    for name, (table, fmt_name) in STORES.items():
        sql = (ac / f'data/sql/base/db_world/{table}.sql').read_text()
        columns = re.findall(r'^  `([^`]+)` ', sql, re.M)
        formats = {}
        for core, repo in [('tc', tc), ('ac', ac)]:
            source = (repo / 'src/server/shared/DataStores/DBCfmt.h').read_text()
            formats[core] = re.search(r'\b' + fmt_name + r'\[\] = "([^"]+)"', source)[1]
        if any(len(fmt) != len(columns) for fmt in formats.values()):
            raise ValueError(f'{name}: DBC/SQL layout mismatch')
        result['stores'][name] = {'table': table, 'columns': columns, 'formats': formats}
    tc_fmt = (tc / 'src/server/shared/DataStores/DBCfmt.h').read_text()
    result['tc_spell_sql_format'] = re.search(r'CustomSpellEntryfmt\[\] = "([^"]+)"', tc_fmt)[1]
    for core, repo, relative in [
        ('tc', tc, 'src/server/game/Spells/SpellMgr.cpp'),
        ('ac', ac, 'src/server/game/Spells/SpellInfoCorrections.cpp'),
    ]:
        registration = ('src/server/game/Scripting/ScriptMgr.h' if core == 'tc' else
                        'src/server/game/Scripting/ScriptDefines/SpellScriptLoader.h')
        inputs = ['src/server/shared/DataStores/DBCfmt.h', *CORRECTION_DEFINITIONS, relative, registration]
        if core == 'ac':
            inputs.extend(f'data/sql/base/db_world/{table}.sql' for table,_ in STORES.values())
        raw = (repo / relative).read_text()
        source = strip_comments(raw)
        guards, operations = [], []
        constants = {}
        defines = '\n'.join(strip_comments((repo / name).read_text()) for name in CORRECTION_DEFINITIONS)
        for name, expression in re.findall(r'\b([A-Z][A-Z0-9_]+)\s*=\s*([^,\n}]+)', defines):
            try:
                constants[name] = integer(expression.strip(), constants)
            except (ValueError, KeyError, SyntaxError):
                pass
        # Each reviewed ApplySpellFix scope has a numeric ID list and a lambda.
        for match in re.finditer(r'ApplySpellFix\(\{([^}]*)\}\s*,\s*\[\]\(SpellInfo\* spellInfo\)\s*\{', source):
            ids = [int(x) for x in re.findall(r'\b\d+\b', match[1])]
            start = match.end()
            end, depth = start, 1
            while depth:
                depth += (source[end] == '{') - (source[end] == '}')
                end += 1
            body = source[start:end - 1]
            fields, changes = [], []
            patterns = [
                (r'spellInfo->(Attributes|PowerType|SpellFamilyName|CasterAuraState|Stances)\s*([|&]?=)\s*([^;]+);', None),
                (r'spellInfo->(?:_GetEffect\(EFFECT_([012])\)|Effects\[EFFECT_([012])\])\.(Effect|TriggerSpell|MiscValue|BasePoints|DieSides|TargetA|ApplyAuraName)\s*([|&]?=)\s*([^;]+);', 'effect'),
            ]
            for pattern, effect in patterns:
                for assignment in re.finditer(pattern, body):
                    if effect:
                        index = int(assignment[1] or assignment[2])
                        field, op, value = assignment[3], assignment[4], assignment[5]
                        tag = f'{index}:{field}'
                        raw_field = EFFECT_FIELDS[field] + index
                        value = re.sub(r'^SpellImplicitTargetInfo\((.*)\)$', r'\1', value)
                    else:
                        field, op, value = assignment[1], assignment[2], assignment[3]
                        tag = 'visibility'
                        raw_field = {'Attributes': 4, 'PowerType': 41, 'SpellFamilyName': 208,
                                     'CasterAuraState': 20, 'Stances': 12}[field]
                    try:
                        # Conditional/cross-effect corrections need a separate review.
                        if re.search(r'\b(if|for|switch)\b', body):
                            raise ValueError('Conditional correction')
                        copied = re.fullmatch(
                            r'spellInfo->(?:_GetEffect\(EFFECT_([012])\)|Effects\[EFFECT_([012])\])\.'
                            r'(Effect|TriggerSpell|MiscValue|BasePoints|DieSides|TargetA|ApplyAuraName)', value.strip())
                        operand = ({'field': EFFECT_FIELDS[copied[3]] + int(copied[1] or copied[2])}
                                   if copied else integer(value.strip(), constants))
                        changes.append([raw_field, op, operand])
                    except (ValueError, KeyError, SyntaxError):
                        fields.append(tag)
            for flags in re.finditer(r'spellInfo->SpellFamilyFlags\s*=\s*flag96\(([^)]+)\);', body):
                try:
                    if re.search(r'\b(if|for|switch)\b', body):
                        raise ValueError('Conditional family correction')
                    changes.extend([[209 + i, '=', integer(value.strip(), constants)]
                                    for i, value in enumerate(flags[1].split(','))])
                except (ValueError, KeyError, SyntaxError):
                    fields.append('visibility')
            indexed_changes,indexed_guarded=indexed_family_corrections(body,constants)
            changes.extend(indexed_changes)
            # Unparsed indexed access (including copied/dynamic indexes) must
            # remain guarded; only bounded constant assignments were reviewed.
            if indexed_guarded or 'SetStackableWithRanks' in body:
                fields.append('visibility')
            if fields:
                guards.append({'ids': ids, 'fields': sorted(set(fields))})
            if changes:
                operations.append({'ids': ids, 'changes': changes})
        result['corrections'][core] = {
            'source': relative, 'sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'guards': guards, 'operations': operations,
        }
        scripts = {}
        reviewed_paths = REVIEWED_ENCOUNTER_SCRIPTS | REVIEWED_CORE_SCRIPTS.get(core,{})
        script_paths = set((repo / 'src/server/scripts/Spells').rglob('*.cpp'))
        script_paths.update(repo / name for name in reviewed_paths)
        for path in sorted(script_paths):
            inputs.append(str(path.relative_to(repo)))
            content = strip_comments(path.read_text())
            reviewed = reviewed_paths.get(str(path.relative_to(repo)))
            for name, policy in script_policies(content, reviewed).items():
                if scripts.get(name) != 'UNSUPPORTED_SPELLBOOK_MUTATION':
                    scripts[name] = policy
        result['scripts'][core] = scripts
        result.setdefault('cast_only_scripts',{})[core] = REVIEWED_CAST_ONLY_SCRIPTS
        result.setdefault('aura_talent_scripts',{})[core] = {
            name: rule | {'mode':'CAST_AURA' if core=='tc' else 'TEMPORARY_SPELL'}
            for name,rule in REVIEWED_AURA_TALENT_SCRIPTS.items()}
        result['inputs'][core] = {path: hashlib.sha256((repo/path).read_bytes()).hexdigest()
                                  for path in sorted(set(inputs))}
    return result


if __name__ == '__main__':
    tc, ac, output = map(Path, sys.argv[1:])
    output.write_text(json.dumps(generate(tc, ac), sort_keys=True, indent=2) + '\n')
