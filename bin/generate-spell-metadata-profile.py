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


def generate(tc, ac):
    result = {'version': 1, 'stores': {}, 'corrections': {}, 'scripts': {}, 'inputs': {}}
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
        inputs = ['src/server/shared/DataStores/DBCfmt.h', 'src/server/shared/SharedDefines.h', relative]
        if core == 'ac':
            inputs.extend(f'data/sql/base/db_world/{table}.sql' for table,_ in STORES.values())
        raw = (repo / relative).read_text()
        source = strip_comments(raw)
        guards, operations = [], []
        constants = {}
        defines = strip_comments((repo / 'src/server/shared/SharedDefines.h').read_text())
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
                        raw_field = {'Effect': 71, 'TriggerSpell': 116, 'MiscValue': 110,
                                     'BasePoints': 80, 'DieSides': 74, 'TargetA': 86,
                                     'ApplyAuraName': 95}[field] + index
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
                        changes.append([raw_field, op, integer(value.strip(), constants)])
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
            if re.search(r'SpellFamilyFlags\[|SetStackableWithRanks', body):
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
        for path in sorted((repo / 'src/server/scripts/Spells').rglob('*.cpp')):
            inputs.append(str(path.relative_to(repo)))
            content = strip_comments(path.read_text())
            for match in re.finditer(r'\b(?:class|struct)\s+(spell_\w+)\b[^;{]*\{', content):
                start, end, depth = match.end(), match.end(), 1
                while depth and end < len(content):
                    depth += (content[end] == '{') - (content[end] == '}')
                    end += 1
                body = content[start:end - 1]
                names = {match[1]} | set(re.findall(r'"(spell_\w+)"', body))
                mutation = bool(re.search(r'\b(?:LearnSpell|learnSpell|RemoveSpell|removeSpell|AddSpell|addSpell)\s*\(', body))
                for name in names:
                    policy = 'UNSUPPORTED_SPELLBOOK_MUTATION' if mutation else 'NO_SPELLBOOK_MUTATION'
                    if scripts.get(name) != 'UNSUPPORTED_SPELLBOOK_MUTATION':
                        scripts[name] = policy
        result['scripts'][core] = scripts
        result['inputs'][core] = {path: hashlib.sha256((repo/path).read_bytes()).hexdigest()
                                  for path in sorted(set(inputs))}
    return result


if __name__ == '__main__':
    tc, ac, output = map(Path, sys.argv[1:])
    output.write_text(json.dumps(generate(tc, ac), sort_keys=True, indent=2) + '\n')
