from pathlib import Path
import hashlib,json,subprocess,tempfile,sys
ROOT=Path(__file__).resolve().parents[1];tc_path,ac_path=map(Path,sys.argv[1:])

def body(s,marker):
 start=s.index('{',s.index(marker));end=start+1;depth=1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[start:end]

parts=[];hashes={}
for core,repo,prefix in [('tc','TrinityCore','trinitycore'),('ac','azerothcore-wotlk','azerothcore')]:
 manifest=dict((n.strip().lstrip('*'),h)for h,n in(line.split(None,1)for line in(ROOT/'compatibility/tc335-acwotlk-v2'/f'{prefix}-semantic.sha256').read_text().splitlines()))
 name='src/server/game/Entities/Player/Player.cpp';raw=((tc_path if core=='tc' else ac_path)/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==manifest[name];text=raw.decode();hashes[core]={name:manifest[name]}
 for extra in ('src/server/game/Handlers/SpellHandler.cpp','src/server/game/Spells/SpellInfo.cpp'):
  data=((tc_path if core=='tc' else ac_path)/extra).read_bytes();assert hashlib.sha256(data).hexdigest()==manifest[extra];hashes[core][extra]=manifest[extra]
 scope='namespace '+core+'{'
 if core=='tc':scope+='struct Row{int state=1;bool active=false,disabled=false;};using PlayerSpellMap=std::map<uint32,Row>;'
 else:scope+='struct Row{int State=1;bool Active=true;int mask=3;bool IsInSpec(int spec)const{return mask&(1<<spec);}};using PlayerSpellMap=std::map<uint32,Row*>;'
 scope+='struct Player{PlayerSpellMap m_spells;int m_activeSpec=0;bool HasSpell(uint32)const;bool HasActiveSpell(uint32)const;};'
 for method in ('HasSpell','HasActiveSpell'):scope+='bool Player::'+method+'(uint32 spell)const'+body(text,'bool Player::'+method+'(')
 # Exact AddSpell first-rank accounting gate: no active-flag condition.
 start=text.index('if (uint32 freeProfs = GetFreePrimaryProfessionPoints())')
 gate='if (uint32 freeProfs = GetFreePrimaryProfessionPoints())'+body(text[start:],'if (uint32 freeProfs = GetFreePrimaryProfessionPoints())')
 scope+='struct Info{bool IsPrimaryProfessionFirstRank(){return true;}};struct Counter{uint32 free=2;uint32 GetFreePrimaryProfessionPoints(){return free;}void SetFreePrimaryProfessions(uint32 n){free=n;}void LoadKnown(bool active){(void)active;Info info;auto spellInfo=&info;'+gate+'}};}'
 parts.append(scope)
main=r'''
int main(){
 for(uint32 spell:{2108,26790,29844,30350,32549}){
  tc::Player source;source.m_spells[spell]={1,false,false};assert(source.HasSpell(spell)&&!source.HasActiveSpell(spell));
  ac::Player target;ac::Row row;target.m_spells[spell]=&row;
  for(int spec:{0,1}){target.m_activeSpec=spec;assert(target.HasSpell(spell)&&target.HasActiveSpell(spell));}
  source.m_spells[spell].active=true;assert(source.HasSpell(spell)&&source.HasActiveSpell(spell));
  source.m_spells[spell].active=false;assert(source.HasSpell(spell)&&!source.HasActiveSpell(spell));
 }
 tc::Counter inactive,active,absent;inactive.LoadKnown(false);active.LoadKnown(true);
 assert(inactive.free==1&&active.free==1&&absent.free==2);
 ac::Counter ai,aa,missing;ai.LoadKnown(false);aa.LoadKnown(true);assert(ai.free==1&&aa.free==1&&missing.free==2);
 std::cout<<"PASS protected TC/AC HasSpell/HasActiveSpell and profession first-rank accounting: TC inactive rows remain known but inactive; an active AC persistent representation permits the action; active-flag changes retain known-row accounting, omission changes it. Mocked state, full gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory()as d:
 cpp=Path(d)/'profession.cpp';exe=Path(d)/'profession';cpp.write_text('#include <map>\n#include <cstdint>\n#include <cassert>\n#include <iostream>\nusing uint32=uint32_t;constexpr int PLAYERSPELL_REMOVED=2;\n'+''.join(parts)+main)
 subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
print(json.dumps({'status':'PASS_MOCKED_CONSUMERS','protected_sources':hashes,'source_changes':False,'full_gameplay':'NOT TESTED'},indent=2)+'\n')

# Compile the native ranked-skill branches with recording setters. Existing
# values/caps above the spell's minimum/tier must survive inactive AND active
# known-row loading. No game server or cast execution is implied.
branches=[]
for core,path in [('tc',tc_path),('ac',ac_path)]:
 text=(path/'src/server/game/Entities/Player/Player.cpp').read_text()
 if core=='tc':
  marker='if (spellLearnSkill->skill != fromSkill)';branch=marker+body(text,marker)
 else:
  marker='    // xinef: set appropriate skill value';fragment=text[text.index(marker):]
  branch='if (spellLearnSkill)'+body(fragment,'if (spellLearnSkill)')
 branches.append('void '+core+'Skill(bool active){(void)active;auto spellLearnSkill=&node;uint32 fromSkill=0;uint32 maxskill=400;(void)fromSkill;(void)maxskill;'+branch+'}')
mock=r'''
#include <cassert>
#include <cstdint>
#include <iostream>
using uint32=uint32_t;
constexpr int CONFIG_ALWAYS_MAXSKILL=1;
struct Node{uint32 skill=165,step=1,value=1,maxvalue=75;}node;
uint32 value=78,cap=150,calls=0;
struct World{bool getBoolConfig(int){return true;}}world;auto sWorld=&world;
uint32 GetPureSkillValue(uint32){return value;}uint32 GetPureMaxSkillValue(uint32){return cap;}
uint32 GetMaxSkillValueForLevel(){return 400;}bool IsProfessionOrRidingSkill(uint32){return true;}
void SetSkill(uint32,uint32,uint32 v,uint32 m){value=v;cap=m;++calls;}
'''
main=r'''
int main(){for(bool active:{false,true})for(auto load:{tcSkill,acSkill}){
 for(uint32 skill:{165,197,164,202})for(uint32 storedCap:{75,150,225,300,375,450}){
  node={skill,1,1,75};value=1;cap=storedCap;calls=0;load(active);
  assert(value==1&&cap==storedCap&&calls==1);
 }
 node={165,1,1,75};value=78;cap=150;calls=0;load(active);assert(value==78&&cap==150&&calls==1);
 node={197,5,1,375};value=1;cap=375;load(active);assert(value==1&&cap==375);
 node={202,5,1,375};value=375;cap=375;load(active);assert(value==375&&cap==375);
 }std::cout<<"PASS protected TC/AC ranked-skill loading branches: retained crafting values/caps survive known-row loading regardless of active flag, including AlwaysMaxSkill config. Recording state; gameplay NOT TESTED\n";}
'''
with tempfile.TemporaryDirectory()as d:
 cpp=Path(d)/'skills.cpp';exe=Path(d)/'skills';cpp.write_text(mock+''.join(branches)+main)
 subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
