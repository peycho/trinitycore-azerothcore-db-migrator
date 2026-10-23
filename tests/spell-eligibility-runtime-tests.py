#!/usr/bin/env python3
"""Protected AC eligibility lookup and stored-row deletion, with DB/state sinks mocked.

An optional private review JSON exercises captured metadata without embedding
player evidence in this repository. This is not full worldserver gameplay.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    end, depth = opening + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


root = Path(__file__).resolve().parents[1]
ac = Path(sys.argv[1])
manifest = dict((name.strip().lstrip('*'), checksum) for checksum, name in
                (line.split(None, 1) for line in
                 (root/'compatibility/tc335-acwotlk-v2/azerothcore-semantic.sha256').read_text().splitlines()))
sources = []
for path, signature in (
        ('src/server/game/DataStores/DBCStores.cpp', 'SkillRaceClassInfoEntry const* GetSkillRaceClassInfo('),
        ('src/server/game/Entities/Player/Player.cpp', 'bool Player::CheckSkillLearnedBySpell('),
        ('src/server/game/Entities/Player/PlayerStorage.cpp', 'void Player::_LoadSpells(')):
    data = (ac/path).read_bytes()
    assert hashlib.sha256(data).hexdigest() == manifest[path], 'Protected AC consumer differs: '+path
    sources.append(function(data.decode(), signature))

mock = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <memory>
#include <utility>
#include <vector>
using uint8=uint8_t; using uint32=uint32_t; using uint64=uint64_t;
constexpr int CONFIG_VALIDATE_SKILL_LEARNED_BY_SPELLS=1,SPEC_MASK_ALL=3,CHAR_DEL_CHAR_SPELL_BY_SPELL=2;
#define LOG_ERROR(...) do {} while(false)
struct SkillLineEntry {uint32 id;};
struct SkillRaceClassInfoEntry {uint32 SkillID,RaceMask,ClassMask;};
struct SkillLineAbilityEntry {uint32 SkillLine,ClassMask=0;};
using SkillRaceClassInfoMap=std::multimap<uint32,SkillRaceClassInfoEntry const*>;
using SkillRaceClassInfoBounds=std::pair<SkillRaceClassInfoMap::iterator,SkillRaceClassInfoMap::iterator>;
SkillRaceClassInfoMap SkillRaceClassInfoBySkill;
using SkillLineAbilityMap=std::multimap<uint32,SkillLineAbilityEntry const*>;
using SkillLineAbilityMapBounds=std::pair<SkillLineAbilityMap::iterator,SkillLineAbilityMap::iterator>;
struct Store {
 std::map<uint32,SkillLineEntry> rows;
 SkillLineEntry const* LookupEntry(uint32 s)const {auto i=rows.find(s);return i==rows.end()?nullptr:&i->second;}
} sSkillLineStore;
struct Manager {SkillLineAbilityMap rows;auto GetSkillLineAbilityMapBounds(uint32 s){return rows.equal_range(s);}} mgr;
Manager* sSpellMgr=&mgr;
struct World {bool validate=true;bool getBoolConfig(int)const{return validate;}} world;
World* sWorld=&world;
struct Guid {uint64 id;uint32 GetCounter()const{return uint32(id);}uint64 GetRawValue()const{return id;}};
struct Statement {uint64 guid=0,spell=0;void SetData(int index,uint64 value){if(index)spell=value;else guid=value;}};
struct Database {
 Statement statement;std::vector<std::pair<uint64,uint32>> deleted;
 Statement* GetPreparedStatement(int){statement={};return &statement;}
 void Execute(Statement* s){deleted.emplace_back(s->guid,uint32(s->spell));}
} CharacterDatabase;
using CharacterDatabasePreparedStatement=Statement;
struct Field {uint32 value;template<class T>T Get()const{return T(value);}};
struct Result {
 std::vector<std::array<Field,2>> rows;size_t current=0;
 Field* Fetch(){return rows[current].data();}bool NextRow(){return ++current<rows.size();}
};
using PreparedQueryResult=std::shared_ptr<Result>;
struct Player {
 uint64 guid;uint8 race,cls;std::map<uint32,uint8> spells;std::vector<uint32> removals;
 uint8 getRace()const{return race;}uint8 getClass()const{return cls;}Guid GetGUID()const{return {guid};}
 bool CheckSkillLearnedBySpell(uint32);void _LoadSpells(PreparedQueryResult);
 void addSpell(uint32 s,uint8 mask,bool){spells[s]=mask;}
 void removeSpell(uint32 s,int,bool){removals.push_back(s);spells.erase(s);}
};
'''
main = [r'''
void check(uint64 guid,uint8 race,uint8 cls,uint32 spell,std::vector<uint32> skills,
           std::vector<std::pair<uint32,uint32>> abilities,
           std::vector<SkillRaceClassInfoEntry> infos,bool expected) {
 sSkillLineStore.rows.clear();mgr.rows.clear();SkillRaceClassInfoBySkill.clear();CharacterDatabase.deleted.clear();
 std::vector<SkillLineAbilityEntry> abilityRows;abilityRows.reserve(abilities.size());
 for(auto s:skills)sSkillLineStore.rows[s]={s};
 for(auto a:abilities){abilityRows.push_back({a.first,a.second});mgr.rows.emplace(spell,&abilityRows.back());}
 for(auto const&i:infos)SkillRaceClassInfoBySkill.emplace(i.SkillID,&i);
 Player p{guid,race,cls,{},{}},other{guid+1,race,cls,{{spell,3}},{}};
 assert(p.CheckSkillLearnedBySpell(spell)==expected);
 auto result=std::make_shared<Result>();result->rows={{{{spell},{2}}}};
 p._LoadSpells(result);
 assert(other.spells.count(spell)==1); // The deletion is scoped to this character.
 if(expected){assert(p.spells.at(spell)==2);assert(CharacterDatabase.deleted.empty());assert(p.removals.empty());}
 else {assert(p.spells.empty());assert(p.removals==std::vector<uint32>{spell});
       assert(CharacterDatabase.deleted.size()==1);
       assert(CharacterDatabase.deleted[0]==std::make_pair(guid,spell));}
}
int main(){
 check(1,1,8,2567,{176},{{176,0}},{{176,0,8}},false); // Thrown: mage fails rogue-only metadata.
 check(2,1,4,2567,{176},{{176,0}},{{176,0,8}},true);
 check(3,1,2,10140,{237},{{237,128}},{{237,0,128}},false);
 check(4,1,8,10140,{237},{{237,128}},{{237,0,128}},true);
 check(5,1,1,900001,{1},{{1,0}},{{1,16,0}},false); // Race mask matters independently.
 check(6,5,1,900001,{1},{{1,0}},{{1,16,0}},true);
 check(7,1,1,900001,{1},{{1,128}},{{1,0,0}},true); // Ability ClassMask is not this consumer's test.
 check(8,1,1,900001,{},{{1,0}},{},true); // Missing SkillLine is ignored by native code.
 check(9,1,1,900001,{1},{},{},true); // No ability associations are accepted.
 check(10,1,1,900001,{1},{{1,0}},{},false); // Existing skill with no eligible info fails.
 check(11,1,1,900001,{1,2},{{1,0},{2,0}},{{1,0,8},{2,0,1}},true); // Any eligible skill suffices.
 check(12,1,1,900001,{1},{{1,0}},{{1,0,8},{1,0,1}},true); // Alternative info row.
 world.validate=false;
 check(13,1,8,2567,{176},{{176,0}},{{176,0,8}},true); // Config control only; never a workaround.
 world.validate=true;
''']
# Fixed reviewed racial masks also run through the protected native reader.
rules = json.loads((root/'lib/cleanup_racial_catalog.json').read_text())
for spell, valid_race in ((20597,1),(59224,3),(28875,11),(59539,11)):
    entry=rules['ac'][str(spell)];skill=rules['spells'][str(spell)]
    infos=rules['skill_metadata']['ac'][str(skill)]['infos']
    for race, expected in ((10,False),(valid_race,True)):
        literal=lambda values:'{'+','.join(map(str,values))+'}'
        main.append('check('+','.join(('100',str(race),'6',str(spell),literal([skill]),
            '{'+','.join(literal((a[1],a[4]))for a in entry['abilities'])+'}',
            '{'+','.join(literal(r[1:4])for r in infos)+'}',str(expected).lower()))+');')
cases = []
if len(sys.argv) > 2:
    private = Path(sys.argv[2])
    assert private.stat().st_size <= 128*1024*1024, 'Private review exceeds its input bound'
    cases = json.loads(private.read_text())
    assert isinstance(cases,list) and len(cases) <= 40000
    def numeric(values, size):
        return (isinstance(values,list) and len(values) == size
                and all(type(v) is int and 0 <= v <= 0xffffffff for v in values))
    for row in cases:
        target = row['target']
        abilities = target['abilities']
        assert type(row['guid']) is int and 1 <= row['guid'] <= 0xffffffff
        assert type(row['spell']) is int and 1 <= row['spell'] <= 0xffffffff
        assert numeric(row['character'],8)
        assert row['character'][1] in (1,2,3,4,5,6,7,8,10,11)
        assert row['character'][2] in (1,2,3,4,5,6,7,8,9,11)
        assert isinstance(abilities,list) and len(abilities) <= 1000 and all(numeric(a,14) for a in abilities)
        assert isinstance(target['skill_info'],list) and len(target['skill_info']) <= 10000
        assert all(numeric(r,8) for r in target['skill_info']) and target['passes'] is False
        skills = sorted({a[1] for a in abilities})
        info = target['skill_info']
        literal = lambda values: '{'+','.join(map(str, values))+'}'
        main.append('check('+','.join((str(row['guid']), str(row['character'][1]), str(row['character'][2]),
            str(row['spell']), literal(skills),
            '{'+','.join(literal((a[1], a[4])) for a in abilities)+'}',
            '{'+','.join(literal(r[1:4]) for r in info)+'}', 'false'))+');')
main.append('std::cout<<"Protected AC spell eligibility/load/delete: 13 synthetic controls, 8 fixed racial controls and '+str(len(cases))+' captured cases PASS; gameplay NOT TESTED\\n";}')
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory)/'eligibility.cpp', Path(directory)/'eligibility'
    cpp.write_text(mock+'\n'+'\n'.join(sources)+'\n'+'\n'.join(main))
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
