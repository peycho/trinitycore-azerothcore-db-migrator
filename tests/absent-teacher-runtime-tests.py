#!/usr/bin/env python3
"""Protected TC stored-row loader and dependent-learn loop with recording sinks.

The harness proves invocation/absence boundaries, not a complete player login.
AC eligibility/load/delete behavior has its separate native consumer harness.
"""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from cleanup_eligibility import ABSENT_TEACHERS

tc = Path(sys.argv[1])
name = 'src/server/game/Entities/Player/Player.cpp'
manifest = dict((n.strip().lstrip('*'),h) for h,n in (line.split(None,1) for line in
                (ROOT/'compatibility/tc335-acwotlk-v2/trinitycore-semantic.sha256').read_text().splitlines()))
data = (tc/name).read_bytes()
assert hashlib.sha256(data).hexdigest() == manifest[name], 'Protected TC player source differs'
source = data.decode()
start = source.index('{',source.index('void Player::_LoadSpells('))
end,depth = start+1,1
while depth:
    depth += (source[end]=='{')-(source[end]=='}')
    end += 1
load = source[start:end]
start = source.index('// learn dependent spells',source.index('bool Player::AddSpell('))
end = source.index('if (!GetSession()->PlayerLoading())',start)
dependent = source[start:end]
start = source.index('// return false if spell disabled',source.index('bool Player::AddSpell('))
end = source.index('\n    }',start)
disabled_gate = source[start:end]
program = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <vector>
using uint32=uint32_t;
struct Node {uint32 Spell;bool Active=true,AutoLearned=false;};
using SpellLearnSpellMap=std::multimap<uint32,Node>;
using SpellLearnSpellMapBounds=std::pair<SpellLearnSpellMap::const_iterator,SpellLearnSpellMap::const_iterator>;
struct Manager {SpellLearnSpellMap links;
 SpellLearnSpellMapBounds GetSpellLearnSpellMapBounds(uint32 s)const{return links.equal_range(s);}
} manager;
Manager* sSpellMgr=&manager;
struct Field {uint32 value;uint32 GetUInt32()const{return value;}bool GetBool()const{return value!=0;}};
struct Rows {
 std::vector<std::array<Field,3>> data;size_t index=0;
 bool NextRow(){return ++index<data.size();}auto const&operator*()const{return data[index];}
 Rows*operator->(){return this;}explicit operator bool()const{return !data.empty();}
};
using PreparedQueryResult=Rows;
struct Player {
 std::set<uint32> known;std::vector<uint32> calls,effectCalls;
 bool IsInWorld()const{return false;}
 bool AddSpell(uint32 spellId,bool,bool,bool,bool disabled,bool loading=false){
  assert(loading||!disabled);calls.push_back(spellId);known.insert(spellId);
  struct {bool disabled;} newspell{disabled};
  @DISABLED_GATE@
  effectCalls.push_back(spellId);
  @DEPENDENT@
  return true;
 }
 void LearnSpell(uint32,bool){assert(false);}
 void _LoadSpells(PreparedQueryResult result) @LOAD@
};
int main(){
 @CASES@
 // Disabled ordinary history never reaches effects/dependent learning. The
 // enabled counterpart is preserved before and after exact retirement.
 for(uint32 id:{25312,32999,16811}){
  manager.links.clear();
  Player before;before._LoadSpells(Rows{{{{{id},{1},{1}}},{{{5195},{1},{0}}}}});
  assert((before.known==std::set<uint32>{id,5195}));
  assert(before.effectCalls==std::vector<uint32>{5195});
  Player after;after._LoadSpells(Rows{{{{{5195},{1},{0}}}}});
  assert(after.known==std::set<uint32>{5195});assert(after.effectCalls==before.effectCalls);
 }
 std::cout<<"Protected TC loader/dependent loop: 10 absent/present teacher pairs, empty input, disabled/auto gates and 3 disabled ordinary-history effect controls PASS; gameplay NOT TESTED\n";
}
'''
cases = []
for pairs in ABSENT_TEACHERS.values():
    for parent,child in pairs:
        cases.append('''{
 manager.links.clear();manager.links.emplace(@P@,Node{@C@,true,false});
 Player absent;absent._LoadSpells(Rows{{{{{@C@},{1},{0}}}}});
 assert(absent.known==std::set<uint32>{@C@});assert(absent.calls==std::vector<uint32>{@C@});
 Player removed;removed._LoadSpells(Rows{});assert(removed.known.empty());assert(removed.calls.empty());
 Player present;present._LoadSpells(Rows{{{{{@P@},{1},{0}}}}});
 assert((present.known==std::set<uint32>{@P@,@C@}));
 Player disabled;disabled._LoadSpells(Rows{{{{{@P@},{1},{1}}}}});
 assert(disabled.known==std::set<uint32>{@P@});
 manager.links.clear();manager.links.emplace(@P@,Node{@C@,true,true});
 Player automatic;automatic._LoadSpells(Rows{{{{{@P@},{1},{0}}}}});
 assert(automatic.known==std::set<uint32>{@P@});
}'''.replace('@P@',str(parent)).replace('@C@',str(child)))
program = program.replace('@DEPENDENT@',dependent).replace('@LOAD@',load).replace('@DISABLED_GATE@',disabled_gate).replace('@CASES@','\n'.join(cases))
with tempfile.TemporaryDirectory() as directory:
    cpp,binary=Path(directory)/'teachers.cpp',Path(directory)/'teachers'
    cpp.write_text(program)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
