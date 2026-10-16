#!/usr/bin/env python3
"""Execute the protected TC reset body with recording sinks; no core DB/runtime."""
from pathlib import Path
import subprocess
import sys
import tempfile

source=(Path(sys.argv[1])/'src/server/game/Entities/Player/Player.cpp').read_text()
start=source.index('bool Player::ResetTalents(')
brace=source.index('{',start);end=brace+1;depth=1
while depth:
    depth+=(source[end]=='{')-(source[end]=='}');end+=1
body=source[start:end]
mock=r'''
#include <cassert>
#include <cstdint>
#include <map>
#include <utility>
#include <vector>
#include <iostream>
using uint32=uint32_t;using int8=int8_t;
constexpr int AT_LOGIN_RESET_TALENTS=4,PET_SAVE_NOT_IN_SLOT=1,MAX_TALENT_RANK=5;
constexpr int SPELL_EFFECT_LEARN_SPELL=36,PLAYERSPELL_REMOVED=3;
using PlayerTalentMap=std::map<uint32,int>;
struct TalentEntry { uint32 TabID;uint32 SpellRank[5]; };
struct TalentTabEntry { uint32 ClassMask; };
struct TalentStore {
    TalentEntry rows[2]={{1,{12284,0,0,0,0}},{2,{17877,0,0,0,0}}};
    uint32 GetNumRows() { return 2; }
    TalentEntry const* LookupEntry(uint32 index) { return index<2?&rows[index]:nullptr; }
} sTalentStore;
struct TabStore {
    TalentTabEntry warrior{1},warlock{256};
    TalentTabEntry const* LookupEntry(uint32 id) { return id==1?&warrior:id==2?&warlock:nullptr; }
} sTalentTabStore;
struct SpellEffectInfo {
    uint32 Effect,TriggerSpell;
    bool IsEffect(uint32 value) const { return Effect==value; }
};
struct SpellInfo {
    std::vector<SpellEffectInfo> effects;
    std::vector<SpellEffectInfo> const& GetEffects() const { return effects; }
};
struct SpellMgr {
    SpellInfo warrior{{}},warlock{{{SPELL_EFFECT_LEARN_SPELL,900001}}};
    SpellInfo const* GetSpellInfo(uint32 id) { return id==17877?&warlock:&warrior; }
} mgr;
SpellMgr* sSpellMgr=&mgr;
struct ScriptMgr { template<class T> void OnPlayerTalentsReset(T*,bool) {} } scripts;
ScriptMgr* sScriptMgr=&scripts;
struct CharacterDatabaseTransaction {};
struct Database {
    int commits=0;
    CharacterDatabaseTransaction BeginTransaction() { return {}; }
    void CommitTransaction(CharacterDatabaseTransaction) { ++commits; }
} CharacterDatabase;
namespace WorldPackets { namespace Talent {
    struct TalentsInvoluntarilyReset {
        explicit TalentsInvoluntarilyReset(bool value) { assert(!value); }
        int Write() { return 1; }
    };
}}
struct Player {
    int flags=4,used=1,free=0,active=0,pets=0,talentSaves=0,spellSaves=0,packets=0;
    PlayerTalentMap maps[2]; std::vector<std::pair<uint32,bool>> removals;
    bool HasAtLoginFlag(int flag) { return flags&flag; }
    void RemoveAtLoginFlag(int flag,bool save) { assert(save);flags&=~flag; }
    uint32 CalculateTalentsPoints() { return 71; }
    uint32 GetUsedTalentCount() { return used; }
    void SetFreeTalentPoints(uint32 value) { free=value; }
    void RemovePet(void* pet,int mode,bool unslot) { assert(!pet&&mode==PET_SAVE_NOT_IN_SLOT&&unslot);++pets; }
    uint32 GetClassMask() { return 256; }
    void RemoveSpell(uint32 spell,bool disabled) {
        removals.emplace_back(spell,disabled);if(spell==17877)used=0;
    }
    int GetActiveTalentGroup() { return active; }
    PlayerTalentMap* GetTalentMap(int group) { return &maps[group]; }
    void _SaveTalents(CharacterDatabaseTransaction) { ++talentSaves; }
    void _SaveSpells(CharacterDatabaseTransaction) { ++spellSaves; }
    void SendDirectMessage(int packet) { assert(packet==1);++packets; }
    bool ResetTalents(bool involuntarily);
};
'''
mock+=body+r'''
int main() {
    for(int active: {0,1}) {
        Player p;p.active=active;p.flags=36;p.maps[active][17877]=0;
        assert(p.ResetTalents(true));
        assert(p.flags==32&&p.free==71&&p.used==0&&p.pets==1);
        assert(p.maps[active][17877]==PLAYERSPELL_REMOVED&&p.maps[1-active].empty());
        assert((p.removals==std::vector<std::pair<uint32,bool>>{{17877,true},{900001,true}}));
        assert(p.talentSaves==1&&p.spellSaves==1&&p.packets==1);
    }
    Player inactive;inactive.maps[0][17877]=0;inactive.maps[1][17877]=0;
    assert(inactive.ResetTalents(true));assert(inactive.maps[1][17877]==0);
    Player noUsed;noUsed.used=0;noUsed.maps[0][17877]=0;
    assert(!noUsed.ResetTalents(true));assert(noUsed.flags==0&&noUsed.maps[0][17877]==0);
    std::cout<<"Protected TC ResetTalents body: active group 0/1, flag preservation, class filter, dependent removal calls, ownership marking, save calls and free-point assignment passed; sinks mocked\n";
    std::cout<<"Controls: populated inactive build is not reset; zero used points returns before clearing ownership; policy guards required. Native gameplay NOT TESTED.\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory);cpp=path/'reset.cpp';exe=path/'reset'
    cpp.write_text(mock)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
