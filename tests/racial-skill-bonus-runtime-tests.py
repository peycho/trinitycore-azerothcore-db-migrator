#!/usr/bin/env python3
"""Protected Gemcutting aura/bonus consumers; state sinks mocked, no gameplay."""
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def body(text,signature):
    start=text.index('{',text.index(signature));end=start+1;depth=1
    while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

mock=r'''
#include <cassert>
#include <cstdint>
#include <map>
#include <iostream>
using uint8=uint8_t;using uint32=uint32_t;using int32=int32_t;using int16=int16_t;
constexpr int SKILL_DELETED=2,AURA_EFFECT_HANDLE_CHANGE_AMOUNT_MASK=1,AURA_EFFECT_HANDLE_SKILL=2;
constexpr int SPELL_AURA_MOD_SKILL_TALENT=98,SKILL_DEFENSE=95;
uint32 PLAYER_SKILL_BONUS_INDEX(uint32 p){return p;}
int16 SKILL_TEMP_BONUS(uint32 v){return int16(v&65535);}
int16 SKILL_PERM_BONUS(uint32 v){return int16(v>>16);}
uint32 MAKE_SKILL_BONUS(int16 temp,int16 perm){return uint32(uint16_t(temp))|(uint32(uint16_t(perm))<<16);}
struct Status{uint32 pos;int uState;};using SkillStatusMap=std::map<uint32,Status>;
struct Player{
 SkillStatusMap mSkillStatus;uint32 bonus=0,value=375,cap=450;int writes=0;
 bool IsPlayer(){return true;}Player* ToPlayer(){return this;}
 void ModifySkillBonus(uint32,int32,bool);
 uint32 GetUInt32Value(uint32){return bonus;}
 void SetUInt32Value(uint32,uint32 v){bonus=v;++writes;}
 int16 GetSkillPermBonusByPos(uint32){return SKILL_PERM_BONUS(bonus);}
 int16 GetSkillTempBonusByPos(uint32){return SKILL_TEMP_BONUS(bonus);}
 void SetSkillPermBonus(uint32,int32 v){bonus=MAKE_SKILL_BONUS(SKILL_TEMP_BONUS(bonus),v);++writes;}
 void SetSkillTempBonus(uint32,int32 v){bonus=MAKE_SKILL_BONUS(v,SKILL_PERM_BONUS(bonus));++writes;}
 void UpdateDefenseBonusesMod(){assert(false);}
};using Unit=Player;
struct AuraApplication{Player* player;Player* GetTarget()const{return player;}};
struct AuraEffect{
 uint32 GetMiscValue()const{return 755;}int32 GetAmount()const{return 5;}
 int GetAuraType()const{return 98;}
 void HandleAuraModSkill(AuraApplication const*,uint8,bool)const;
};
'''
parts=[];hashes={}
for core,path in zip(('trinitycore','azerothcore'),map(Path,sys.argv[1:])):
    manifest=dict((n.strip().lstrip('*'),h)for h,n in(line.split(None,1)for line in(ROOT/'compatibility/tc335-acwotlk-v2'/f'{core}-semantic.sha256').read_text().splitlines()))
    sources={}
    for file in ('src/server/game/Entities/Player/Player.cpp','src/server/game/Spells/Auras/SpellAuraEffects.cpp'):
        raw=(path/file).read_bytes();assert hashlib.sha256(raw).hexdigest()==manifest[file],file
        sources[file]=raw.decode()
    hashes[core]={f:manifest[f]for f in sources}
    parts.append('')
    # Separate namespaces allow the exact TC and AC methods to coexist.
    parts[-1]='namespace '+core+'{'+mock[mock.index('struct Status'):]+\
        'void Player::ModifySkillBonus(uint32 skillid,int32 val,bool talent)'+body(sources['src/server/game/Entities/Player/Player.cpp'],'void Player::ModifySkillBonus(')+\
        'void AuraEffect::HandleAuraModSkill(AuraApplication const* aurApp,uint8 mode,bool apply)const'+body(sources['src/server/game/Spells/Auras/SpellAuraEffects.cpp'],'void AuraEffect::HandleAuraModSkill(')+\
        '''void check(){
 Player p;p.mSkillStatus[755]={0,1};AuraApplication app{&p};AuraEffect aura;
 aura.HandleAuraModSkill(&app,AURA_EFFECT_HANDLE_SKILL,true);
 assert(SKILL_PERM_BONUS(p.bonus)==5&&p.value==375&&p.cap==450&&p.writes==1);
 aura.HandleAuraModSkill(&app,AURA_EFFECT_HANDLE_SKILL,false);
 assert(p.bonus==0&&p.value==375&&p.cap==450&&p.writes==2);
 p.mSkillStatus.clear();aura.HandleAuraModSkill(&app,AURA_EFFECT_HANDLE_SKILL,true);
 assert(p.mSkillStatus.empty()&&p.writes==2);
 p.mSkillStatus[755]={0,SKILL_DELETED};aura.HandleAuraModSkill(&app,AURA_EFFECT_HANDLE_SKILL,true);
 assert(p.writes==2);
 aura.HandleAuraModSkill(&app,0,true);assert(p.writes==2);
 }}'''
assert len(parts)==2,'Supply TC and AC source directories'
with tempfile.TemporaryDirectory()as d:
    cpp=Path(d)/'bonus.cpp';exe=Path(d)/'bonus'
    cpp.write_text(mock[:mock.index('struct Status')]+''.join(parts)+'int main(){trinitycore::check();azerothcore::check();std::cout<<"PASS protected TC/AC Gemcutting +5 bonus only; stored skill values/caps unchanged; no missing skill created; gameplay NOT TESTED\\n";}')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print(json.dumps({'protected_sources':hashes,'status':'PASS_MOCKED_CONSUMERS','gameplay':'NOT TESTED'}))
