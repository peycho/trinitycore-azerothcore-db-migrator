#!/usr/bin/env python3
"""Execute protected TC rank recursion and stored-row loading with mocked state.

This verifies native predecessor restoration, not complete Player::AddSpell,
spell effects or gameplay. AC exact passive restoration has its own harness.
"""
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
tc = Path(sys.argv[1])
path = 'src/server/game/Entities/Player/Player.cpp'
manifest = dict((name.strip().lstrip('*'), digest) for digest, name in (line.split(None,1)
    for line in (root/'compatibility/tc335-acwotlk-v2/trinitycore-semantic.sha256').read_text().splitlines()))
assert hashlib.sha256((tc/path).read_bytes()).hexdigest() == manifest[path]
source = (tc/path).read_text()


def body(marker):
    start = source.index('{',source.index(marker))
    end, depth = start+1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


start = source.index('else if (uint32 prev_spell = sSpellMgr->GetPrevSpellInChain(spellId))')
end = source.index('std::pair<PlayerSpellMap::iterator, bool> inserted',start)
recursion = source[start:end].strip().removeprefix('else ')
program = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <vector>
using uint32=uint32_t;
struct Manager {std::map<uint32,uint32> previous;uint32 GetPrevSpellInChain(uint32 id){return previous[id];}} manager;
Manager* sSpellMgr=&manager;
struct Field{uint32 value;uint32 GetUInt32()const{return value;}bool GetBool()const{return value!=0;}};
struct Rows{std::vector<std::array<Field,3>> data;size_t index=0;
 bool NextRow(){return ++index<data.size();}auto const& operator*()const{return data[index];}
 Rows*operator->(){return this;}explicit operator bool()const{return !data.empty();}};
using PreparedQueryResult=Rows;
struct Flags{bool active,disabled,dependent;};
struct Player {
 std::map<uint32,Flags> known;bool inWorld=false;
 bool IsInWorld()const{return inWorld;}
 void LearnSpell(uint32,bool,uint32){assert(false);}
 bool AddSpell(uint32 spellId,bool active,bool learning,bool dependent,bool disabled,bool loading=false,uint32 fromSkill=0){
  (void)learning;(void)loading;
  @RECURSION@
  known[spellId]={active,disabled,dependent};return !disabled;
 }
 void _LoadSpells(PreparedQueryResult result) @LOAD@
};
int main(){
 std::vector<std::vector<uint32>> chains={{16958,16961},{16952,16954},{52284,52285,52286},
  {51969,51983,51986},{50096,50108,50109,50110,50111},{61274,61275,61276,61277,61278}};
 for(auto const& chain:chains){
  manager.previous.clear();for(size_t i=1;i<chain.size();++i)manager.previous[chain[i]]=chain[i-1];
  // The reviewed repair retains exact enabled higher anchors. No child is
  // inferred by casting a selected learn-effect talent during source loading.
  for(bool active:{false,true}){
   Player player;Rows rows;rows.data.push_back({Field{chain.back()},Field{uint32(active)},Field{0}});
   player._LoadSpells(rows);
   assert(player.known.size()==chain.size());
   for(auto id:chain){assert(!player.known[id].disabled);assert(player.known[id].active==active);
    assert(player.known[id].dependent==(id!=chain.back()));}
   assert(!player.known.count(chain.back()+100000));
  }
  // Remaining explicit enabled anchors produce the same known prefix in
  // either order, including overlapping derivations.
  std::vector<uint32> anchors={chain.front(),chain.back()};
  do{Player player;Rows rows;for(auto id:anchors)rows.data.push_back({Field{id},Field{1},Field{0}});
   player._LoadSpells(rows);for(auto id:chain)assert(player.known.count(id)&&!player.known[id].disabled);
  }while(std::next_permutation(anchors.begin(),anchors.end()));
 }
 std::cout<<"PASS: protected TC _LoadSpells and predecessor recursion restore only known enabled anchors' lower ranks, including overlapping anchors and flags; state/catalogs mocked, gameplay NOT TESTED.\n";
}
'''
program = program.replace('@RECURSION@',recursion).replace('@LOAD@',body('void Player::_LoadSpells('))
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp)
    (path/'prefix.cpp').write_text(program)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(path/'prefix.cpp'),'-o',str(path/'prefix')],check=True)
    subprocess.run([str(path/'prefix')],check=True)
