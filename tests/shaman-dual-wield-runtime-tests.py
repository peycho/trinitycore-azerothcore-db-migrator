#!/usr/bin/env python3
"""Execute protected skill-reward and off-hand gates with recording sinks.

This demonstrates why retiring only spell 674 cannot repair an unselected
Shaman while retaining skill 118. It is not full login/gameplay verification.
"""
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
tc,ac=map(Path,sys.argv[1:])

def body(text,marker):
    start=text.index('{',text.index(marker));end=start+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

sources={}
for core,path in (('tc',tc),('ac',ac)):
    prefix='trinitycore' if core=='tc' else 'azerothcore'
    manifest={name.strip().lstrip('*'):digest for digest,name in (line.split(None,1) for line in
        (ROOT/'compatibility/tc335-acwotlk-v2'/f'{prefix}-semantic.sha256').read_text().splitlines())}
    name='src/server/game/Entities/Player/Player.cpp'
    raw=(path/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==manifest[name]
    sources[core]=raw.decode()
mock=r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <vector>
using uint8=uint8_t;using uint16=uint16_t;using uint32=uint32_t;
constexpr uint32 SKILL_LINE_ABILITY_LEARNED_ON_SKILL_VALUE=1,SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN=2,SPEC_MASK_ALL=3;
struct SpellInfo{};
struct SkillLineAbilityEntry{uint32 Spell,AcquireMethod,RaceMask,ClassMask,MinSkillLineRank,SkillLine,SupercededBySpell;};
SkillLineAbilityEntry ability{674,2,0,109,1,118,0};
struct SpellMgr{
 SpellInfo spell;
 SpellInfo const*GetSpellInfo(uint32)const{return &spell;}
 auto GetSkillLineAbilityMapBounds(uint32)const{static std::map<uint32,SkillLineAbilityEntry const*> rows;return rows.equal_range(0);}
}manager;SpellMgr*sSpellMgr=&manager;
std::vector<SkillLineAbilityEntry const*>const*GetSkillLineAbilitiesBySkill(uint32 id){static std::vector<SkillLineAbilityEntry const*> rows{&ability};return id==118?&rows:nullptr;}
std::vector<SkillLineAbilityEntry const*>GetSkillLineAbilitiesBySkillLine(uint32 id){return id==118?std::vector<SkillLineAbilityEntry const*>{&ability}:std::vector<SkillLineAbilityEntry const*>{};}
struct Player{
 uint32 cls=7;bool inWorld=false;std::map<uint32,uint32> spells;
 uint32 GetRaceMask()const{return 1;}uint32 getRaceMask()const{return 1;}
 uint32 GetClassMask()const{return 1<<(cls-1);}uint32 getClassMask()const{return GetClassMask();}
 bool IsInWorld()const{return inWorld;}uint8 GetActiveSpec()const{return 0;}
 void AddSpell(uint32 id,bool,bool,bool,bool,bool,uint32){spells[id]=3;}
 void addSpell(uint32 id,uint32 mask,bool,bool){spells[id]=mask;}
 void LearnSpell(uint32 id,bool,uint32){spells[id]=3;}
 void learnSpell(uint32 id,bool,bool){spells[id]=3;}
 void RemoveSpell(uint32 id){spells.erase(id);}void removeSpell(uint32 id,uint8,bool){spells.erase(id);}
 void TcReward(uint32 skillId,uint32 skillValue);
 void AcReward(uint32 skill_id,uint32 skill_value);
};
'''
methods='void Player::TcReward(uint32 skillId,uint32 skillValue)'+body(sources['tc'],'void Player::LearnSkillRewardedSpells(')
methods+='\nvoid Player::AcReward(uint32 skill_id,uint32 skill_value)'+body(sources['ac'],'void Player::learnSkillRewardedSpells(')
# The exact early native empty-offhand gate guarantees that this path cannot
# call the later item moves/mail code. Occupied slots remain outside any repair.
gates=''
for core,name in (('tc','TcOffhand'),('ac','AcOffhand')):
    text=body(sources[core],'void Player::AutoUnequipOffhandIfNeed(')
    marker='    ItemTemplate const* offhandTemplate' if core=='tc' else '    // unequip offhand weapon'
    early=text[:text.index(marker)]
    assert 'if (!offItem)' in early and 'return;' in early
    gates+='\nvoid Equipment::'+name+'()'+early+'\n ++laterPath;\n}\n'
equipment=r'''
constexpr int INVENTORY_SLOT_BAG_0=255,EQUIPMENT_SLOT_OFFHAND=16;
struct Item{};
struct Equipment{
 bool occupied=false;int laterPath=0,updates=0;Item item;
 Item*GetItemByPos(int,int){return occupied?&item:nullptr;}
 void UpdateTitansGrip(){++updates;}
 void TcOffhand();void AcOffhand();
};
'''
# Exercise the actual normalizer switches: 118's weapon category gives a
# level-based range; the MONO_VALUE display flag is not the range authority.
ranges=''
for core,name in (('tc','TcRange'),('ac','AcRange')):
    source=(tc if core=='tc' else ac)/'src/server/game/Globals/ObjectMgr.cpp'
    prefix='trinitycore' if core=='tc' else 'azerothcore'
    manifest={n.strip().lstrip('*'):h for h,n in (line.split(None,1) for line in
        (ROOT/'compatibility/tc335-acwotlk-v2'/f'{prefix}-semantic.sha256').read_text().splitlines())}
    raw=source.read_bytes();assert hashlib.sha256(raw).hexdigest()==manifest['src/server/game/Globals/ObjectMgr.cpp']
    ranges+='\nSkillRangeType '+name+'(SkillRaceClassInfoEntry const*rcEntry)'+body(raw.decode(),'SkillRangeType GetSkillRangeType(')
normalizers=''
for core,name in (('tc','TcLoad'),('ac','AcLoad')):
    text=body(sources[core],'void Player::_LoadSkills(')
    start=text.index('            switch (GetSkillRangeType(rcEntry))');end=text.index('\n\n            if (value == 0)',start)
    fragment=text[start:end].replace('GetSkillRangeType(',('TcRange('if core=='tc'else'AcRange('))
    normalizers+='\nstd::pair<uint16,uint16> '+name+'(uint16 value,uint16 max,uint16 level){auto rcEntry=&info;auto GetMaxSkillValueForLevel=[level](){return level*5;};'+fragment+'return {value,max};}\n'
range_mock=r'''
constexpr uint32 SKILL_RUNEFORGING=776,SKILL_CATEGORY_ARMOR=8,SKILL_CATEGORY_LANGUAGES=10;
enum SkillRangeType{SKILL_RANGE_NONE,SKILL_RANGE_LANGUAGE,SKILL_RANGE_LEVEL,SKILL_RANGE_MONO,SKILL_RANGE_RANK};
struct SkillRaceClassInfoEntry{uint32 SkillID=118,Flags=402,SkillTierID=0;}info;
struct SkillLineEntry{uint32 CategoryID=6,categoryId=6;}line;
struct SkillLines{SkillLineEntry const*LookupEntry(uint32)const{return &line;}}sSkillLineStore;
struct Tiers{void const*LookupEntry(uint32)const{return nullptr;}}sSkillTiersStore;
'''
main=r'''
int main(){
 assert((ability.ClassMask&64)==64);
 for(uint16 level:{20,45,55,80}){
  auto before=std::pair<uint16,uint16>{1,uint16(level*5)};
  assert(TcLoad(before.first,before.second,level)==before);
  assert(AcLoad(before.first,before.second,level)==before);
  Player tc,ac;assert(tc.spells.empty()&&ac.spells.empty());
  tc.TcReward(118,1);ac.AcReward(118,1);
  assert(tc.spells.at(674)==3&&ac.spells.at(674)==3);
 }
 // No 118 row means the load loop does not call its reward consumer.
 Player noSkill;noSkill.TcReward(999,1);noSkill.AcReward(999,1);assert(noSkill.spells.empty());
 // Other ordinary Dual Wield classes keep their native reward.
 for(uint32 cls:{1,3,4,6}){Player tc,ac;tc.cls=ac.cls=cls;tc.TcReward(118,1);ac.AcReward(118,1);assert(tc.spells.at(674)==3&&ac.spells.at(674)==3);}
 // Actual loader gates block unrelated classes despite the stored row.
 Player mage;mage.cls=8;mage.TcReward(118,1);mage.AcReward(118,1);assert(mage.spells.empty());
 Equipment empty;empty.TcOffhand();empty.AcOffhand();assert(empty.laterPath==0&&empty.updates==1);
 Equipment occupied;occupied.occupied=true;occupied.TcOffhand();occupied.AcOffhand();assert(occupied.laterPath==2);
 std::cout<<"PASS protected TC/AC Shaman skill rewards: retained 118 regrants 674 (AC mask 3), native 1/level*5 preserved; shared-class and wrong-class controls; empty off-hand exits before item mutation; occupied slots reach later equipment handling. Mocked consumers; gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory()as d:
    cpp=Path(d)/'shaman.cpp';exe=Path(d)/'shaman'
    cpp.write_text(mock+methods+equipment+gates+range_mock+ranges+normalizers+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-implicit-fallthrough',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
