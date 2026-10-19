#!/usr/bin/env python3
"""Protected spec-switch/count effects with recording state sinks.

Loading tests separately prove that neither effect is executed by normalization.
This verifies button semantics and a purchase-effect negative control, not a
worldserver's gossip, costs, action bars or full spec-switch scheduling.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def body(source, signature):
    start=source.index('{',source.index(signature))
    end,depth=start+1,1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}')
        end+=1
    return source[start:end]


methods=[]
for directory,prefix in zip(map(Path,sys.argv[1:]),('Tc','Ac')):
    source=(directory/'src/server/game/Spells/SpellEffects.cpp').read_text()
    assert re.search(r'&Spell::EffectSpecCount,\s*//161\b',source)
    assert re.search(r'&Spell::EffectActivateSpec,\s*//162\b',source)
    for suffix in ('ActivateSpec','SpecCount'):
        methods.append('void '+prefix+suffix+'()'+body(source,'void Spell::Effect'+suffix+'('))

mock=r'''
#include <cassert>
#include <cstdint>
#include <iostream>
using uint32=uint32_t;
constexpr int SPELL_EFFECT_HANDLE_HIT_TARGET=1,TYPEID_PLAYER=1;
struct Player {
 bool player=true;uint32 groups=2,active=0,activations=0,purchases=0;
 uint32 GetTypeId()const{return player?TYPEID_PLAYER:0;}
 Player*ToPlayer(){return player?this:nullptr;}
 void ActivateTalentGroup(uint32 spec){assert(spec<groups);active=spec;++activations;}
 void ActivateSpec(uint32 spec){ActivateTalentGroup(spec);}
 void UpdateTalentGroupCount(uint32 count){groups=count;++purchases;}
 void UpdateSpecCount(uint32 count){UpdateTalentGroupCount(count);}
};
struct Spell {
 int effectHandleMode=SPELL_EFFECT_HANDLE_HIT_TARGET;Player*unitTarget=nullptr;uint32 damage=1;
'''+''.join(methods)+r'''
};
int main(){
 for(uint32 spec:{0,1}){
  Player tc,ac;Spell left,right;left.unitTarget=&tc;right.unitTarget=&ac;
  left.damage=right.damage=spec+1;left.TcActivateSpec();right.AcActivateSpec();
  assert(tc.active==spec&&ac.active==spec&&tc.groups==2&&ac.groups==2);
  assert(tc.activations==1&&ac.activations==1&&tc.purchases==0&&ac.purchases==0);
 }
 Player tc,ac;tc.groups=ac.groups=1;Spell left,right;
 left.unitTarget=&tc;right.unitTarget=&ac;left.damage=right.damage=2;
 left.TcSpecCount();right.AcSpecCount();assert(tc.groups==2&&ac.groups==2);
 assert(tc.purchases==1&&ac.purchases==1); // why migration never casts 63624
 Player other;other.player=false;Spell ignored;ignored.unitTarget=&other;
 ignored.TcActivateSpec();ignored.AcActivateSpec();ignored.TcSpecCount();ignored.AcSpecCount();
 assert(other.activations==0&&other.purchases==0);
 ignored.unitTarget=nullptr;ignored.TcActivateSpec();ignored.AcActivateSpec();
 ignored.unitTarget=&tc;ignored.effectHandleMode=0;ignored.TcActivateSpec();ignored.TcSpecCount();
 assert(tc.activations==0&&tc.purchases==1);
 std::cout<<"Protected TC/AC dual-spec switch/count effects PASS: both button targets, no count changes on switch, purchase negative control and invalid-target/mode controls; sinks mocked, gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp,binary=Path(directory)/'dual-spec.cpp',Path(directory)/'dual-spec'
    cpp.write_text(mock)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
