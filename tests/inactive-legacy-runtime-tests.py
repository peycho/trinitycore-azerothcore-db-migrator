#!/usr/bin/env python3
"""Protected known/active, client book and cast guards; state/targets mocked."""
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
tc,ac=map(Path,sys.argv[1:])


def block(source,marker):
    start=source.index('{',source.index(marker));end,depth=start+1,1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]


sources=[]
for repo,prefix in ((tc,'trinitycore'),(ac,'azerothcore')):
    manifest={n.strip().lstrip('*'):h for h,n in (line.split(None,1) for line in
        (ROOT/f'compatibility/tc335-acwotlk-v2/{prefix}-semantic.sha256').read_text().splitlines())}
    for path in ('src/server/game/Entities/Player/Player.cpp','src/server/game/Handlers/SpellHandler.cpp'):
        assert hashlib.sha256((repo/path).read_bytes()).hexdigest()==manifest[path]
    sources.append(((repo/'src/server/game/Entities/Player/Player.cpp').read_text(),
                    (repo/'src/server/game/Handlers/SpellHandler.cpp').read_text()))
tcp,tch=sources[0];acp,ach=sources[1]
acbook=acp[acp.index('for (PlayerSpellMap::const_iterator itr = m_spells.begin();',acp.index('void Player::SendInitialSpells()')):]
acloop=acbook[:acbook.index('{')]+block(acbook,'for (')
tcguard='if (!_player->HasActiveSpell(spellInfo->Id))'
acguard='if (!(spellInfo->Targets & TARGET_FLAG_GAMEOBJECT_ITEM)'
tcgate=tcguard+block(tch,tcguard)
acstart=ach.index(acguard);acend=ach.index('{',acstart)
acgate=ach[acstart:acend]+block(ach,acguard)
program=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <map>
#include <set>
#include <vector>
#include <iostream>
using uint8=uint8_t;using uint16=uint16_t;using uint32=uint32_t;
constexpr uint32 PLAYERSPELL_UNCHANGED=0,PLAYERSPELL_REMOVED=3,PLAYERSPELL_TEMPORARY=4;
constexpr uint32 TARGET_FLAG_GAMEOBJECT_ITEM=0x4000,TRIGGERED_FULL_MASK=1,SPELL_AURA_PERIODIC_TRIGGER_SPELL_FROM_CLIENT=1;
struct SpellInfo{uint32 Id=0,Targets=1;bool IsPassive()const{return false;}};
struct GameObject{SpellInfo const*locked=nullptr;template<class P>SpellInfo const*GetSpellForLock(P*)const{return locked;}};
struct Targets{GameObject*go=nullptr;GameObject*GetGOTarget()const{return go;}};
namespace WorldPackets::Spells{
 struct Entry{uint32 SpellID=0,ActionBarSlot=0;};
 struct InitialSpells{bool InitialLogin=false;std::vector<Entry>Spells;InitialSpells*Write(){return this;}};
}
struct History{void WritePacket(WorldPackets::Spells::InitialSpells*){}};
struct TcSpell{uint32 state=PLAYERSPELL_UNCHANGED;bool active=false,disabled=false;};
struct TcPlayer{
 using PlayerSpellMap=std::map<uint32,TcSpell>;PlayerSpellMap m_spells;History history;std::set<uint32>sent;bool externalTrigger=false;
 bool HasSpell(uint32 spell)const @TC_KNOWN@
 bool HasActiveSpell(uint32 spell)const @TC_ACTIVE@
 void SendInitialSpells() @TC_BOOK@
 bool IsLoading()const{return true;}History*GetSpellHistory(){return &history;}
 void SendDirectMessage(WorldPackets::Spells::InitialSpells*p){sent.clear();for(auto const&e:p->Spells)sent.insert(e.SpellID);}
 bool HasAuraTypeWithTriggerSpell(uint32,uint32)const{return externalTrigger;}
};
struct AcSpell{uint32 State=PLAYERSPELL_UNCHANGED;bool Active=true;uint8 mask=3;bool IsInSpec(uint8 s)const{return mask&(1<<s);}};
struct Packet{std::set<uint32>ids;Packet&operator<<(uint32 v){ids.insert(v);return *this;}Packet&operator<<(uint16){return *this;}};
struct Shape{std::array<uint32,8>stanceSpell{};};
struct AcPlayer{
 using PlayerSpellMap=std::map<uint32,AcSpell*>;PlayerSpellMap m_spells;uint8 m_activeSpec=0;
 bool HasSpell(uint32 spell)const @AC_KNOWN@
 bool HasActiveSpell(uint32 spell)const @AC_ACTIVE@
 AcPlayer*ToPlayer(){return this;}uint8 GetActiveSpec()const{return m_activeSpec;}
 std::set<uint32>ClientBook(){Packet data;uint16 spellCount=0;Shape const*shapeInfo=nullptr;
 @AC_BOOK@
 assert(spellCount==data.ids.size());return data.ids;}
};
struct TcRequest{TcPlayer*_player;bool accepted=false;
 void Cast(SpellInfo const*spellInfo,Targets targets){uint32 triggerFlag=0;(void)triggerFlag;
 @TC_GATE@
 accepted=true;}};
struct AcRequest{AcPlayer*mover;bool accepted=false;
 void Cast(SpellInfo const*spellInfo,Targets targets){uint32 spellId=spellInfo->Id;
 @AC_GATE@
 accepted=true;}};
int main(){
 std::vector<uint32>catalog={23892,23893,23894,25251,30335};
 for(size_t anchor=0;anchor<catalog.size();++anchor){
  TcPlayer before,after;
  before.m_spells[23881]={0,true,false};after.m_spells[23881]={0,true,false};
  for(auto id:catalog)before.m_spells[id]={0,id==catalog[anchor],false};
  after.m_spells[catalog[anchor]]={0,true,false};
  before.SendInitialSpells();after.SendInitialSpells();assert(before.sent==after.sent);
  for(uint8 active:{0,1}){
   AcPlayer target;target.m_activeSpec=active;AcSpell talent,retained;
   target.m_spells[23881]=&talent;target.m_spells[catalog[anchor]]=&retained;
   assert(target.ClientBook()==after.sent);
   // Negative representation control: copying all known ordinary singleton
   // rows as active in mask 3 makes previously inactive entries usable.
   AcPlayer unsafeCopy;unsafeCopy.m_activeSpec=active;std::array<AcSpell,5>copied;
   unsafeCopy.m_spells[23881]=&talent;
   for(size_t i=0;i<catalog.size();++i)unsafeCopy.m_spells[catalog[i]]=&copied[i];
   assert(unsafeCopy.ClientBook()!=before.sent);
   for(auto id:catalog){
    SpellInfo info{id};GameObject lock{&info};
    assert(before.HasSpell(id));assert(after.HasSpell(id)==(id==catalog[anchor]));
    assert(before.HasActiveSpell(id)==after.HasActiveSpell(id));
    assert(target.HasActiveSpell(id)==after.HasActiveSpell(id));
    if(id!=catalog[anchor])assert(!before.HasActiveSpell(id)&&unsafeCopy.HasActiveSpell(id));
    // Normal requests and independent lock overrides keep their native result.
    for(bool lockOverride:{false,true}){
     Targets targets{lockOverride?&lock:nullptr};
     TcRequest old{&before},fixed{&after};AcRequest migrated{&target};
     old.Cast(&info,targets);fixed.Cast(&info,targets);migrated.Cast(&info,targets);
     assert(old.accepted==fixed.accepted&&fixed.accepted==migrated.accepted);
    }
    // TC's separate periodic-client-trigger override is book-independent;
    // native AC differences are not changed or claimed fixed by retirement.
    before.externalTrigger=after.externalTrigger=true;
    TcRequest old{&before},fixed{&after};old.Cast(&info,{});fixed.Cast(&info,{});assert(old.accepted==fixed.accepted);
    before.externalTrigger=after.externalTrigger=false;
   }
  }
 }
 std::cout<<"PASS protected TC/AC HasSpell, HasActiveSpell, initial spellbook and player cast gates: inactive history disappears from known membership while visible/normal castable spells and independent lock routes stay unchanged; native override differences retained; state/targets/packets mocked, gameplay NOT TESTED.\n";
}
'''
values={'TC_KNOWN':block(tcp,'bool Player::HasSpell('),'TC_ACTIVE':block(tcp,'bool Player::HasActiveSpell('),
        'TC_BOOK':block(tcp,'void Player::SendInitialSpells('),'AC_KNOWN':block(acp,'bool Player::HasSpell('),
        'AC_ACTIVE':block(acp,'bool Player::HasActiveSpell('),'AC_BOOK':acloop,'TC_GATE':tcgate,'AC_GATE':acgate}
for name,value in values.items():program=program.replace('@'+name+'@',value)
with tempfile.TemporaryDirectory() as temp:
    path=Path(temp);(path/'inactive.cpp').write_text(program)
    subprocess.run(['g++','-std=c++20','-Wall','-Wextra','-Werror',str(path/'inactive.cpp'),'-o',str(path/'inactive')],check=True)
    subprocess.run([str(path/'inactive')],check=True)
