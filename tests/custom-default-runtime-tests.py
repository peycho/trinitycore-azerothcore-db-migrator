#!/usr/bin/env python3
"""Execute protected TC custom-start configuration and learning consumers.

Native function bodies are compiled unchanged; state/config/DB sinks are mocked.
This is behavioral verification, not worldserver login or gameplay acceptance.
"""
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile

tc=Path(sys.argv[1])
root=Path(__file__).resolve().parents[1]
manifest=dict((name.strip().lstrip('*'),digest) for digest,name in
              (line.split(None,1) for line in
               (root/'compatibility/tc335-acwotlk-v2/trinitycore-semantic.sha256').read_text().splitlines()))
for name in ('src/server/game/Entities/Player/Player.cpp','src/server/game/World/World.cpp'):
    assert hashlib.sha256((tc/name).read_bytes()).hexdigest()==manifest[name], 'Protected custom-start consumer differs'
source=(tc/'src/server/game/Entities/Player/Player.cpp').read_text()
start=source.index('void Player::LearnCustomSpells()')
end=source.index('\nvoid Player::LearnDefaultSkills()',start)
function=source[start:end]
world=(tc/'src/server/game/World/World.cpp').read_text()
assignment=next(line.strip() for line in world.splitlines()
                if 'm_bool_configs[CONFIG_START_ALL_SPELLS] =' in line)
assert 'GetBoolDefault("PlayerStart.AllSpells", false)' in assignment
program=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
using uint32=uint32_t;
using PlayerCreateInfoSpells=std::vector<uint32>;
constexpr int CONFIG_START_ALL_SPELLS=0;
#define ASSERT(x) assert(x)
#define TC_LOG_DEBUG(...) ((void)0)
struct Config {
    bool supplied=false,value=false;
    bool GetBoolDefault(char const* key,bool fallback) {
        assert(std::strcmp(key,"PlayerStart.AllSpells")==0 && !fallback);
        return supplied?value:fallback;
    }
} config;
Config* sConfigMgr=&config;
struct World {
    bool m_bool_configs[1]{};
    void LoadConfig(){@ASSIGNMENT@}
    bool getBoolConfig(int key) const {assert(key==CONFIG_START_ALL_SPELLS);return m_bool_configs[key];}
} world;
World* sWorld=&world;
struct PlayerInfo {PlayerCreateInfoSpells customSpells{48743,48707,25312,32999,16811,48073,48074,53308,53312};};
struct Manager {
    PlayerInfo info;int reads=0;
    PlayerInfo const* GetPlayerInfo(uint32,uint32) {++reads;return &info;}
} manager;
Manager* sObjectMgr=&manager;
struct Player {
    bool inWorld=false;std::vector<uint32> added,learned;
    uint32 GetRace()const{return 1;}uint32 GetClass()const{return 6;}
    bool IsInWorld()const{return inWorld;}
    void AddSpell(uint32 spell,bool active,bool learning,bool dependent,bool disabled) {
        assert(active && learning && dependent && !disabled);added.push_back(spell);
    }
    void LearnSpell(uint32 spell,bool dependent) {assert(dependent);learned.push_back(spell);}
    void LearnCustomSpells();
};
@FUNCTION@
int main(){
    Player player;
    world.LoadConfig();player.LearnCustomSpells();
    assert(manager.reads==0 && player.added.empty() && player.learned.empty());
    config.supplied=true;config.value=false;world.LoadConfig();
    for(bool online:{false,true}){player.inWorld=online;player.LearnCustomSpells();}
    assert(manager.reads==0 && player.added.empty() && player.learned.empty());
    config.value=true;world.LoadConfig();
    player.inWorld=false;player.LearnCustomSpells();
    assert(player.added==manager.info.customSpells && player.learned.empty());
    player.inWorld=true;player.LearnCustomSpells();
    assert(player.learned==manager.info.customSpells && manager.reads==2);
}
'''.replace('@ASSIGNMENT@',assignment).replace('@FUNCTION@',function)
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);(p/'test.cpp').write_text(program)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
print('Protected TC custom-start config/learning consumers passed (mocked sinks; gameplay NOT TESTED).')
