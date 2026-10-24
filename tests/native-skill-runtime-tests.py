#!/usr/bin/env python3
"""Execute protected default-skill consumers with recording skill/state sinks."""
from pathlib import Path
import hashlib,re,subprocess,tempfile,sys
tc,ac=map(Path,sys.argv[1:])
root=Path(__file__).resolve().parents[1]
for core,prefix in ((tc,'trinitycore'),(ac,'azerothcore')):
 manifest=dict((n.strip().lstrip('*'),h)for h,n in(line.split(None,1)for line in
  (root/'compatibility/tc335-acwotlk-v2'/f'{prefix}-semantic.sha256').read_text().splitlines()))
 for name in ('src/server/game/Entities/Player/Player.cpp','src/server/game/Entities/Unit/Unit.h','src/server/game/Globals/ObjectMgr.cpp'):
  assert hashlib.sha256((core/name).read_bytes()).hexdigest()==manifest[name],'Protected skill consumer differs'
def body(s,marker):
 start=s.index('{',s.index(marker));end=start+1;depth=1
 while depth:
  depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[start:end]
acplayer=(ac/'src/server/game/Entities/Player/Player.cpp').read_text();tcplayer=(tc/'src/server/game/Entities/Player/Player.cpp').read_text()
assert 'GetTalentGroupsCount' not in body(tcplayer,'bool Player::AddSpell(')
assert 'GetSpecsCount' not in body(acplayer,'bool Player::_addSpell(')
maximums=[]
for core,kind,name in ((tc,'uint32','TcMax'),(ac,'uint16','AcMax')):
 unit=(core/'src/server/game/Entities/Unit/Unit.h').read_text()
 formula=body(unit,kind+' GetMaxSkillValueForLevel(')
 maximums.append(kind+' NativeUnit::'+name+'(NativeUnit const* target) const '+formula)
a=body(acplayer,'void Player::LearnDefaultSkill(');t=body(tcplayer,'void Player::LearnDefaultSkill(')
range_body=body((ac/'src/server/game/Globals/ObjectMgr.cpp').read_text(),'SkillRangeType GetSkillRangeType(')
tc_range_body=body((tc/'src/server/game/Globals/ObjectMgr.cpp').read_text(),'SkillRangeType GetSkillRangeType(')
mock=r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <vector>
using uint8=uint8_t;using uint16=uint16_t;using uint32=uint32_t;using int32=int32_t;
constexpr uint32 SKILL_CATEGORY_ARMOR=8,SKILL_CATEGORY_LANGUAGES=10,SKILL_RUNEFORGING=776,SKILL_FIST_WEAPONS=473,SKILL_UNARMED=162,SKILL_LOCKPICKING=633,SKILL_FLAG_ALWAYS_MAX_VALUE=0x10,CLASS_DEATH_KNIGHT=6,CLASS_CONTEXT_SKILL=0,CONFIG_ALWAYS_MAXSKILL=0;
enum SkillRangeType {SKILL_RANGE_NONE,SKILL_RANGE_LANGUAGE,SKILL_RANGE_LEVEL,SKILL_RANGE_MONO,SKILL_RANGE_RANK};
struct SkillRaceClassInfoEntry {uint32 SkillID=183,Flags=1170,SkillTierID=0;};
struct SkillLineEntry {uint32 id,ID,categoryId,CategoryID;};
struct SkillTiersEntry {uint16 Value[16]{};};
struct SkillLines {SkillLineEntry generic{183,183,12,12},runeforging{776,776,7,7};SkillLineEntry const* LookupEntry(uint32 id)const {if(id==183)return &generic;if(id==776)return &runeforging;return nullptr;}}sSkillLineStore;
struct Tiers {SkillTiersEntry const* LookupEntry(uint32)const{return nullptr;}}sSkillTiersStore;
SkillRaceClassInfoEntry generic{183,1170,0},runeforging{776,128,0};
SkillRaceClassInfoEntry const* GetSkillRaceClassInfo(uint32 id,uint8,uint8){return id==183?&generic:id==776?&runeforging:nullptr;}
struct World {bool max=false;bool getBoolConfig(uint32)const{return max;}}world;World*sWorld=&world;
#define LOG_DEBUG(...) ((void)0)
#define TC_LOG_DEBUG(...) ((void)0)
struct NativeUnit {
 uint16 level=80;uint16 GetLevel()const{return level;}
 uint16 GetLevelForTarget(NativeUnit const*)const{return level;}uint16 getLevelForTarget(NativeUnit const*)const{return level;}
 uint32 TcMax(NativeUnit const* target=nullptr)const;uint16 AcMax(NativeUnit const* target=nullptr)const;
};
constexpr uint32 SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN=2;
struct SkillLineAbilityEntry {uint32 AcquireMethod,TrivialSkillLineRankHigh;};
struct Player {
 uint8 cls=1,groups=1,active=0;uint16 level=80,slots=2;std::map<uint32,std::pair<uint16,uint16>> skills;
 uint8 getRace()const{return 1;}uint8 GetRace()const{return 1;}uint8 getClass()const{return cls;}uint8 GetClass()const{return cls;}
 uint16 GetLevel()const{return level;}uint16 GetMaxSkillValueForLevel()const{NativeUnit u;u.level=level;assert(u.TcMax()==u.AcMax());return u.AcMax();}
 bool IsProfessionOrRidingSkill(uint32)const{return false;}bool IsClass(uint32 c,uint32)const{return cls==c;}
 uint16 GetSkillValue(uint32 id)const{auto i=skills.find(id);return i==skills.end()?0:i->second.first;}
 void SetSkill(uint32 id,uint16,uint16 v,uint16 cap){skills[id]={v,cap};}
 void TcDefault(uint32 skillId,uint16 rank);void AcDefault(uint32 skillId,uint16 rank);
 bool HasSkill(uint32 id)const{return skills.count(id)>0;}
 void TcAcquire(uint32 skill,uint32 method,uint32 high);void AcAcquire(uint32 skill,uint32 method,uint32 high);
};
'''
methods='\n'.join(maximums)+'\nSkillRangeType AcRange(SkillRaceClassInfoEntry const* rcEntry)'+range_body+'\nSkillRangeType TcRange(SkillRaceClassInfoEntry const* rcEntry)'+tc_range_body+'\nvoid Player::TcDefault(uint32 skillId,uint16 rank)'+t.replace('GetSkillRangeType(','TcRange(')+'\nvoid Player::AcDefault(uint32 skillId,uint16 rank)'+a.replace('GetSkillRangeType(','AcRange(')

for source,name,callee in ((tcplayer,'TcAcquire','TcDefault'),(acplayer,'AcAcquire','AcDefault')):
    snippets=re.findall(r'if \(\(_spell_idx->second->AcquireMethod.*?\n\s*LearnDefaultSkill\(.*?;',source,re.S)
    assert len(snippets)==1,len(snippets)
    prefix='void Player::'+name+'(uint32 skill,uint32 method,uint32 high){auto pSkill=sSkillLineStore.LookupEntry(skill);assert(pSkill);SkillLineAbilityEntry ability{method,high};std::map<uint32,SkillLineAbilityEntry const*> bounds{{0,&ability}};auto _spell_idx=bounds.begin();'
    methods+=prefix+snippets[0].replace('LearnDefaultSkill(',callee+'(')+'}\n'

main=r'''
int main(){
 for(bool always:{false,true})for(uint8 cls:{1,6,11})for(uint16 level:{1,70,80}){
  world.max=always;Player tc,ac;tc.cls=ac.cls=cls;tc.level=ac.level=level;tc.TcDefault(183,0);ac.AcDefault(183,0);
  assert((tc.skills[183]==std::pair<uint16,uint16>{uint16(level*5),uint16(level*5)}));assert(tc.skills==ac.skills);assert(tc.slots==2&&ac.slots==2);
 }
 Player tc,ac;tc.cls=ac.cls=6;tc.TcDefault(776,0);ac.AcDefault(776,0);assert((tc.skills[776]==std::pair<uint16,uint16>{1,1}));assert(tc.skills==ac.skills);
 for(uint8 groups:{1,2})for(uint8 active=0;active<groups;++active)for(uint32 skill:{183,776}){
  Player left,right;left.groups=right.groups=groups;left.active=right.active=active;
  left.TcAcquire(skill,2,0);right.AcAcquire(skill,2,0);assert(left.skills==right.skills);assert(left.skills.count(skill)==1);
  assert(left.groups==groups&&right.groups==groups&&left.active==active&&right.active==active&&left.slots==2&&right.slots==2);
 }
 for(uint32 method:{0,1}){
  Player recipe;recipe.cls=6;recipe.skills[183]={400,400};auto before=recipe.skills;
  recipe.TcAcquire(776,method,510);assert(recipe.skills==before);
  recipe.AcAcquire(776,method,510);assert(recipe.skills==before);
 }
 for(uint32 method:{0,1,2}){
  Player acquiring;acquiring.cls=6;acquiring.TcAcquire(776,method,0);
  assert((acquiring.skills[776]==std::pair<uint16,uint16>{1,1}));
 }
 Player automatic;automatic.cls=6;automatic.AcAcquire(776,2,510);
 assert((automatic.skills[776]==std::pair<uint16,uint16>{1,1}));
 Player defaultRune;defaultRune.TcAcquire(776,1,0);assert((defaultRune.skills[776]==std::pair<uint16,uint16>{1,1}));
 Player existing;existing.skills[183]={1,400};existing.TcAcquire(183,2,0);existing.AcAcquire(183,2,0);assert((existing.skills[183]==std::pair<uint16,uint16>{1,400}));
 Player noSkill;noSkill.AcDefault(999999,0);assert(noSkill.skills.empty());
 std::cout<<"PASS protected TC/AC default skill bodies: Generic creates level*5 at native maximums for levels 1/70/80; Runeforging creates 1/1; unknown skill no-op; profession slots unchanged; method 0/1 high 510 recipes preserve absent Runeforging, acquiring controls create 1/1\n";
}
'''
with tempfile.TemporaryDirectory()as d:
 cpp=Path(d)/'native.cpp';exe=Path(d)/'native';cpp.write_text(mock+methods+main)
 subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
