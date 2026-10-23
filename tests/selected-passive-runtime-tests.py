#!/usr/bin/env python3
"""Protected AC direct talent loading, passive casts and spec removal; mocked state."""
import hashlib,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];tc,ac=map(Path,sys.argv[1:])
for path,name in ((tc,'trinitycore'),(ac,'azerothcore')):
    rows=dict((p.strip().lstrip('*'),h)for h,p in (r.split(None,1)for r in
        (ROOT/'compatibility/tc335-acwotlk-v2'/f'{name}-semantic.sha256').read_text().splitlines()))
    relative='src/server/game/Entities/Player/Player.cpp'
    assert hashlib.sha256((path/relative).read_bytes()).hexdigest()==rows[relative]
t=(tc/relative).read_text();a=(ac/relative).read_text()
def body(source,marker):
    start=source.index('{',source.index(marker));end=start+1;depth=1
    while depth:depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
# TC only records talent ownership during load; it does not cast AddSpell.
tc_load=body(t,'void Player::_LoadTalents(')
assert 'AddTalent' in tc_load and 'AddSpell(' not in tc_load
assert all(call not in body(t,'bool Player::AddTalent(')for call in ('AddSpell(', 'CastSpell('))
program=r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <map>
#include <set>
#include <vector>
#include <iostream>
using uint8=uint8_t;using uint32=uint32_t;
constexpr uint32 SPELL_ATTR0_PASSIVE=64,SPELL_ATTR0_DO_NOT_DISPLAY=128,SPELL_EFFECT_LEARN_SPELL=36;
constexpr uint8 MAX_SPELL_EFFECTS=3,SPEC_MASK_ALL=3;
enum PlayerSpellState {PLAYERSPELL_UNCHANGED,PLAYERSPELL_NEW,PLAYERSPELL_CHANGED,PLAYERSPELL_REMOVED};
struct SpellInfo {bool passive=true;uint32 Stances=0;struct Effect{uint32 Effect=0,TriggerSpell=0;};std::array<Effect,3>Effects{};
 bool HasAttribute(uint32 bit)const{return bit==64&&passive;}bool IsPassive()const{return passive;}
 bool HasEffect(uint32 e)const{for(auto r:Effects)if(r.Effect==e)return true;return false;}};
struct TalentSpellPos {uint32 talent_id=0,rank=0;};
struct TalentEntry {uint32 TalentID=0;bool addToSpellBook=false;std::array<uint32,5>RankID{};};
std::map<uint32,TalentSpellPos>positions;
TalentSpellPos const*GetTalentSpellPos(uint32 s){auto it=positions.find(s);return it==positions.end()?nullptr:&it->second;}
struct Store{std::map<uint32,TalentEntry>data;TalentEntry const*LookupEntry(uint32 id){return &data.at(id);}}sTalentStore;
struct Manager {std::map<uint32,SpellInfo>data;SpellInfo const*GetSpellInfo(uint32 s){return &data.at(s);}bool IsAdditionalTalentSpell(uint32)const{return false;}}manager;
Manager*sSpellMgr=&manager;
struct SpellMgr{static bool CheckSpellValid(SpellInfo const*p,uint32,bool){return p;}};
struct PlayerTalent{PlayerSpellState State;uint8 specMask;uint32 talentID;bool inSpellBook;};
using PlayerTalentMap=std::map<uint32,PlayerTalent*>;
struct Field{uint32 value;template<class T>T Get()const{return static_cast<T>(value);}};
struct Rows {std::vector<std::array<Field,2>>data;size_t pos=0;Rows*operator->(){return this;}
 auto const&operator*()const{return data[pos];}bool NextRow(){return ++pos<data.size();}explicit operator bool()const{return !data.empty();}};
using PreparedQueryResult=Rows;
#define ASSERT(x) assert(x)
struct PetAura{};
struct Player{
 uint8 active=0;bool gate=true;PlayerTalentMap m_talents;uint32 m_usedTalentCount=0;
 std::set<uint32>auras;std::vector<uint32>cast;std::set<uint32>book;
 ~Player(){for(auto r:m_talents)delete r.second;}
 uint8 GetActiveSpecMask()const{return 1<<active;}bool isBeingLoaded()const{return true;}
 bool addTalent(uint32 spellId,uint8 addSpecMask,uint8 oldTalentRank) @ADD@
 void _LoadTalents(PreparedQueryResult result) @LOAD@
 void _addTalentAurasAndSpells(uint32 spellId) @AURAS@
 void _removeTalent(uint32,uint8){assert(false);}void _removeTalentAurasAndSpells(uint32 s){auras.erase(s);}
 void SendLearnPacket(uint32,bool){assert(false);}
 bool IsNeedCastPassiveSpellAtLearn(SpellInfo const*)const{return gate;}
 void CastSpell(Player*,uint32 s,bool trigger){assert(trigger);auras.insert(s);cast.push_back(s);}
 void _addSpell(uint32,uint8,bool){assert(false);} // learn-effect children forbidden by the contract
};
int main(){
 std::vector<std::vector<uint32>>families={{12295,12676,12677},{16462,16463,16464,16465,16466},
   {20205,20206,20207,20209,20208},{27839,27840},{48978,49390,49391,49392,49393}};
 uint32 family=0;
 for(auto const&ranks:families){++family;TalentEntry entry;entry.TalentID=family;
  for(size_t i=0;i<ranks.size();++i){entry.RankID[i]=ranks[i];positions[ranks[i]]={family,static_cast<uint32>(i)};manager.data[ranks[i]]={};}
  sTalentStore.data[family]=entry;
  for(uint8 active:{0,1}){
   Player p;p.active=active;uint32 lower=ranks[0],other=ranks[1];
   // Wrong higher stored aura is retired before AC login. Exact selected
   // talents, not a highest-rank recursion, drive every subsequent native cast.
   Rows rows;rows.data={{{lower,static_cast<uint32>(1<<active)}},{{other,static_cast<uint32>(1<<(1-active))}}};p._LoadTalents(rows);
   assert(p.auras==std::set<uint32>{lower}&&p.cast==std::vector<uint32>{lower});
   assert(p.m_usedTalentCount==1&&p.book.empty());
   assert(!p.m_talents.at(lower)->inSpellBook&&!p.m_talents.at(other)->inSpellBook);
   assert(p.m_talents.at(lower)->specMask==(1<<active));
   // Use the real passive consumer with the other spec's selected ID, as
   // ActivateSpec does after removing old spec auras. Dispatcher state mocked.
   p._removeTalentAurasAndSpells(lower);p.active=1-active;p._addTalentAurasAndSpells(other);
   assert(p.auras==std::set<uint32>{other}&&p.book.empty());
   Player merged;merged.active=active;Rows both;both.data={{{lower,3}}};merged._LoadTalents(both);
   assert(merged.auras==std::set<uint32>{lower}&&merged.m_talents.at(lower)->specMask==3);
   Player stance;stance.active=active;stance.gate=false;Rows gated;gated.data={{{lower,3}}};stance._LoadTalents(gated);
   assert(stance.auras.empty()&&stance.m_talents.at(lower)->specMask==3);
  }
 }
 std::cout<<"PASS: protected AC _LoadTalents/addTalent/passive consumer: exact selected ranks, both specs, merged masks, native stance gate, no spellbook insertion or temporary children.\n";
 std::cout<<"TC talent loader records ownership without a spell cast; spec dispatcher/catalog/state mocked; gameplay NOT TESTED.\n";
}
'''
program=program.replace('@ADD@',body(a,'bool Player::addTalent(')).replace('@LOAD@',body(a,'void Player::_LoadTalents(')).replace('@AURAS@',body(a,'void Player::_addTalentAurasAndSpells('))
with tempfile.TemporaryDirectory()as temp:
    p=Path(temp);(p/'direct.cpp').write_text(program)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(p/'direct.cpp'),'-o',str(p/'direct')],check=True)
    subprocess.run([str(p/'direct')],check=True)
