#!/usr/bin/env python3
"""TC load-time talent-cast gate versus AC native exact-child restoration.

Only the protected load/cast consumers are compiled; spell effects, catalogs
and state are recording sinks. This is not full worldserver gameplay.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

tc, ac = map(Path, sys.argv[1:])
t = (tc/'src/server/game/Entities/Player/Player.cpp').read_text()
a = (ac/'src/server/game/Entities/Player/Player.cpp').read_text()


def body(source, marker):
    start = source.index('{', source.index(marker))
    end, depth = start+1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


start = t.index('// cast talents with SPELL_EFFECT_LEARN_SPELL')
end = t.index('// update used talent points count', start)
cast_gate = t[start:end]
load = body(t, 'void Player::_LoadSpells(')
native = body(a, 'void Player::_addTalentAurasAndSpells(')
program = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <map>
#include <set>
#include <vector>
#include <iostream>
using uint8=uint8_t;using uint32=uint32_t;
constexpr uint32 SPELL_EFFECT_LEARN_SPELL=36,SPELL_EFFECT_SKILL_STEP=44;
constexpr uint32 SPELL_ATTR0_CU_IS_TALENT=1,SPELL_ATTR0_DO_NOT_DISPLAY=128;
constexpr uint8 MAX_SPELL_EFFECTS=3,SPEC_MASK_ALL=3;
struct Effect {uint32 Effect=0,TriggerSpell=0;};
struct SpellInfo {
 std::array<Effect,3> Effects{};bool passive=false;uint32 Stances=0;
 bool HasEffect(uint32 e)const{for(auto const&r:Effects)if(r.Effect==e)return true;return false;}
 bool HasAttribute(uint32 e)const{return e==SPELL_ATTR0_CU_IS_TALENT;}
 bool IsPassive()const{return passive;}
};
struct Manager{
 std::map<uint32,SpellInfo> spells;
 SpellInfo const* GetSpellInfo(uint32 id){return &spells.at(id);}
 bool IsAdditionalTalentSpell(uint32)const{return false;}
}manager;
Manager* sSpellMgr=&manager;
struct Field{uint32 value;uint32 GetUInt32()const{return value;}bool GetBool()const{return value!=0;}};
struct Rows{
 std::vector<std::array<Field,3>> data;size_t index=0;
 bool NextRow(){return ++index<data.size();}auto const&operator*()const{return data[index];}
 Rows*operator->(){return this;}explicit operator bool()const{return !data.empty();}
};
using PreparedQueryResult=Rows;
struct Player{
 std::set<uint32> known;std::vector<uint32> cast,added;
 bool AddSpell(uint32 spellId,bool,bool,bool,bool disabled,bool loading=false){
  known.insert(spellId);if(disabled)return false;
  auto spellInfo=sSpellMgr->GetSpellInfo(spellId);
  @CAST_GATE@
  return true;
 }
 void _LoadSpells(PreparedQueryResult result) @LOAD@
 void _addTalentAurasAndSpells(uint32 spellId) @NATIVE@
 bool HandlePassiveSpellLearn(SpellInfo const*)const{return true;}
 bool IsNeedCastPassiveSpellAtLearn(SpellInfo const*)const{return true;}
 void CastSpell(Player*,uint32 id,bool triggered){assert(triggered);cast.push_back(id);}
 void _addSpell(uint32 id,uint8 mask,bool temporary){assert(mask==3&&temporary);added.push_back(id);}
};
int main(){
 for(auto pair:std::vector<std::pair<uint32,uint32>>{{37116,16952},{49189,52284},{49146,51969},{61154,50096},{64357,44441}}){
  auto parent=pair.first,child=pair.second;
  manager.spells[parent].Effects[0]={36,child};
  Player load;Rows rows;rows.data.push_back({Field{parent},Field{1},Field{0}});load._LoadSpells(rows);
  assert(load.known.count(parent)&&load.cast.empty()&&load.added.empty());
  assert(!load.known.count(child)); // retained parent alone is NOT a source restore proof
  Player retained;retained.known.insert(child);retained._LoadSpells(rows);
  assert(retained.known.count(child)&&retained.cast.empty());
  Player activation;activation.AddSpell(parent,true,true,false,false,false);
  assert(activation.cast==std::vector<uint32>{parent});
  Player target;target._addTalentAurasAndSpells(parent);
  assert(target.added==std::vector<uint32>{child});
 }
 std::cout<<"PASS: protected TC _LoadSpells uses loading=true and does not recast non-passive learn-effect talents; retained child anchors are necessary.\n";
 std::cout<<"PASS: protected normal TC talent cast gate and AC exact temporary-child consumer; catalogs/effects/state sinks mocked, gameplay NOT TESTED.\n";
}
'''
program = program.replace('@CAST_GATE@', cast_gate).replace('@LOAD@', load).replace('@NATIVE@', native)
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory)
    (p/'ownership.cpp').write_text(program)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(p/'ownership.cpp'),'-o',str(p/'ownership')],check=True)
    subprocess.run([str(p/'ownership')],check=True)
