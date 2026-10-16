#!/usr/bin/env python3
"""Exercise AC's protected talent consumer with a recording spell-add sink.

This verifies exact-child delegation, not worldserver gameplay or the effects
of _addSpell. The latter's rank behavior is reviewed in the protected source.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ac = Path(sys.argv[1])
source = (ac / 'src/server/game/Entities/Player/Player.cpp').read_text()
start = source.index('void Player::_addTalentAurasAndSpells(')
opening = source.index('{', start)
end, depth = opening + 1, 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
function = source[start:end]
mock = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <tuple>
#include <vector>
using uint8=uint8_t; using uint32=uint32_t;
constexpr uint8 MAX_SPELL_EFFECTS=3, SPEC_MASK_ALL=3;
constexpr int SPELL_EFFECT_LEARN_SPELL=36, SPELL_ATTR0_DO_NOT_DISPLAY=128;
struct SpellEffectInfo { int Effect=0; uint32 TriggerSpell=0; };
struct SpellInfo {
    std::array<SpellEffectInfo,3> Effects{};
    bool passive=false, hidden=false; uint32 Stances=0;
    bool HasEffect(int effect) const {
        for (auto const& row:Effects) if (row.Effect==effect) return true;
        return false;
    }
    bool IsPassive() const { return passive; }
    bool HasAttribute(int) const { return hidden; }
};
struct SpellMgr {
    std::map<uint32,SpellInfo> spells;
    std::set<uint32> additional;
    SpellInfo const* GetSpellInfo(uint32 id) { return &spells.at(id); }
    bool IsAdditionalTalentSpell(uint32 id) const { return additional.count(id); }
};
SpellMgr manager; SpellMgr* sSpellMgr=&manager;
struct Player {
    std::vector<std::tuple<uint32,uint8,bool>> added;
    std::vector<uint32> cast;
    bool passiveEligible=true;
    void _addTalentAurasAndSpells(uint32 spellId);
    void _addSpell(uint32 id,uint8 mask,bool temporary) { added.emplace_back(id,mask,temporary); }
    bool IsNeedCastPassiveSpellAtLearn(SpellInfo const*) const { return passiveEligible; }
    void CastSpell(Player*,uint32 id,bool triggered) { assert(triggered); cast.push_back(id); }
};
'''
main = r'''
int main() {
    // Fiery Payback: each selected talent learns only its own exact children.
    // AC's separate 44440 -> 44441 rank catalog must not add a call for 44440.
    manager.spells[64353].Effects={SpellEffectInfo{36,44440},SpellEffectInfo{36,64350},{}};
    manager.spells[64357].Effects={SpellEffectInfo{36,44441},SpellEffectInfo{36,64349},{}};
    Player rank1,rank2;
    rank1._addTalentAurasAndSpells(64353);
    rank2._addTalentAurasAndSpells(64357);
    assert((rank1.added==std::vector<std::tuple<uint32,uint8,bool>>{{44440,3,true},{64350,3,true}}));
    assert((rank2.added==std::vector<std::tuple<uint32,uint8,bool>>{{44441,3,true},{64349,3,true}}));
    assert(rank1.cast.empty() && rank2.cast.empty());
    // Additional talent spells are owned through their persistent mask policy.
    manager.additional.insert(44441);
    Player additional; additional._addTalentAurasAndSpells(64357);
    assert((additional.added==std::vector<std::tuple<uint32,uint8,bool>>{{64349,3,true}}));
    // Native passive and stance eligibility still controls casts.
    manager.spells[900001].passive=true;
    Player passive; passive._addTalentAurasAndSpells(900001);
    assert(passive.added.empty() && passive.cast==std::vector<uint32>{900001});
    Player ineligible; ineligible.passiveEligible=false;
    ineligible._addTalentAurasAndSpells(900001);
    assert(ineligible.added.empty() && ineligible.cast.empty());
    std::cout << "Protected AC talent exact-child consumer checks passed; spell-add sink mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'talent.cpp'
    binary = Path(directory) / 'talent-tests'
    cpp.write_text(mock + '\n' + function + '\n' + main)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
