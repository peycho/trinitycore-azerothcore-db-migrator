#!/usr/bin/env python3
"""Execute protected TC ownership/sibling code; runtime state getters mocked."""
from pathlib import Path
import subprocess
import sys
import tempfile

source=(Path(sys.argv[1])/'src/server/game/Entities/Player/Player.cpp').read_text()
def block(start):
    opening=source.index('{',start);end,depth=opening+1,1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
add_talent=block(source.index('bool Player::AddTalent('))
start=source.index('// talent: unlearn all other talent ranks',source.index('bool Player::AddSpell('))
sibling=block(source.index('if (TalentSpellPos const*',start))
previous_start=source.index('else if (uint32 prev_spell =',start)
previous=block(previous_start).removeprefix('else ')
mock=r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
using uint8=uint8_t;using uint32=uint32_t;
constexpr int MAX_TALENT_RANK=5,PLAYERSPELL_UNCHANGED=0,PLAYERSPELL_NEW=1,PLAYERSPELL_REMOVED=2;
#define TC_LOG_ERROR(...) ((void)0)
struct SpellInfo {};
struct SpellMgr { SpellInfo entry; SpellInfo const* GetSpellInfo(uint32) { return &entry; }
 uint32 GetPrevSpellInChain(uint32 id)const{return id==21084?20154:0;}
 static bool IsSpellValid(SpellInfo const* s,void*,bool) { return s!=nullptr; } };
SpellMgr manager;SpellMgr* sSpellMgr=&manager;
struct TalentSpellPos { uint32 talent_id=1; };
TalentSpellPos position;
TalentSpellPos const* GetTalentSpellPos(uint32 id) { return id>=600 && id<=602?&position:nullptr; }
struct TalentEntry { std::array<uint32,5> SpellRank{600,601,602,0,0}; };
struct TalentStore { TalentEntry entry; TalentEntry const* LookupEntry(uint32) { return &entry; } };
TalentStore sTalentStore;
using PlayerTalentMap=std::map<uint32,int>;
struct Player {
 std::array<PlayerTalentMap,2> talents;
 std::set<uint32> spellBook;
 std::map<uint32,bool> dependentRows;
 bool IsInWorld() const { return false; }
 void DeleteSpellFromAllPlayers(uint32) { assert(false); }
 PlayerTalentMap* GetTalentMap(uint8 group) { return &talents.at(group); }
 bool AddTalent(uint32 spellId,uint8 spec,bool learning);
 void LoadDisabledSiblingPass(uint32 spellId);
 void LoadPreviousRank(uint32 spellId,bool active,bool disabled,bool fromSkill);
 void AddSpell(uint32 spellId,bool active,bool,bool dependent,bool disabled,bool,bool fromSkill){
  LoadPreviousRank(spellId,active,disabled,fromSkill);spellBook.insert(spellId);dependentRows[spellId]=dependent;
 }
 void LearnSpell(uint32,bool,bool){assert(false);}
 void RemoveSpell(uint32 spell,bool disabled,bool lower) { assert(!disabled && !lower);spellBook.erase(spell); }
};
'''
main=r'''
int main() {
 Player highSeal;highSeal.AddSpell(21084,true,false,false,false,true,false);
 assert((highSeal.spellBook==std::set<uint32>{20154,21084}));
 assert(highSeal.dependentRows.at(20154)&&!highSeal.dependentRows.at(21084));
 Player lowSeal;lowSeal.AddSpell(20154,true,false,false,false,true,false);
 assert(lowSeal.spellBook==std::set<uint32>{20154});
 Player canonical;
 assert(canonical.AddTalent(600,0,false));
 assert(canonical.AddTalent(602,1,false));
 canonical.spellBook={600,602};
 assert(canonical.talents[0].count(600) && canonical.talents[1].count(602));
 Player stale=canonical;
 // A newly loaded stale rank reaches this native branch before its disabled
 // early return. Selected ownership survives, but spellbook siblings do not.
 stale.LoadDisabledSiblingPass(601);
 assert(stale.spellBook.empty());
 assert(stale.talents==canonical.talents);
 // Changing one selected spec does not select the highest rank in both.
 Player separate=canonical;
 assert(separate.AddTalent(601,0,false));
 assert(separate.talents[0].at(600)==PLAYERSPELL_REMOVED);
 assert(separate.talents[0].at(601)==PLAYERSPELL_UNCHANGED);
 assert(separate.talents[1].at(602)==PLAYERSPELL_UNCHANGED);
 std::cout << "Protected TC AddTalent/spec maps and AddSpell sibling branch passed; map/removal sinks mocked; full native loading/gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp=Path(directory)/'rank.cpp';binary=Path(directory)/'rank-tests'
    cpp.write_text(mock+'\n'+add_talent+'\nvoid Player::LoadDisabledSiblingPass(uint32 spellId) {\n'+sibling+'\n}\n'
                  +'void Player::LoadPreviousRank(uint32 spellId,bool active,bool disabled,bool fromSkill){'+previous+'}\n'+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
