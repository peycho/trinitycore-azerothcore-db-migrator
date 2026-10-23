from pathlib import Path
import json,subprocess,tempfile,hashlib,sys
ROOT=Path(__file__).resolve().parents[1];tc_path,ac_path=map(Path,sys.argv[1:]);sys.path.insert(0,str(ROOT/'lib'))
from cleanup_specializations import native_sources

def body(s,marker):
 start=s.index('{',s.index(marker));end=start+1;depth=1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[start:end]

proof=native_sources({'tc_source':tc_path,'ac_source':ac_path});parts=[]
for core,repo in [('tc','TrinityCore'),('ac','azerothcore-wotlk')]:
 path=tc_path if core=='tc'else ac_path
 for name,expected in proof[core].items():assert hashlib.sha256((path/name).read_bytes()).hexdigest()==expected
 text=(path/'src/server/game/Entities/Player/Player.cpp').read_text()
 if core=='tc':
  declarations='struct Row{int state=1;bool active=false,disabled=false;};using PlayerSpellMap=std::map<uint32,Row>;'
  storage=text;marker='if (proto->GetRequiredSpell() != 0 && !HasSpell(proto->GetRequiredSpell()))'
 else:
  declarations='struct Row{int State=1;bool Active=true;int mask=3;bool IsInSpec(int spec)const{return mask&(1<<spec);}};using PlayerSpellMap=std::map<uint32,Row*>;'
  storage=(path/'src/server/game/Entities/Player/PlayerStorage.cpp').read_text();marker='if (proto->RequiredSpell != 0 && !HasSpell(proto->RequiredSpell))'
 start=storage.index(marker)
 if core=='tc':gate=storage[start:storage.index(';',start)+1]
 else:gate=marker+body(storage,marker)
 gate=gate.replace('EQUIP_ERR_NO_REQUIRED_PROFICIENCY','DENIED').replace('EQUIP_ERR_PROFICIENCY_NEEDED','DENIED')
 part='namespace '+core+'{'+declarations+'struct Item{uint32 RequiredSpell;uint32 GetRequiredSpell()const{return RequiredSpell;}};'
 part+='struct Player{PlayerSpellMap m_spells;int m_activeSpec=0;bool HasSpell(uint32)const;bool HasActiveSpell(uint32)const;bool CanUse(Item const*proto)const;};'
 for name in ('HasSpell','HasActiveSpell'):part+='bool Player::'+name+'(uint32 spell)const'+body(text,'bool Player::'+name+'(')
 part+='bool Player::CanUse(Item const*proto)const{'+gate+'\nreturn ALLOWED;}'
 if core=='tc':
  npc=(path/'src/server/scripts/World/npc_professions.cpp').read_text()
  for name in ('HasTailorSpell','HasWeaponSub'):part+='bool '+name+'(Player*player)'+body(npc,'inline bool '+name+'(')
 part+='}';parts.append(part)
main=r'''
int main(){
 tc::Player p;p.m_spells[26797]={1,false,false};p.m_spells[26798]={1,true,false};
 tc::Item retired{26797},retained{26798};
 assert(p.HasSpell(26797)&&!p.HasActiveSpell(26797)&&tc::HasTailorSpell(&p));
 assert(p.CanUse(&retired)&&p.CanUse(&retained));p.m_spells.erase(26797);
 assert(!p.CanUse(&retired)&&p.CanUse(&retained)&&tc::HasTailorSpell(&p));
 p.m_spells[17039]={1,false,false};p.m_spells[17041]={1,true,false};assert(tc::HasWeaponSub(&p));
 p.m_spells.erase(17039);assert(tc::HasWeaponSub(&p)&&p.HasActiveSpell(17041));
 ac::Player a;ac::Row old,choice;a.m_spells[26797]=&old;a.m_spells[26798]=&choice;
 ac::Item ao{26797},ak{26798};for(int spec:{0,1}){a.m_activeSpec=spec;assert(a.CanUse(&ao)&&a.CanUse(&ak));}
 a.m_spells.erase(26797);assert(!a.CanUse(&ao)&&a.CanUse(&ak));
 std::cout<<"PASS pinned TC/AC known-spell equipment gates and TC specialization NPC gates with mocked state: inactive TC specialization remains known and satisfies RequiredSpell; deleting it changes eligibility while retained active choice survives. No production or gameplay test.\n";
}
'''
preamble='#include <map>\n#include <cstdint>\n#include <cassert>\n#include <iostream>\nusing uint32=uint32_t;constexpr int PLAYERSPELL_REMOVED=2;constexpr bool DENIED=false,ALLOWED=true;constexpr uint32 S_MOONCLOTH=26798,S_SPELLFIRE=26797,S_SHADOWEAVE=26801,S_HAMMER=17040,S_AXE=17041,S_SWORD=17039;\n'
with tempfile.TemporaryDirectory()as d:
 cpp=Path(d)/'spec.cpp';exe=Path(d)/'spec';cpp.write_text(preamble+''.join(parts)+main)
 subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
