#!/usr/bin/env python3
"""Execute protected skill reward loaders with recording dependent/temporary sinks."""
from pathlib import Path
import hashlib
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
root=Path(__file__).resolve().parents[1]
for core,prefix in ((tc,'trinitycore'),(ac,'azerothcore')):
    manifest=dict((name.strip().lstrip('*'),digest)for digest,name in(line.split(None,1)for line in
        (root/'compatibility/tc335-acwotlk-v2'/f'{prefix}-semantic.sha256').read_text().splitlines()))
    name='src/server/game/Entities/Player/Player.cpp'
    assert hashlib.sha256((core/name).read_bytes()).hexdigest()==manifest[name], 'Protected skill reward consumer differs'
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
    SpellInfo const* GetSpellInfo(uint32 id) const { return id==674 || id==53341 || id==53343 || id==20154 || id==21084 || id==2382 || id==63644 || id==63645 ? &info:nullptr; }
    SkillLineAbilityMapBounds GetSkillLineAbilityMapBounds(uint32 id) const { return map.equal_range(id); }
};
SpellMgr manager;SpellMgr* sSpellMgr=&manager;
std::vector<SkillLineAbilityEntry const*> const* GetSkillLineAbilitiesBySkill(uint32) { return &abilities; }
std::vector<SkillLineAbilityEntry const*> GetSkillLineAbilitiesBySkillLine(uint32) { return abilities; }
struct Player {
    uint32 classMask=1,raceMask=1,groups=1,active=0;
    std::vector<std::pair<uint32,uint32>> added;
    void TcRewards(uint32,uint32);void AcRewards(uint32,uint32);
    uint32 GetRaceMask() const { return raceMask; }
    uint32 getRaceMask() const { return raceMask; }
    uint32 GetClassMask() const { return classMask; }
    uint32 getClassMask() const { return classMask; }
    bool IsInWorld() const { return false; }
    uint32 GetActiveSpec() const { return active; }
    void RemoveSpell(uint32) {}
    void removeSpell(uint32,uint32,bool) {}
    void AddSpell(uint32 id,bool active,bool dependent,bool learning,bool disabled,bool temporary,uint32) { assert(active && dependent && learning && !disabled && !temporary); added.emplace_back(id,3); }
    void LearnSpell(uint32,bool,uint32) { assert(false); }
    void addSpell(uint32 id,uint32 mask,bool update,bool temporary) { assert(update && temporary); added.emplace_back(id,mask); }
    void learnSpell(uint32,bool,bool) { assert(false); }
};

'''
main = r'''int main() {
    SkillLineAbilityEntry generic{183,2382,0,0,2,0,0},primary{183,63644,4095,1535,2,0,0},secondary{183,63645,4095,1535,2,0,0};
    abilities={&generic,&primary,&secondary};
    for(uint32 groups:{1,2})for(uint32 active=0;active<groups;++active){
        Player tc,ac;tc.groups=ac.groups=groups;tc.active=ac.active=active;
        tc.TcRewards(183,400);ac.AcRewards(183,400);
        assert((tc.added==std::vector<std::pair<uint32,uint32>>{{2382,3},{63644,3},{63645,3}}));
        assert(tc.added==ac.added&&tc.groups==groups&&ac.groups==groups&&tc.active==active&&ac.active==active);
    }
    abilities={&ability};
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
    // Existing Holy skill teaches the upper seal in BOTH native cores. TC
    // also learns the lower seal; AC deliberately skips the superseded entry.
    // Explicit lower persistence therefore changes no native upper grant.
    SkillLineAbilityEntry lower{594,20154,0,2,2,1,21084},upper{594,21084,0,2,2,1,0};
    manager.map.emplace(20154,&lower);manager.map.emplace(21084,&upper);
    for(uint32 value:{35,110,400})for(bool reversed:{false,true}){
        abilities=reversed?std::vector<SkillLineAbilityEntry const*>{&upper,&lower}:
                           std::vector<SkillLineAbilityEntry const*>{&lower,&upper};
        Player tc,ac;tc.classMask=ac.classMask=2;
        tc.TcRewards(594,value);ac.AcRewards(594,value);
        std::sort(tc.added.begin(),tc.added.end());
        assert((tc.added==std::vector<std::pair<uint32,uint32>>{{20154,3},{21084,3}}));
        assert((ac.added==std::vector<std::pair<uint32,uint32>>{{21084,3}}));
    }
    std::cout << "Protected TC/AC skill-reward consumers: ordinary Dual Wield, Runeforging and Seal of Righteousness native rewards, threshold/race/acquisition controls passed; spell-add sinks mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'skill.cpp'
    binary = Path(directory) / 'skill'
    cpp.write_text(mock + '\n'.join(methods) + main)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
