#!/usr/bin/env python3
"""Execute protected aura handlers with recording sinks, without a worldserver."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def body(source, signature):
    start = source.index('{', source.index(signature))
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


cores = list(map(Path, sys.argv[1:]))
handlers = []
for directory in cores:
    source = (directory / 'src/server/scripts/Spells/spell_druid.cpp').read_text()
    for name, value in [('R1', 47179), ('R2', 47180)]:
        assert re.search(rf'SPELL_DRUID_NURTURING_INSTINCT_{name}\s*=\s*{value}', source)
    source = source[source.index('class spell_dru_nurturing_instinct '):]
    handlers.append([body(source, 'void AfterApply('), body(source, 'void AfterRemove(')])
mock = r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>
using uint32=uint32_t;
constexpr uint32 SPELL_DRUID_NURTURING_INSTINCT_R1=47179,SPELL_DRUID_NURTURING_INSTINCT_R2=47180,SPEC_MASK_ALL=3;
struct AuraEffect {};
struct SpellInfo { uint32 rank=1; uint32 GetRank() const { return rank; } };
struct Player {
    bool isPlayer=true;
    std::vector<uint32> casts,removed,temporary;
    Player* ToPlayer() { return isPlayer?this:nullptr; }
    void CastSpell(Player* target,uint32 id,AuraEffect const*) { assert(target==this); casts.push_back(id); }
    void RemoveAurasDueToSpell(uint32 id) { removed.push_back(id); }
    void addSpell(uint32 id,uint32 mask,bool update,bool temp) { assert(mask==3 && !update && temp); temporary.push_back(id); }
    void removeSpell(uint32 id,uint32 mask,bool onlyTemporary) { assert(mask==3 && onlyTemporary); removed.push_back(id); temporary.clear(); }
};
using Unit=Player;
struct Handler {
    Player target; SpellInfo info;
    Player* GetTarget() { return &target; }
    SpellInfo const* GetSpellInfo() const { return &info; }
'''
for prefix, methods in zip(('Tc', 'Ac'), handlers):
    for suffix, method in zip(('Apply', 'Remove'), methods):
        # TC uses aurEff, AC intentionally ignores it; omit the name in AC.
        arg = 'aurEff' if prefix == 'Tc' and suffix == 'Apply' else ''
        mock += f'void {prefix}{suffix}(AuraEffect const* {arg}) {method}\n'
mock += r'''
};
int main() {
    for (uint32 rank:{1,2}) {
        uint32 child=rank==1?47179:47180;
        Handler h; h.info.rank=rank;
        h.TcApply(nullptr); assert(h.target.casts==std::vector<uint32>{child});
        assert(h.target.temporary.empty());
        h.TcRemove(nullptr); assert(h.target.removed==std::vector<uint32>{child});
        h.target.removed.clear();
        h.AcApply(nullptr); assert(h.target.temporary==std::vector<uint32>{child});
        h.AcRemove(nullptr); assert(h.target.temporary.empty());
        assert(h.target.removed==std::vector<uint32>{child});
        Handler nonplayer; nonplayer.target.isPlayer=false;
        nonplayer.AcApply(nullptr); nonplayer.AcRemove(nullptr);
        assert(nonplayer.target.temporary.empty() && nonplayer.target.removed.empty());
    }
    std::cout << "Protected Nurturing Instinct handlers: exact rank helpers, TC aura casts/removal, AC temporary add/removal and nonplayer controls passed; sinks mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'nurturing.cpp'
    binary = Path(directory) / 'nurturing'
    cpp.write_text(mock)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
