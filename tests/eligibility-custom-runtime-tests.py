#!/usr/bin/env python3
"""AC's CustomSpells setting is independent of TC's AllSpells switch."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1];ac=Path(sys.argv[1])
manifest={name.strip():checksum for checksum,name in (line.split(None,1) for line in
          (root/'compatibility/tc335-acwotlk-v2/azerothcore-semantic.sha256').read_text().splitlines())}
for name in ('src/server/game/World/WorldConfig.cpp','src/server/game/World/WorldConfig.h',
             'src/server/game/Entities/Player/Player.cpp'):
    assert hashlib.sha256((ac/name).read_bytes()).hexdigest()==manifest[name],name
source=(ac/'src/server/game/Entities/Player/Player.cpp').read_text()
start=source.index('void Player::LearnCustomSpells()');end=source.index('\nvoid Player::LearnDefaultSkills()',start)
function=source[start:end]
config=(ac/'src/server/game/World/WorldConfig.cpp').read_text()
assignment=next(line.strip() for line in config.splitlines() if 'SetConfigValue<bool>(CONFIG_START_CUSTOM_SPELLS,' in line)
assert assignment=='SetConfigValue<bool>(CONFIG_START_CUSTOM_SPELLS, "PlayerStart.CustomSpells", false);'
program=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
using uint32=uint32_t;using PlayerCreateInfoSpells=std::vector<uint32>;
constexpr int CONFIG_START_CUSTOM_SPELLS=1,SPEC_MASK_ALL=3;
#define ASSERT(x) assert(x)
#define LOG_DEBUG(...) ((void)0)
struct World {
 bool supplied=false,option=false,custom=false;
 template<class T>void SetConfigValue(int key,char const* name,T fallback){
  assert(key==CONFIG_START_CUSTOM_SPELLS && std::strcmp(name,"PlayerStart.CustomSpells")==0 && !fallback);
  custom=supplied?option:fallback;
 }
 void Load(){@ASSIGNMENT@}
 bool getBoolConfig(int key)const{assert(key==CONFIG_START_CUSTOM_SPELLS);return custom;}
} world;
World* sWorld=&world;
struct PlayerInfo {PlayerCreateInfoSpells customSpells{2567,10140};};
struct Manager {
 PlayerInfo info;int reads=0;
 PlayerInfo const* GetPlayerInfo(uint32,uint32){++reads;return &info;}
} manager;
Manager* sObjectMgr=&manager;
struct Player {
 bool inWorld=false;std::vector<uint32>added,learned;
 uint32 getRace()const{return 1;}uint32 getClass()const{return 8;}
 bool IsInWorld()const{return inWorld;}
 void addSpell(uint32 s,int mask,bool learning){assert(mask==3&&learning);added.push_back(s);}
 void learnSpell(uint32 s){learned.push_back(s);}
 void LearnCustomSpells();
};
@FUNCTION@
int main(){
 Player p;
 world.Load();p.LearnCustomSpells();assert(manager.reads==0&&p.added.empty()&&p.learned.empty());
 world.supplied=true;world.option=false;world.Load();
 for(bool online:{false,true}){p.inWorld=online;p.LearnCustomSpells();}
 assert(manager.reads==0&&p.added.empty()&&p.learned.empty());
 world.option=true;world.Load();p.inWorld=false;p.LearnCustomSpells();
 assert(p.added==manager.info.customSpells&&p.learned.empty());
 p.inWorld=true;p.LearnCustomSpells();assert(p.learned==manager.info.customSpells&&manager.reads==2);
}
'''.replace('@ASSIGNMENT@',assignment).replace('@FUNCTION@',function)
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);(p/'test.cpp').write_text(program)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
print('Protected AC PlayerStart.CustomSpells: default/explicit off prevents regrants; enabled control calls native add/learn; mocked sinks, gameplay NOT TESTED.')
