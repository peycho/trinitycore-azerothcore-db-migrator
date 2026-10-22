#!/usr/bin/env python3
"""Execute reviewed Cower callbacks and actual native aura lookup functions.

State/database/engine sinks are isolated. These checks prove callback scope,
not full pet gameplay or arbitrary aura-layout equivalence between cores.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from cleanup_pet_teaching import cower_sources

tc,ac=map(Path,sys.argv[1:]);cower_sources({'tc_source':tc,'ac_source':ac})

def function(source,signature):
    start=source.index(signature);opening=source.index('{',start);end=opening+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]

callbacks=[];methods=[]
for core,path,cls in (('Tc',tc,'spell_hun_pet_cower'),('Ac',ac,'spell_hun_cower')):
    source=(path/'src/server/scripts/Spells/spell_hunter.cpp').read_text()
    source=source[source.index('class '+cls+' :'):]
    callbacks.append('struct '+core+'Callback { '+core+'Unit* unit; SpellInfo const* info; '+core+'Unit* GetUnitOwner(){return unit;} SpellInfo const* GetSpellInfo(){return info;}\n'+function(source,'void CalculateAmount(')+'\n};')
    unit=(path/'src/server/game/Entities/Unit/Unit.cpp').read_text()
    signature='AuraEffect* Unit::GetAuraEffect(AuraType type, SpellFamilyNames name, uint32 iconId, uint8 effIndex) const'
    methods.append(function(unit,signature).replace('Unit::',core+'Unit::'))
    if core=='Tc':
        methods.append(function(unit,'AuraEffect* Unit::GetDummyAuraEffect(SpellFamilyNames name, uint32 iconId, uint8 effIndex) const').replace('Unit::','TcUnit::'))

mock=r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>
using uint8=uint8_t;using uint32=uint32_t;using int32=int32_t;
using AuraType=int;using SpellFamilyNames=uint32;
constexpr int SPELL_AURA_DUMMY=4,SPELLFAMILY_PET=17,SPELL_ICON_HUNTER_PET_IMPROVED_COWER=958,EFFECT_0=0;
struct Flags {uint32 value=0;bool operator!()const{return value==0;}};
struct SpellInfo {uint32 SpellIconID=958,SpellFamilyName=17;Flags SpellFamilyFlags;};
struct AuraEffect {SpellInfo info;uint8 index=0;int32 amount=-50;
 uint8 GetEffIndex()const{return index;}SpellInfo const*GetSpellInfo()const{return &info;}int32 GetAmount()const{return amount;}};
void AddPct(int32& value,int32 pct){value+=value*pct/100;}
struct BaseUnit {
 using AuraEffectList=std::vector<AuraEffect*>;AuraEffectList auras;
 AuraEffectList const& GetAuraEffectsByType(AuraType type)const{assert(type==4);return auras;}
};
struct TcUnit:BaseUnit{AuraEffect*GetAuraEffect(AuraType,SpellFamilyNames,uint32,uint8)const;AuraEffect*GetDummyAuraEffect(SpellFamilyNames,uint32,uint8)const;};
struct AcUnit:BaseUnit{AuraEffect*GetAuraEffect(AuraType,SpellFamilyNames,uint32,uint8)const;};
'''
main=r'''
int main(){
 SpellInfo child;child.SpellIconID=958;
 for(int32 base:{-50,-25,0})for(int32 modifier:{-100,-50,0,50,100}){
  AuraEffect effect;effect.amount=modifier;
  TcUnit tc;AcUnit ac;tc.auras={&effect};ac.auras={&effect};
  int32 left=base,right=base;bool tcRecalc=false,acRecalc=true;
  TcCallback{&tc,&child}.CalculateAmount(nullptr,left,tcRecalc);
  AcCallback{&ac,&child}.CalculateAmount(nullptr,right,acRecalc);
  assert(left==base+base*modifier/100&&right==left);
  assert(!tcRecalc&&acRecalc&&effect.amount==modifier);
  assert(tc.auras.size()==1&&ac.auras.size()==1);
 }
 for(int which=0;which<4;++which){
  AuraEffect effect;
  if(which==0)effect.index=1;
  if(which==1)effect.info.SpellFamilyName=9;
  if(which==2)effect.info.SpellIconID=1;
  TcUnit tc;AcUnit ac;
  if(which!=3){tc.auras={&effect};ac.auras={&effect};}
  int32 left=-50,right=-50;bool recalc=false;
  TcCallback{&tc,&child}.CalculateAmount(nullptr,left,recalc);
  AcCallback{&ac,&child}.CalculateAmount(nullptr,right,recalc);
  assert(left==-50&&right==-50);
 }
 // Keep the native lookup difference explicit: TC excludes family flags;
 // AC does not. Retirement neither changes aura data nor normalizes it.
 AuraEffect flagged;flagged.info.SpellFamilyFlags.value=1;
 TcUnit tc;AcUnit ac;tc.auras={&flagged};ac.auras={&flagged};
 int32 left=-50,right=-50;bool recalc=false;
 TcCallback{&tc,&child}.CalculateAmount(nullptr,left,recalc);
 AcCallback{&ac,&child}.CalculateAmount(nullptr,right,recalc);
 assert(left==-50&&right==-25&&flagged.amount==-50);
 std::cout<<"PASS protected Cower callbacks and aura getters: stock calculation, absent/wrong modifier controls, readonly state, explicit native family-flag difference; no ownership/skill/pet writes available; gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory()as d:
    p=Path(d);(p/'cower.cpp').write_text(mock+'\n'+'\n'.join(methods)+'\n'+'\n'.join(callbacks)+'\n'+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(p/'cower.cpp'),'-o',str(p/'cower')],check=True)
    subprocess.run([str(p/'cower')],check=True)
