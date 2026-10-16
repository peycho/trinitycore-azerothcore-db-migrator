#!/usr/bin/env python3
"""Verify the native predecessor-call difference that keeps ranked children blocked."""
from pathlib import Path
import subprocess
import sys
import tempfile


tc, ac = map(Path, sys.argv[1:])
tc_source = (tc / 'src/server/game/Entities/Player/Player.cpp').read_text()
start = tc_source.index('// talent: unlearn all other talent ranks (high and low)')
end = tc_source.index('std::pair<PlayerSpellMap::iterator, bool> inserted', start)
tc_branch = tc_source[start:end]
ac_source = (ac / 'src/server/game/Entities/Player/Player.cpp').read_text()
start = ac_source.index('void Player::_addTalentAurasAndSpells(')
pos = ac_source.index('{', start)
depth, end = 1, pos + 1
while depth:
    depth += (ac_source[end] == '{') - (ac_source[end] == '}')
    end += 1
ac_function = ac_source[start:end]
mock = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>
using uint8=uint8_t;using uint32=uint32_t;
constexpr uint8 MAX_SPELL_EFFECTS=3,MAX_TALENT_RANK=5,SPEC_MASK_ALL=3;
constexpr int SPELL_EFFECT_LEARN_SPELL=36,SPELL_ATTR0_DO_NOT_DISPLAY=128;
struct TalentSpellPos { uint32 talent_id=1; };
TalentSpellPos position;
TalentSpellPos const* GetTalentSpellPos(uint32 id) { return id==37117?&position:nullptr; }
struct TalentEntry { std::array<uint32,5> SpellRank{37116,37117,0,0,0}; };
struct TalentStore { TalentEntry row;TalentEntry const* LookupEntry(uint32) const { return &row; } };
TalentStore sTalentStore;
struct Effect { int Effect=0;uint32 TriggerSpell=0; };
struct SpellInfo {
    std::array<Effect,3> Effects{Effect{36,16961},{},{}};uint32 Stances=0;
    bool HasEffect(int effect) const { return effect==36; }
    bool IsPassive() const { return false; }
    bool HasAttribute(int) const { return false; }
};
struct SpellMgr {
    SpellInfo info;
    uint32 GetPrevSpellInChain(uint32 id) const { return id==16961?16958:0; }
    SpellInfo const* GetSpellInfo(uint32 id) const { assert(id==37117);return &info; }
    bool IsAdditionalTalentSpell(uint32) const { return false; }
};
SpellMgr manager;SpellMgr* sSpellMgr=&manager;
struct Player {
    std::vector<uint32> predecessors,temporary,removed;
    bool IsInWorld() const { return false; }
    void RemoveSpell(uint32 id,bool,bool) { removed.push_back(id); }
    void AddSpell(uint32 id,bool,bool learning,bool dependent,bool disabled,bool loading,uint32) {
        assert(learning && dependent && !disabled && !loading);predecessors.push_back(id);
    }
    void LearnSpell(uint32,bool,uint32) { assert(false); }
    void _addSpell(uint32 id,uint8 mask,bool temp) { assert(mask==3 && temp);temporary.push_back(id); }
    bool IsNeedCastPassiveSpellAtLearn(SpellInfo const*) const { return false; }
    void CastSpell(Player*,uint32,bool) { assert(false); }
    void _addTalentAurasAndSpells(uint32);
    void TcRankBranch(uint32 spellId,bool active=true,bool disabled=false,uint32 fromSkill=0) {
'''
mock += tc_branch + '\n}\n};\n' + ac_function
mock += r'''
int main() {
    Player tc,ac;
    tc.TcRankBranch(16961);ac._addTalentAurasAndSpells(37117);
    assert(tc.predecessors==std::vector<uint32>{16958});
    assert(ac.temporary==std::vector<uint32>{16961});
    Player direct;direct.TcRankBranch(37117);
    assert(direct.predecessors.empty());
    assert(direct.removed==std::vector<uint32>{37116});
    std::cout << "Protected rank/talent consumer difference: TC requests predecessor 16958, AC adds only temporary 16961; direct-talent control passed; sinks mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'ranks.cpp'
    binary = Path(directory) / 'ranks'
    cpp.write_text(mock)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
