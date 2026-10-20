#!/usr/bin/env python3
"""Execute protected native Generic load range and level update consumers."""
from pathlib import Path
import re, subprocess, tempfile, sys

tc,ac=map(Path,sys.argv[1:])

def body(source,marker):
    start=source.index('{',source.index(marker));end=start+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]

methods=[]
for repo,prefix in ((tc,'Tc'),(ac,'Ac')):
    header=(repo/'src/server/game/Entities/Player/Player.h').read_text()
    limit=int(re.search(r'#define PLAYER_MAX_SKILLS\s+(\d+)',header)[1])
    assert limit==(128 if prefix=='Tc' else 127),limit
    player=(repo/'src/server/game/Entities/Player/Player.cpp').read_text()
    update=player if prefix=='Tc' else (repo/'src/server/game/Entities/Player/PlayerUpdates.cpp').read_text()
    methods.append('void Player::'+prefix+'Update()'+body(update,'void Player::UpdateSkillsForLevel()'))
    load=player[player.index('void Player::_LoadSkills('):]
    ranges='switch (GetSkillRangeType(rcEntry))'+body(load,'switch (GetSkillRangeType(rcEntry))')
    methods.append('void Player::'+prefix+'Load(){uint16 value=this->value,max=cap;auto rcEntry=&generic;'+ranges+
                   'this->value=value;cap=max;if(!value)return;'+prefix+'Update();}')

mock=r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
using uint8=uint8_t;using uint16=uint16_t;using uint32=uint32_t;
constexpr int SKILL_DELETED=1,SKILL_NEW=2,SKILL_CHANGED=3,SKILL_UNCHANGED=0;
constexpr int SKILL_RANGE_LEVEL=0,SKILL_RANGE_LANGUAGE=1,SKILL_RANGE_MONO=2;
constexpr int CONFIG_ALWAYS_MAX_SKILL_FOR_LEVEL=0,SKILL_FLAG_ALWAYS_MAX_VALUE=16;
#define PLAYER_SKILL_VALUE_INDEX(x) (x)
#define SKILL_MAX(x) ((x)>>16)
#define SKILL_VALUE(x) ((x)&65535)
#define MAKE_SKILL_VALUE(a,b) ((a)|((b)<<16))
struct SkillInfo {uint32 Flags=1170;}generic;
using SkillRaceClassInfoEntry=SkillInfo;
SkillInfo const*GetSkillRaceClassInfo(uint32 id,uint32,uint32){return id==183||id==772?&generic:nullptr;}
int GetSkillRangeType(SkillInfo const*){return SKILL_RANGE_LEVEL;}
struct World{uint16 GetConfigMaxSkillValue()const{return 400;}bool getBoolConfig(int)const{return false;}}world;
World*sWorld=&world;
struct SkillStatusData{uint16 pos=0;int uState=SKILL_UNCHANGED;};
using SkillStatusMap=std::map<uint32,SkillStatusData>;
struct Player {
 uint16 level=80,value=400,cap=400;
 SkillStatusMap mSkillStatus{{183,{0,SKILL_UNCHANGED}}};
 uint16 GetMaxSkillValueForLevel()const{return level*5;}
 uint32 GetRace()const{return 1;}uint32 GetClass()const{return 2;}
 uint32 getRace()const{return GetRace();}uint32 getClass()const{return GetClass();}
 uint16 GetSkillMaxRankByPos(uint16)const{return cap;}
 void SetSkillRank(uint16,uint16 v){value=v;}void SetSkillMaxRank(uint16,uint16 v){cap=v;}
 uint32 GetUInt32Value(uint32)const{return value|(uint32(cap)<<16);}
 void SetUInt32Value(uint32,uint32 bits){value=bits&65535;cap=bits>>16;}
 void TcUpdate();void AcUpdate();void TcLoad();void AcLoad();
};
'''+''.join(methods)+r'''
int main(){
 for(uint32 skill:{183,772})for(uint16 level:{1,20,62,80})for(auto original:std::map<uint16,uint16>{{1,400},{5,350},{310,310},{400,400},{1,1}}){
  generic.Flags=skill==183?1170:1040;
  Player tc,ac;tc.level=ac.level=level;tc.value=ac.value=original.first;tc.cap=ac.cap=original.second;
  tc.mSkillStatus={{skill,{0,SKILL_UNCHANGED}}};ac.mSkillStatus=tc.mSkillStatus;
  tc.TcLoad();ac.AcLoad();assert(tc.value==level*5&&tc.cap==level*5);
  assert(tc.value==ac.value&&tc.cap==ac.cap);
 }
 Player zero;zero.value=0;zero.TcLoad();assert(zero.value==0);zero.AcLoad();assert(zero.value==0);
 std::cout<<"Protected TC/AC skill-load range and UpdateSkillsForLevel bodies PASS: Generic and Unholy already normalize to level*5 for value/cap independently of spell history; levels 1/20/62/80 and stale states; state/getters mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp,binary=Path(directory)/'generic.cpp',Path(directory)/'generic'
    cpp.write_text(mock)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    result=subprocess.check_output([str(binary)],text=True)
print(result,end='')
