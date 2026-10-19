#!/usr/bin/env python3
"""Execute protected aura handlers with recording sinks, without a worldserver."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def body(source, signature):
    start = source.index('{', source.index(signature))
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


cores = list(map(Path, sys.argv[1:]))
tc_player=(cores[0]/'src/server/game/Entities/Player/Player.cpp').read_text()
start=tc_player.index('// non talent spell: learn low ranks (recursive call)',tc_player.index('bool Player::AddSpell('))
rank=tc_player[start:tc_player.index('std::pair<PlayerSpellMap::iterator, bool> inserted',start)]
rank=rank.replace('else if (uint32 prev_spell','if (uint32 prev_spell')
start=tc_player.index('// learn dependent spells',start)
dependency=tc_player[start:tc_player.index('if (!GetSession()->PlayerLoading())',start)]
shape=(cores[0]/'src/server/game/Spells/Auras/SpellAuraEffects.cpp').read_text()
shape=shape[shape.index('void AuraEffect::HandleShapeshiftBoosts('):]
stance=shape[shape.index('PlayerSpellMap const& sp_list'):shape.index('// Also do it for Glyphs')]
handlers = []
for directory in cores:
    source = (directory / 'src/server/scripts/Spells/spell_druid.cpp').read_text()
    for name, value in [('R1', 47179), ('R2', 47180)]:
        assert re.search(rf'SPELL_DRUID_NURTURING_INSTINCT_{name}\s*=\s*{value}', source)
    source = source[source.index('class spell_dru_nurturing_instinct '):]
    handlers.append([body(source, 'void AfterApply('), body(source, 'void AfterRemove(')])
mock = r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>
#include <map>
#include <set>
using uint64=uint64_t;
#define UI64LIT(x) x##ULL
constexpr int PLAYERSPELL_UNCHANGED=0,PLAYERSPELL_REMOVED=1;
enum SpellAttr0{SPELL_ATTR0_PASSIVE=64,SPELL_ATTR0_HIDDEN_CLIENTSIDE=128};
using uint32=uint32_t;
constexpr uint32 SPELL_DRUID_NURTURING_INSTINCT_R1=47179,SPELL_DRUID_NURTURING_INSTINCT_R2=47180,SPEC_MASK_ALL=3;
struct AuraEffect {};
struct SpellInfo { uint32 rank=1,Id=0,Stances=1,flags=400;
 uint32 GetRank() const{return rank;}bool HasAttribute(SpellAttr0 v)const{return flags&v;}
 bool IsPassive()const{return flags&64;}
};
struct Player {
    bool isPlayer=true;
    std::vector<uint32> casts,removed,temporary;
    Player* ToPlayer() { return isPlayer?this:nullptr; }
    void CastSpell(Player* target,uint32 id,AuraEffect const*) { assert(target==this); casts.push_back(id); }
    void RemoveAurasDueToSpell(uint32 id) { removed.push_back(id); }
    void addSpell(uint32 id,uint32 mask,bool update,bool temp) { assert(mask==3 && !update && temp); temporary.push_back(id); }
    void removeSpell(uint32 id,uint32 mask,bool onlyTemporary) { assert(mask==3 && onlyTemporary); removed.push_back(id); temporary.clear(); }
};
using Unit=Player;
struct Handler {
    Player target; SpellInfo info;
    Player* GetTarget() { return &target; }
    SpellInfo const* GetSpellInfo() const { return &info; }
'''
for prefix, methods in zip(('Tc', 'Ac'), handlers):
    for suffix, method in zip(('Apply', 'Remove'), methods):
        # TC uses aurEff, AC intentionally ignores it; omit the name in AC.
        arg = 'aurEff' if prefix == 'Tc' and suffix == 'Apply' else ''
        mock += f'void {prefix}{suffix}(AuraEffect const* {arg}) {method}\n'
mock += r'''
};
struct SpellLearnSpellNode{uint32 Spell=0;bool Active=false,AutoLearned=false;};
using SpellLearnSpellMap=std::multimap<uint32,SpellLearnSpellNode>;
using SpellLearnSpellMapBounds=std::pair<SpellLearnSpellMap::const_iterator,SpellLearnSpellMap::const_iterator>;
struct Manager{
 SpellLearnSpellMap rows;std::map<uint32,SpellInfo>infos;
 uint32 GetPrevSpellInChain(uint32 s)const{return s==47180?47179:0;}
 SpellLearnSpellMapBounds GetSpellLearnSpellMapBounds(uint32 s)const{return rows.equal_range(s);}
 SpellInfo const*GetSpellInfo(uint32 s)const{return &infos.at(s);}
} manager;Manager*sSpellMgr=&manager;
struct TcSpell{int state=0;bool disabled=false,active=false;};
using PlayerSpellMap=std::map<uint32,TcSpell>;
struct TcPlayer{
 PlayerSpellMap spells;std::vector<uint32>casts;
 bool IsInWorld()const{return false;}PlayerSpellMap const&GetSpellMap()const{return spells;}
 void LearnSpell(uint32,bool,uint32=0){assert(false);}
 void AddSpell(uint32 spellId,bool active,bool learning,bool dependent,bool disabled,bool=false,uint32 fromSkill=0){
  assert(!active&&learning&&dependent&&!disabled);
'''+rank+r'''
  spells[spellId]={PLAYERSPELL_UNCHANGED,disabled,active};
 }
 void Restore(uint32 spellId){
'''+dependency+r'''
 }
 void CastSpell(TcPlayer*,uint32 id,void const*){casts.push_back(id);}
};
struct Shape{
 uint32 form=1;uint32 GetMiscValue()const{return form;}
 void Apply(TcPlayer*plrTarget){TcPlayer*target=plrTarget;uint32 spellId=0,spellId2=0;
'''+stance+r'''
 }
};
int main() {
    manager.rows.emplace(33872,SpellLearnSpellNode{47179,false,false});
    manager.rows.emplace(33873,SpellLearnSpellNode{47180,false,false});
    manager.infos[47179]=SpellInfo{1,47179};manager.infos[47180]=SpellInfo{2,47180};
    for(uint32 parent:{33872,33873}){
        TcPlayer p;p.Restore(parent);
        assert(p.spells.size()==(parent==33872?1:2));
        for(auto const&entry:p.spells)assert(!entry.second.active&&!entry.second.disabled);
        for(uint32 form:{0,1,5,8}){
            p.casts.clear();if(form)Shape{form}.Apply(&p);
            assert(p.casts.size()==(form==1?p.spells.size():0));
            if(form==1)assert(p.casts.back()==(parent==33872?47179:47180));
        }
    }
    for (uint32 rank:{1,2}) {
        uint32 child=rank==1?47179:47180;
        Handler h; h.info.rank=rank;
        h.TcApply(nullptr); assert(h.target.casts==std::vector<uint32>{child});
        assert(h.target.temporary.empty());
        h.TcRemove(nullptr); assert(h.target.removed==std::vector<uint32>{child});
        h.target.removed.clear();
        h.AcApply(nullptr); assert(h.target.temporary==std::vector<uint32>{child});
        h.AcRemove(nullptr); assert(h.target.temporary.empty());
        assert(h.target.removed==std::vector<uint32>{child});
        Handler nonplayer; nonplayer.target.isPlayer=false;
        nonplayer.AcApply(nullptr); nonplayer.AcRemove(nullptr);
        assert(nonplayer.target.temporary.empty() && nonplayer.target.removed.empty());
    }
    std::cout << "Protected Nurturing Instinct handlers: TC world restoration/prefix/stance, exact rank helpers, TC aura casts/removal, AC temporary add/removal and nonplayer controls passed; sinks mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'nurturing.cpp'
    binary = Path(directory) / 'nurturing'
    cpp.write_text(mock)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
