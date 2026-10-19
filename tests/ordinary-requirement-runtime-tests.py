#!/usr/bin/env python3
"""Execute protected AC spec-mask and TC/AC trainer requirement consumers.

State getters/catalogs are mocked. This verifies known ordinary spell handling,
not full worldserver loading, quest completion, casts or gameplay acceptance.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

tc,ac=map(Path,sys.argv[1:])
def body(source,marker):
    start=source.index('{',source.index(marker));end=start+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
acplayer=(ac/'src/server/game/Entities/Player/Player.cpp').read_text()
mask_body=body(acplayer,'uint8 Player::GetLearnSpellSpecMask(')
methods='uint8 Player::GetLearnSpellSpecMask(uint32 spellId) const '+mask_body+'\n'
for repo,name in ((tc,'TcState'),(ac,'AcState')):
    source=(repo/'src/server/game/Entities/Creature/Trainer.cpp').read_text()
    methods+='SpellState Trainer::'+name+'(Player const* player,Spell const* trainerSpell) const '+body(source,'SpellState Trainer::'+('GetSpellState(' if name=='TcState' else 'GetDefaultSpellState('))+'\n'
mock=r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <vector>
using uint8=uint8_t;using uint32=uint32_t;using int32=int32_t;
constexpr uint8 SPEC_MASK_ALL=3;
constexpr int SPELL_EFFECT_LEARN_SPELL=36;
using SpellRequiredMap=std::multimap<uint32,uint32>;
struct Range {
 SpellRequiredMap::const_iterator first,last;
 auto begin()const{return first;}auto end()const{return last;}
};
struct SpellEffectInfo {int effect;uint32 TriggerSpell;bool IsEffect(int x)const{return effect==x;}};
struct SpellInfo {std::vector<SpellEffectInfo> effects;auto const&GetEffects()const{return effects;}};
std::map<uint32,uint32> costs;
uint32 GetTalentSpellCost(uint32 id){return costs[id];}
struct SpellMgr {
 std::map<uint32,uint32> first,previous;
 std::map<uint32,SpellInfo> spells;
 std::set<uint32> additional;
 SpellRequiredMap required;
 uint32 requirementReads=0;
 uint32 GetFirstSpellInChain(uint32 id){return first.count(id)?first[id]:id;}
 uint32 GetPrevSpellInChain(uint32 id){return previous[id];}
 bool IsAdditionalTalentSpell(uint32 id){return additional.count(id);}
 Range GetSpellsRequiredForSpellBounds(uint32 id){++requirementReads;auto p=required.equal_range(id);return {p.first,p.second};}
 SpellInfo const*AssertSpellInfo(uint32 id){return &spells[id];}
}manager;SpellMgr*sSpellMgr=&manager;
struct PlayerSpell {uint8 specMask=3;};
struct Player {
 uint8 m_activeSpec=0;
 std::map<uint32,PlayerSpell*> m_spells;
 uint8 GetActiveSpecMask()const{return 1<<m_activeSpec;}
 uint8 GetLearnSpellSpecMask(uint32 spellId)const;
 bool HasSpell(uint32 id)const {auto p=m_spells.find(id);return p!=m_spells.end()&&(p->second->specMask&GetActiveSpecMask());}
 bool IsSpellFitByClassAndRace(uint32)const{return true;}
 uint32 GetBaseSkillValue(uint32)const{return 450;}
 uint32 GetLevel()const{return 80;}
};
enum class SpellState {Known,Unavailable,Available};
struct Trainer {
 struct Spell {uint32 SpellId,ReqSkillLine=0,ReqSkillRank=0,ReqLevel=0;std::array<int32,3> ReqAbility{};};
 SpellState TcState(Player const*,Spell const*)const;
 SpellState AcState(Player const*,Spell const*)const;
};
'''
main=r'''
int main(){
 manager.required.emplace(5209,5487);
 manager.required.emplace(23214,13819);manager.required.emplace(23214,33391);
 PlayerSpell ordinary{3},otherSpec{2};Trainer trainer;
 for(uint8 spec:{0,1})for(uint32 id:{5209,23214}){
  Player p;p.m_activeSpec=spec;p.m_spells[id]=&ordinary;
  uint32 reads=manager.requirementReads;
  assert(p.GetLearnSpellSpecMask(id)==3&&manager.requirementReads==reads);
  Trainer::Spell direct{id};
  assert(trainer.TcState(&p,&direct)==SpellState::Known&&trainer.AcState(&p,&direct)==SpellState::Known);
  uint32 wrapper=1000000+id;manager.spells[wrapper].effects={{36,id}};
  manager.required.emplace(wrapper,5487);Trainer::Spell wrapped{wrapper};
  assert(trainer.TcState(&p,&wrapped)==SpellState::Known&&trainer.AcState(&p,&wrapped)==SpellState::Known);
  p.m_spells.erase(id);
  assert(trainer.TcState(&p,&direct)==SpellState::Unavailable&&trainer.AcState(&p,&direct)==SpellState::Unavailable);
  assert(trainer.TcState(&p,&wrapped)==SpellState::Unavailable&&trainer.AcState(&p,&wrapped)==SpellState::Unavailable);
  assert(!p.HasSpell(5487)&&!p.HasSpell(13819)&&!p.HasSpell(33391)&&p.m_spells.empty());
 }
 // Native talent/additional classification does not take the ordinary early return.
 costs[20911]=1;manager.additional.insert(25899);manager.required.emplace(25899,20911);
 Player talent;uint32 reads=manager.requirementReads;
 assert(talent.GetLearnSpellSpecMask(25899)==1&&manager.requirementReads==reads+1);
 talent.m_spells[20911]=&otherSpec;assert(talent.GetLearnSpellSpecMask(25899)==3);
 // This native learning fallback is not migration authorization: converter units
 // still require selected ownership and intersect every talent requirement.
 std::cout<<"Protected ordinary requirement consumers PASS: AC both-spec early return; TC/AC direct/wrapped trainers know existing spells, block unlearned spells without prerequisites; no parent grants; talent/additional negative control; getters mocked\n";
}
'''
with tempfile.TemporaryDirectory()as directory:
    cpp=Path(directory)/'requirements.cpp';binary=Path(directory)/'requirements'
    cpp.write_text(mock+methods+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
