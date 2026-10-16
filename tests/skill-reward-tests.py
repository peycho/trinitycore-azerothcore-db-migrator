#!/usr/bin/env python3
"""Execute protected skill reward loaders with recording dependent/temporary sinks."""
from pathlib import Path
import subprocess
import sys
import tempfile


def function(source, signature):
    start = source.index(signature)
    pos = source.index('{', start)
    depth = 1
    end = pos + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


tc, ac = map(Path, sys.argv[1:])
methods = []
for core, name in [(tc, 'TcRewards'), (ac, 'AcRewards')]:
    source = (core / 'src/server/game/Entities/Player/Player.cpp').read_text()
    original = 'LearnSkillRewardedSpells' if core == tc else 'learnSkillRewardedSpells'
    methods.append(function(source, 'void Player::' + original + '(').replace('Player::' + original + '(', 'Player::' + name + '('))
mock = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <utility>
#include <vector>
using uint32=uint32_t;
constexpr uint32 SKILL_LINE_ABILITY_LEARNED_ON_SKILL_VALUE=1,SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN=2,SPEC_MASK_ALL=3;
struct SkillLineAbilityEntry { uint32 SkillLine=118,Spell=674,RaceMask=0,ClassMask=109,AcquireMethod=2,MinSkillLineRank=1,SupercededBySpell=0; };
SkillLineAbilityEntry ability;
std::vector<SkillLineAbilityEntry const*> abilities{&ability};
using SkillLineAbilityMap=std::multimap<uint32,SkillLineAbilityEntry const*>;
using SkillLineAbilityMapBounds=std::pair<SkillLineAbilityMap::const_iterator,SkillLineAbilityMap::const_iterator>;
struct SpellInfo {};
struct SpellMgr {
    SpellInfo info; SkillLineAbilityMap map;
    SpellInfo const* GetSpellInfo(uint32 id) const { return id==674 || id==53341 || id==53343 ? &info:nullptr; }
    SkillLineAbilityMapBounds GetSkillLineAbilityMapBounds(uint32 id) const { return map.equal_range(id); }
};
SpellMgr manager;SpellMgr* sSpellMgr=&manager;
std::vector<SkillLineAbilityEntry const*> const* GetSkillLineAbilitiesBySkill(uint32) { return &abilities; }
std::vector<SkillLineAbilityEntry const*> GetSkillLineAbilitiesBySkillLine(uint32) { return abilities; }
struct Player {
    uint32 classMask=1,raceMask=1;
    std::vector<std::pair<uint32,uint32>> added;
    void TcRewards(uint32,uint32);void AcRewards(uint32,uint32);
    uint32 GetRaceMask() const { return raceMask; }
    uint32 getRaceMask() const { return raceMask; }
    uint32 GetClassMask() const { return classMask; }
    uint32 getClassMask() const { return classMask; }
    bool IsInWorld() const { return false; }
    uint32 GetActiveSpec() const { return 1; }
    void RemoveSpell(uint32) {}
    void removeSpell(uint32,uint32,bool) {}
    void AddSpell(uint32 id,bool active,bool dependent,bool learning,bool disabled,bool temporary,uint32) { assert(active && dependent && learning && !disabled && !temporary); added.emplace_back(id,3); }
    void LearnSpell(uint32,bool,uint32) { assert(false); }
    void addSpell(uint32 id,uint32 mask,bool update,bool temporary) { assert(update && temporary); added.emplace_back(id,mask); }
    void learnSpell(uint32,bool,bool) { assert(false); }
};

'''
main = r'''int main() {
    for (uint32 cls:{1,3,4,6}) {
        Player tc,ac;tc.classMask=ac.classMask=1<<(cls-1);
        tc.TcRewards(118,1);ac.AcRewards(118,1);
        assert((tc.added==std::vector<std::pair<uint32,uint32>>{{674,3}}));
        assert(tc.added==ac.added);
    }
    for (uint32 cls:{2,5}) {
        Player tc,ac;tc.classMask=ac.classMask=1<<(cls-1);
        tc.TcRewards(118,1);ac.AcRewards(118,1);
        assert(tc.added.empty() && ac.added.empty());
    }
    ability.RaceMask=2;
    Player tcRace,acRace;tcRace.TcRewards(118,1);acRace.AcRewards(118,1);
    assert(tcRace.added.empty() && acRace.added.empty());
    ability.RaceMask=0;ability.AcquireMethod=0;
    Player tcMethod,acMethod;tcMethod.TcRewards(118,1);acMethod.AcRewards(118,1);
    assert(tcMethod.added.empty() && acMethod.added.empty());

    SkillLineAbilityEntry cinder{776,53341,0,32,1,1,0},razor{776,53343,0,32,1,1,0};
    abilities={&cinder,&razor};
    for (uint32 value:{0,1}) {
        Player tc,ac;tc.classMask=ac.classMask=32;
        tc.TcRewards(776,value);ac.AcRewards(776,value);
        assert(tc.added==ac.added);
        assert(tc.added.size()==(value?2:0));
        if (value) assert((tc.added==std::vector<std::pair<uint32,uint32>>{{53341,3},{53343,3}}));
    }
    Player wrongClass;wrongClass.TcRewards(776,1);wrongClass.AcRewards(776,1);
    assert(wrongClass.added.empty());
    cinder.RaceMask=razor.RaceMask=2;
    Player wrongRace;wrongRace.classMask=32;wrongRace.TcRewards(776,1);wrongRace.AcRewards(776,1);
    assert(wrongRace.added.empty());
    cinder.RaceMask=razor.RaceMask=0;cinder.AcquireMethod=razor.AcquireMethod=0;
    Player trained;trained.classMask=32;trained.TcRewards(776,1);trained.AcRewards(776,1);
    assert(trained.added.empty());
    std::cout << "Protected TC/AC skill-reward consumers: ordinary Dual Wield class routes, Runeforging native dependencies, threshold/race/acquisition controls passed; spell-add sinks mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'skill.cpp'
    binary = Path(directory) / 'skill'
    cpp.write_text(mock + '\n'.join(methods) + main)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
