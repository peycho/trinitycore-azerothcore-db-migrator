#!/usr/bin/env python3
"""Execute pinned TC's validator with catalog getters mocked; no worldserver."""
from pathlib import Path
import subprocess
import sys
import tempfile

core=Path(sys.argv[1])
source=(core/'src/server/game/Spells/SpellMgr.cpp').read_text()
start=source.index('bool SpellMgr::IsSpellValid(')
opening=source.index('{',start)
end,depth=opening+1,1
while depth:
    depth+=(source[end]=='{')-(source[end]=='}');end+=1
function=source[start:end]
mock=r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
using uint8=uint8_t; using uint32=uint32_t;
constexpr int SPELL_EFFECT_CREATE_ITEM=24,SPELL_EFFECT_CREATE_ITEM_2=157,SPELL_EFFECT_LEARN_SPELL=36,MAX_SPELL_REAGENTS=8;
#define TC_LOG_ERROR(...) ((void)0)
struct Player { void* GetSession() { return nullptr; } };
struct ChatHandler { explicit ChatHandler(void*) {} template<class... T> void PSendSysMessage(T...) {} };
struct SpellEffectInfo { int Effect=0; uint32 TriggerSpell=0,ItemType=0; };
struct SpellInfo {
 uint32 Id=0;
 std::array<SpellEffectInfo,3> Effects{};
 std::array<int32_t,8> Reagent{};
 bool IsLootCrafting() const { return false; }
 auto const& GetEffects() const { return Effects; }
};
struct ObjectMgr { std::set<uint32> items; bool GetItemTemplate(uint32 id) { return items.count(id); } };
struct SpellMgr {
 std::map<uint32,SpellInfo> spells;
 SpellInfo const* GetSpellInfo(uint32 id) { auto it=spells.find(id);return it==spells.end()?nullptr:&it->second; }
 static bool IsSpellValid(SpellInfo const*,Player*,bool);
};
ObjectMgr objects; ObjectMgr* sObjectMgr=&objects;
SpellMgr manager; SpellMgr* sSpellMgr=&manager;
'''
main=r'''
int main() {
 manager.spells[50334].Id=50334;
 manager.spells[51266].Id=51266;
 manager.spells[51266].Effects={SpellEffectInfo{36,50321,0},SpellEffectInfo{36,50334,0},{}};
 assert(!SpellMgr::IsSpellValid(nullptr,nullptr,false));
 assert(SpellMgr::IsSpellValid(manager.GetSpellInfo(50334),nullptr,false));
 assert(!SpellMgr::IsSpellValid(manager.GetSpellInfo(51266),nullptr,false));
 // Effective custom target data must change the decision, not be ignored.
 manager.spells[50321].Id=50321;
 assert(SpellMgr::IsSpellValid(manager.GetSpellInfo(51266),nullptr,false));
 manager.spells[50321].Effects[0]={24,0,42};
 assert(!SpellMgr::IsSpellValid(manager.GetSpellInfo(51266),nullptr,false));
 objects.items.insert(42);
 assert(SpellMgr::IsSpellValid(manager.GetSpellInfo(51266),nullptr,false));
 manager.spells[1831].Id=1831;
 manager.spells[1831].Effects[0]={36,11113,0};
 assert(!SpellMgr::IsSpellValid(manager.GetSpellInfo(1831),nullptr,false));
 manager.spells[11113].Id=11113;
 assert(SpellMgr::IsSpellValid(manager.GetSpellInfo(1831),nullptr,false));
 std::cout << "Protected TC IsSpellValid: missing child rejects whole teacher; custom valid target and Blast Wave controls passed; catalog getters mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp=Path(directory)/'teacher.cpp';binary=Path(directory)/'teacher-tests'
    cpp.write_text(mock+'\n'+function+'\n'+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
