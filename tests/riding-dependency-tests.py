#!/usr/bin/env python3
"""Run protected load-time dependency/skill bodies with mocked state sinks."""
from pathlib import Path
import subprocess
import sys
import tempfile


def body(source, marker):
    start = source.index('{', source.index(marker))
    end, depth = start + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


tc, ac = map(Path, sys.argv[1:])
tc_source = (tc/'src/server/game/Entities/Player/Player.cpp').read_text()
ac_source = (ac/'src/server/game/Entities/Player/Player.cpp').read_text()
start = tc_source.index('// learn dependent spells',tc_source.index('bool Player::AddSpell('))
end = tc_source.index('if (!GetSession()->PlayerLoading())',start)
dependency = tc_source[start:end]
tc_skill = body(tc_source,'if (SpellLearnSkillNode const* spellLearnSkill = sSpellMgr->GetSpellLearnSkill(spellId))')
ac_skill = body(ac_source[ac_source.index('bool Player::_addSpell('):],'if (spellLearnSkill)')
tc_effect = body((tc/'src/server/game/Spells/SpellEffects.cpp').read_text(),'void Spell::EffectSkill(')
ac_effect = body((ac/'src/server/game/Spells/SpellEffects.cpp').read_text(),'void Spell::EffectSkill(')
mock = r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <utility>
#include <vector>
using uint16=uint16_t;using uint32=uint32_t;
constexpr int CONFIG_ALWAYS_MAXSKILL=0;
#define TC_LOG_DEBUG(...) ((void)0)
#define LOG_DEBUG(...) ((void)0)
constexpr int SPELL_EFFECT_HANDLE_HIT=0;
struct Spell { int effectHandleMode=0;void TcEffect();void AcEffect(); };
struct World { bool getBoolConfig(int) const { return true; } };
World world;World* sWorld=&world;
struct SpellLearnSkillNode { uint32 skill=762,step=3,value=225,maxvalue=225; };
struct SpellLearnSpellNode { uint32 Spell=34090;bool Active=true,AutoLearned=false; };
using SpellLearnSpellMap=std::multimap<uint32,SpellLearnSpellNode>;
using SpellLearnSpellMapBounds=std::pair<SpellLearnSpellMap::const_iterator,SpellLearnSpellMap::const_iterator>;
struct SpellMgr {
    SpellLearnSpellMap rows;
    SpellLearnSpellMapBounds GetSpellLearnSpellMapBounds(uint32 id) const { return rows.equal_range(id); }
};
SpellMgr manager;SpellMgr* sSpellMgr=&manager;
struct Player {
    uint32 value=225,cap=225,step=3,slots=2;
    std::vector<uint32> added;
    bool IsInWorld() const { return false; }
    bool IsProfessionOrRidingSkill(uint32 id) const { return id==762; }
    uint32 GetMaxSkillValueForLevel() const { return 400; }
    uint32 GetPureSkillValue(uint32 id) const { assert(id==762);return value; }
    uint32 GetPureMaxSkillValue(uint32 id) const { assert(id==762);return cap; }
    void SetSkill(uint32 id,uint32 tier,uint32 v,uint32 c) { assert(id==762);step=tier;value=v;cap=c; }
    void AddSpell(uint32 id,bool active,bool learning,bool dependent,bool disabled) {
        assert(active && learning && dependent && !disabled);added.push_back(id);
    }
    void LearnSpell(uint32,bool) { assert(false); }
    void Restore(uint32 spellId);
    void TcSkill(SpellLearnSkillNode const*,uint32);
    void AcSkill(SpellLearnSkillNode const*);
};
'''
methods = ('void Player::Restore(uint32 spellId) {\n'+dependency+'\n}\n'
           'void Player::TcSkill(SpellLearnSkillNode const* spellLearnSkill,uint32 fromSkill) '+tc_skill+'\n'
           'void Player::AcSkill(SpellLearnSkillNode const* spellLearnSkill) '
           '{uint16 maxskill=GetMaxSkillValueForLevel();'+ac_skill+'}\n'
           'void Spell::TcEffect() '+tc_effect+'\nvoid Spell::AcEffect() '+ac_effect+'\n')
main = r'''
int main() {
    for (int mode:{0,1}) { Spell spell;spell.effectHandleMode=mode;spell.TcEffect();spell.AcEffect(); }
    manager.rows.emplace(33943,SpellLearnSpellNode{});
    Player restored;restored.Restore(33943);
    assert((restored.added==std::vector<uint32>{34090}));
    Player absent;absent.Restore(40120);assert(absent.added.empty());
    manager.rows.begin()->second.AutoLearned=true;
    Player automatic;automatic.Restore(33943);assert(automatic.added.empty());
    for (uint32 cap:{225,300}) {
        Player tc,ac;tc.value=ac.value=tc.cap=ac.cap=cap;
        for (uint32 tier=1;tier<=cap/75;++tier) {
            SpellLearnSkillNode node{762,tier,tier*75,tier*75};
            tc.TcSkill(&node,0);ac.AcSkill(&node);
            assert(tc.value==cap && ac.value==cap && tc.cap==cap && ac.cap==cap);
            assert(tc.slots==2 && ac.slots==2);
        }
        assert(tc.step==cap/75 && ac.step==cap/75);
    }
    // Negative control: a missing/insufficient skill really would be raised.
    Player tc,ac;tc.value=ac.value=tc.cap=ac.cap=150;
    SpellLearnSkillNode expert;
    tc.TcSkill(&expert,0);ac.AcSkill(&expert);
    assert(tc.value==225 && ac.value==225 && tc.cap==225 && ac.cap==225);
    std::cout << "Protected TC dependency and TC/AC riding skill bodies passed; state sinks mocked; gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp,binary=Path(directory)/'riding.cpp',Path(directory)/'riding'
    cpp.write_text(mock+methods+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
