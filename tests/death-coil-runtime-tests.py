#!/usr/bin/env python3
"""Compile native consumers with mocked catalogs, fields and state sinks."""
from pathlib import Path
import subprocess,tempfile,sys

tc_dir,ac_dir=map(Path,sys.argv[1:])
tc=(tc_dir/'src/server/game/Entities/Player/Player.cpp').read_text()
ac=(ac_dir/'src/server/game/Entities/Player/Player.cpp').read_text()
storage=(ac_dir/'src/server/game/Entities/Player/PlayerStorage.cpp').read_text()
def body(source,marker):
    start=source.index('{',source.index(marker));end=start+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
login=tc[tc.index('bool Player::LoadFromDB('):]
assert login.index('_LoadSkills(')<login.index('_LoadSpells(')
login=storage[storage.index('bool Player::LoadFromDB('):]
assert login.index('_LoadSkills(')<login.index('_LoadSpells(')
assert 'LearnSkillRewardedSpells(skill.first, skill.second);' in body(tc,'void Player::_LoadSkills(')
assert 'learnSkillRewardedSpells(skill.first, skill.second);' in body(ac,'void Player::_LoadSkills(')
assert 'if (HasSkill(skillId))\n            continue;' in body(tc,'void Player::LearnDefaultSkills(')
rank_start=tc.index('// talent: unlearn all other talent ranks (high and low)')
rank_end=tc.index('std::pair<PlayerSpellMap::iterator, bool> inserted',rank_start)
rank=tc[rank_start:rank_end]
marker='if (itr->second.disabled != disabled && itr->second.state != PLAYERSPELL_REMOVED)'
disable=marker+'\n'+body(tc,marker)
program=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <vector>
using uint8=uint8_t;using uint32=uint32_t;
constexpr uint32 SKILL_LINE_ABILITY_LEARNED_ON_SKILL_VALUE=1,SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN=2;
constexpr int PLAYERSPELL_UNCHANGED=0,PLAYERSPELL_NEW=1,PLAYERSPELL_CHANGED=2,PLAYERSPELL_REMOVED=3;
constexpr uint8 SPEC_MASK_ALL=3,MAX_TALENT_RANK=5;
struct PlayerSpell{int state=PLAYERSPELL_NEW;bool disabled=false;};
using PlayerSpellMap=std::map<uint32,PlayerSpell>;
struct SkillLineAbilityEntry{uint32 SkillLine,Spell,RaceMask,ClassMask,MinSkillLineRank,SupercededBySpell,AcquireMethod;};
std::vector<SkillLineAbilityEntry> records{{772,47541,0,32,1,49892,2},{772,49892,0,32,1,49893,0},
 {772,49893,0,32,1,49894,0},{772,49894,0,32,1,49895,0},{772,49895,0,32,1,0,0}};
std::vector<SkillLineAbilityEntry const*> abilities;
struct SpellInfo{};
struct Manager{
 SpellInfo info;std::multimap<uint32,SkillLineAbilityEntry const*> bySpell;
 SpellInfo const* GetSpellInfo(uint32 id){return id==6603||bySpell.count(id)?&info:nullptr;}
 auto GetSkillLineAbilityMapBounds(uint32 id){return bySpell.equal_range(id);}
 uint32 GetPrevSpellInChain(uint32 id){std::map<uint32,uint32> previous{{49895,49894},{49894,49893},{49893,49892},{49892,47541}};return previous[id];}
}manager;
Manager* sSpellMgr=&manager;
struct TalentSpellPos{uint32 talent_id;};
TalentSpellPos const* GetTalentSpellPos(uint32){return nullptr;}
struct TalentEntry{std::array<uint32,5> SpellRank{};};
struct TalentStore{TalentEntry const* LookupEntry(uint32){return nullptr;}}sTalentStore;
struct Field{uint32 value;uint32 GetUInt32()const{return value;}bool GetBool()const{return value!=0;}};
struct Rows{
 std::vector<std::array<Field,3>> data;size_t index=0;
 bool NextRow(){return ++index<data.size();}
 std::array<Field,3>const&operator*()const{return data[index];}
 Rows*operator->(){return this;}
 explicit operator bool()const{return !data.empty();}
};
using PreparedQueryResult=Rows;
namespace TC{
struct Player{
 PlayerSpellMap m_spells;uint32 cls=6;
 bool IsInWorld()const{return false;}
 uint32 GetRaceMask()const{return 1;}uint32 GetClassMask()const{return 1u<<(cls-1);}
 auto GetSkillLineAbilitiesBySkill(uint32 skill){assert(skill==772);return &abilities;}
 void RemoveSpell(uint32 id,bool=false,bool=false){m_spells.erase(id);}
 void LearnSpell(uint32,bool,uint32){assert(false);}
 bool UpdateDisabled(uint32 spellId,bool disabled){auto itr=m_spells.find(spellId);bool disabled_case=false;
 @DISABLE@
 return disabled_case;}
 bool AddSpell(uint32 spellId,bool active,bool,bool,bool disabled,bool=false,uint32 fromSkill=0){
  if(m_spells.count(spellId)){UpdateDisabled(spellId,disabled);return false;}
  @RANK@
  m_spells[spellId]={PLAYERSPELL_NEW,disabled};return !disabled;
 }
 bool HasSpell(uint32 spell)const @KNOWN@
 void LearnSkillRewardedSpells(uint32 skillId,uint32 skillValue) @TC_SKILL@
 void _LoadSpells(PreparedQueryResult result) @LOAD@
};
}
namespace AC{
struct Player{
 PlayerSpellMap m_spells;uint32 cls=6;
 bool IsInWorld()const{return false;}
 uint32 getRaceMask()const{return 1;}uint32 getClassMask()const{return 1u<<(cls-1);}
 auto GetSkillLineAbilitiesBySkillLine(uint32 skill){assert(skill==772);return abilities;}
 uint8 GetActiveSpec()const{return 0;}
 void removeSpell(uint32 id,uint8,bool){m_spells.erase(id);}
 void addSpell(uint32 id,uint8 mask,bool,bool){assert(mask==3);m_spells[id]={PLAYERSPELL_NEW,false};}
 void learnSpell(uint32,bool,bool){assert(false);}
 void learnSkillRewardedSpells(uint32 skill_id,uint32 skill_value) @AC_SKILL@
};
}
int main(){
 for(auto const&r:records){abilities.push_back(&r);manager.bySpell.emplace(r.Spell,&r);}
 for(uint32 anchor:{49892,49893,49895})for(uint32 value:{1,55,310,400}){
  TC::Player before;before.m_spells[6603]={PLAYERSPELL_NEW,false};
  before.LearnSkillRewardedSpells(772,value);assert(before.HasSpell(47541));
  Rows rows;rows.data.push_back({Field{anchor},Field{1},Field{1}});before._LoadSpells(rows);
  for(uint32 id:{47541,49892,49893,49894,49895})assert(!before.HasSpell(id));
  assert(before.HasSpell(6603));
  TC::Player after;after.LearnSkillRewardedSpells(772,value);after._LoadSpells({});
  assert(after.HasSpell(47541));
  for(uint32 id:{49892,49893,49894,49895})assert(!after.HasSpell(id));
  AC::Player target;target.learnSkillRewardedSpells(772,value);
  assert(target.m_spells.count(47541)==1);
  for(uint32 id:{49892,49893,49894,49895})assert(target.m_spells.count(id)==0);
 }
 TC::Player wrongClass;wrongClass.cls=1;wrongClass.LearnSkillRewardedSpells(772,400);assert(!wrongClass.HasSpell(47541));
 std::cout<<"PASS: native TC skill learning grants base 47541; subsequent stored disabled higher rank recursively disables it.\n";
 std::cout<<"PASS: deleting disabled higher history makes base 47541 known on TC reload; AC native skill loading also grants only base 47541.\n";
 std::cout<<"PASS: all supplied anchors/representative skill values, unlearned higher ranks and foreign-class negative control; state/catalog/DB sinks mocked, gameplay NOT TESTED.\n";
}
'''
for key,value in {'DISABLE':disable,'RANK':rank,'KNOWN':body(tc,'bool Player::HasSpell(uint32 spell) const'),
                  'TC_SKILL':body(tc,'void Player::LearnSkillRewardedSpells('),
                  'AC_SKILL':body(ac,'void Player::learnSkillRewardedSpells('),
                  'LOAD':body(tc,'void Player::_LoadSpells(')}.items():
    program=program.replace('@'+key+'@',value)
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);(p/'review.cpp').write_text(program)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(p/'review.cpp'),'-o',str(p/'review')],check=True)
    subprocess.run([str(p/'review')],check=True)
