#!/usr/bin/env python3
"""Protected TC alias factory and area-aura callbacks with recording state sinks."""
from pathlib import Path
import hashlib
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
tc = Path(sys.argv[1])
manifest = dict((name.strip().lstrip('*'),digest) for digest,name in (line.split(None,1)
    for line in (root/'compatibility/tc335-acwotlk-v2/trinitycore-semantic.sha256').read_text().splitlines()))
files = ['src/server/scripts/Spells/spell_paladin.cpp','src/server/game/Scripting/ScriptMgr.h']
for name in files:
    assert hashlib.sha256((tc/name).read_bytes()).hexdigest() == manifest[name]
source, header = [(tc/name).read_text() for name in files]


def method(text,marker):
    start = text.index(marker)
    body = text.index('{',start)
    end, depth = body+1,1
    while depth:
        depth += (text[end]=='{')-(text[end]=='}')
        end += 1
    return text[start:end]


body = source[source.index('class spell_pal_improved_aura '):]
constructor = method(body,'spell_pal_improved_aura(uint32')
validate = method(body,'bool Validate(')
apply = method(body,'void HandleEffectApply(')
remove = method(body,'void HandleEffectRemove(')
factory = method(header[header.index('class GenericSpellAndAuraScriptLoader '):], 'AuraScript* GetAuraScript() const override')
macro = next(line for line in header.splitlines() if line.startswith('#define RegisterSpellScriptWithArgs('))
aliases = ['spell_pal_improved_concentraction_aura','spell_pal_improved_devotion_aura',
           'spell_pal_sanctified_retribution','spell_pal_swift_retribution']
registrations = [re.search(r'RegisterSpellScriptWithArgs\(spell_pal_improved_aura, "'+name+r'", \w+\);',source)[0][:-1]
                 for name in aliases]
constants = ['SPELL_PALADIN_IMPROVED_CONCENTRACTION_AURA','SPELL_PALADIN_IMPROVED_DEVOTION_AURA',
             'SPELL_PALADIN_SANCTIFIED_RETRIBUTION_AURA','SPELL_PALADIN_SANCTIFIED_RETRIBUTION_R1','SPELL_PALADIN_SWIFT_RETRIBUTION_R1']
declarations = '\n'.join('constexpr uint32 '+name+'='+re.search(r'\b'+name+r'\s*=\s*(\d+)',source)[1]+';' for name in constants)
program = r'''
#include <cassert>
#include <cstdint>
#include <initializer_list>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <tuple>
#include <type_traits>
#include <utility>
#include <vector>
#include <iostream>
using uint32=uint32_t;using AuraEffectHandleModes=int;
@CONSTANTS@
struct AuraEffect{};
struct SpellInfo{uint32 Id=0;SpellInfo const*GetFirstRankSpell()const{return this;}};
struct Unit{
 std::set<uint32> auras,known{6603};std::map<uint32,uint32> skills{{171,375}};
 std::vector<uint32> casts,removed;
 bool GetAuraOfRankedSpell(uint32 id)const{return auras.count(id);}
 void RemoveOwnedAura(uint32 id,uint32 caster){assert(caster==17);removed.push_back(id);}
 void CastSpell(Unit*target,uint32 id,bool triggered){assert(target==this&&triggered);casts.push_back(id);}
};
struct AuraScript{
 virtual~AuraScript()=default;virtual bool Validate(SpellInfo const*){return true;}
 Unit target;SpellInfo info;
 Unit*GetTarget(){return &target;}uint32 GetCasterGUID(){return 17;}
 SpellInfo const*GetSpellInfo()const{return &info;}
 bool ValidateSpellInfo(std::initializer_list<uint32> ids){return ids.size()==3;}
};
class spell_pal_improved_aura:public AuraScript{
 uint32 _spellId;
public:
 @CONSTRUCTOR@
 @VALIDATE@
 @APPLY@
 @REMOVE@
};
namespace Trinity{
 struct find_type_end{};
 template<class T,class Tuple>T*new_from_tuple(Tuple const&t){return std::apply([](auto...args){return new T(args...);},t);}
}
struct SpellScriptLoader{
 std::string name;explicit SpellScriptLoader(char const*n):name(n){}
 virtual~SpellScriptLoader()=default;virtual AuraScript*GetAuraScript()const=0;
};
template<class Type,class Tuple>class GenericSpellAndAuraScriptLoader:public SpellScriptLoader{
 using AuraScriptType=Type;using ArgsType=Tuple;ArgsType _args;
public:
 GenericSpellAndAuraScriptLoader(char const*name,ArgsType&&args):SpellScriptLoader(name),_args(std::move(args)){}
 @FACTORY@
};
@MACRO@
int main(){
 std::vector<SpellScriptLoader*> loaders={@REGISTRATIONS@};
 std::vector<uint32> helpers={63510,63514,63531,63531};
 for(size_t i=0;i<loaders.size();++i){
  std::unique_ptr<SpellScriptLoader>loader(loaders[i]);
  std::unique_ptr<AuraScript>base(loader->GetAuraScript());
  auto&script=dynamic_cast<spell_pal_improved_aura&>(*base);
  assert(script.Validate(nullptr));auto known=script.target.known;auto skills=script.target.skills;
  script.HandleEffectApply(nullptr,0);
  assert(script.target.casts==std::vector<uint32>{helpers[i]});
  assert(script.target.removed==std::vector<uint32>{helpers[i]});
  script.target.removed.clear();script.HandleEffectRemove(nullptr,0);
  assert(script.target.removed==std::vector<uint32>{helpers[i]});
  for(auto pair:std::vector<std::pair<uint32,uint32>>{{31869,53379},{53379,31869}}){
   script.info.Id=pair.first;script.target.auras={pair.second};script.target.removed.clear();
   script.HandleEffectRemove(nullptr,0);assert(script.target.removed.empty());
  }
  assert(script.target.known==known&&script.target.skills==skills);
 }
 std::cout<<"PASS: protected literal alias registrations and native factory forward exact constructor helpers; aura apply/remove and shared-aura retention callbacks use recording sinks, with no spellbook/skill changes. Full gameplay NOT TESTED.\n";
}
'''
for key,value in {'CONSTANTS':declarations,'CONSTRUCTOR':constructor,'VALIDATE':validate,'APPLY':apply,
                  'REMOVE':remove,'FACTORY':factory,'MACRO':macro,'REGISTRATIONS':',\n'.join(registrations)}.items():
    program = program.replace('@'+key+'@',value)
with tempfile.TemporaryDirectory() as temp:
    p = Path(temp)
    (p/'aliases.cpp').write_text(program)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(p/'aliases.cpp'),'-o',str(p/'aliases')],check=True)
    subprocess.run([str(p/'aliases')],check=True)
