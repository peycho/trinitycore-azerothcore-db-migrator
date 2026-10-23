#!/usr/bin/env python3
"""Execute protected loader casting branches with recording cast sinks.

This tests only the reviewed auto-cast decision, not complete player loading or
research execution. Synthetic MySQL checks cover the stored rows and skills.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

tc,ac=map(Path,sys.argv[1:])
tc_source=(tc/'src/server/game/Entities/Player/Player.cpp').read_text()
tc_start=tc_source.index('// cast talents with SPELL_EFFECT_LEARN_SPELL')
tc_branch=tc_source[tc_start:tc_source.index('// update used talent points count',tc_start)]
ac_source=(ac/'src/server/game/Entities/Player/Player.cpp').read_text()
ac_start=ac_source.index('// xinef: do not add spells with effect learn spell')
ac_branch=ac_source[ac_start:ac_source.index('// xinef: unapply aura stats',ac_start)]
start=tc_source.index('// learn dependent spells',tc_source.index('bool Player::AddSpell('))
tc_dependencies=tc_source[start:tc_source.index('if (!GetSession()->PlayerLoading())',start)]
mock=r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <vector>
using uint32=uint32_t;
constexpr int SPELL_EFFECT_LEARN_SPELL=36, SPELL_EFFECT_SKILL_STEP=44;
constexpr uint32 SPELL_ATTR0_CU_IS_TALENT=0x800000, SPELL_ATTR0_DO_NOT_DISPLAY=128;
#define LOG_INFO(...) ((void)0)
struct SpellInfo {
    uint32 Id=60893,flags=0x10020,Stances=0;
    std::array<int,3> effects{157,77,0};
    bool HasEffect(int effect) const {
        for (int actual:effects) if (actual==effect) return true;
        return false;
    }
    bool HasAttribute(uint32 flag) const { return flags & flag; }
    bool IsPassive() const { return flags & 64; }
};
struct SpellLearnSpellNode{uint32 Spell;bool Active=false,AutoLearned=false;};
using SpellLearnSpellMap=std::multimap<uint32,SpellLearnSpellNode>;
using SpellLearnSpellMapBounds=std::pair<SpellLearnSpellMap::const_iterator,SpellLearnSpellMap::const_iterator>;
struct SpellMgr{
 SpellLearnSpellMap rows;
 SpellLearnSpellMapBounds GetSpellLearnSpellMapBounds(uint32 id)const{return rows.equal_range(id);}
} manager;SpellMgr*sSpellMgr=&manager;
struct Player {
    int casts=0;uint32 groups=2,active=0;
    std::vector<uint32> restored;
    bool IsInWorld()const{return false;}
    void AddSpell(uint32 id,bool visible,bool learning,bool dependent,bool disabled){
        assert(visible&&learning&&dependent&&!disabled);restored.push_back(id);
    }
    void LearnSpell(uint32,bool){assert(false);}
    void RestoreTcDependencies(uint32 spellId){
'''+tc_dependencies+r'''
    }
    std::map<uint32,int> m_spells;
    void CastSpell(Player*,uint32,bool) { ++casts; }
    bool HandlePassiveSpellLearn(SpellInfo const*) const { return true; }
    bool IsNeedCastPassiveSpellAtLearn(SpellInfo const*) const { return true; }
    bool TcLoad(SpellInfo const* spellInfo,bool loading) {
        uint32 spellId=spellInfo->Id;
'''
middle='\nreturn true;\n}\nbool AcLoad(SpellInfo const* spellInfo) {\nuint32 spellId=spellInfo->Id;\n'
main=r'''
return true;
}
};
int main() {
    manager.rows.emplace(63680,SpellLearnSpellNode{63645,true,false});
    manager.rows.emplace(63680,SpellLearnSpellNode{63644,true,false});
    manager.rows.emplace(63706,SpellLearnSpellNode{63645,true,false});
    manager.rows.emplace(63707,SpellLearnSpellNode{63644,true,false});
    for(uint32 active:{0,1}){
        Player tc,oldAc;tc.active=oldAc.active=active;
        SpellInfo teacher;teacher.Id=63680;teacher.flags=536871296;teacher.effects={36,36,0};
        assert(tc.TcLoad(&teacher,true));tc.RestoreTcDependencies(63680);
        assert((tc.restored==std::vector<uint32>{63645,63644}));
        assert(!oldAc.AcLoad(&teacher));assert(tc.casts==0&&oldAc.casts==0);
        for(uint32 id:{63644,63645}){
            SpellInfo button;button.Id=id;button.flags=268435584;button.effects={162,0,0};
            Player normalized;normalized.active=active;
            assert(normalized.TcLoad(&button,true)&&normalized.AcLoad(&button));
            assert(normalized.casts==0&&normalized.groups==2&&normalized.active==active);
        }
    }
    for(uint32 active:{0,1})for(uint32 id:{63706,63707}){
        Player tc,oldAc;tc.active=oldAc.active=active;
        SpellInfo teacher;teacher.Id=id;teacher.flags=0;teacher.effects={36,0,0};
        assert(tc.TcLoad(&teacher,true));tc.RestoreTcDependencies(id);
        assert((tc.restored==std::vector<uint32>{id==63706?63645u:63644u}));
        assert(!oldAc.AcLoad(&teacher));assert(tc.casts==0&&oldAc.casts==0);
        assert(tc.groups==2&&tc.active==active&&oldAc.groups==2&&oldAc.active==active);
    }
    for (uint32 id:{60893,61177,61288}) {
        SpellInfo research; research.Id=id;
        Player tc,ac;
        assert(tc.TcLoad(&research,true));
        assert(ac.AcLoad(&research));
        assert(tc.casts==0 && ac.casts==0);
    }
    for (uint32 id:{53323,53331,53341,53342,53343,53344,54446,54447,62158,70164}) {
        SpellInfo rune; rune.Id=id; rune.flags=65952; rune.effects={53,3,0};
        Player tc,ac;
        assert(tc.TcLoad(&rune,true) && ac.AcLoad(&rune));
        assert(tc.casts==0 && ac.casts==0);
    }
    SpellInfo passive; passive.flags|=64;
    Player tcPassive,acPassive;
    tcPassive.TcLoad(&passive,true); acPassive.AcLoad(&passive);
    assert(tcPassive.casts==1 && acPassive.casts==1);
    SpellInfo stance; stance.flags|=128; stance.Stances=1;
    Player acStance; acStance.AcLoad(&stance); assert(acStance.casts==1);
    SpellInfo step; step.effects={44,77,0};
    Player tcStep,acStep;
    assert(!tcStep.TcLoad(&step,true) && !acStep.AcLoad(&step));
    assert(tcStep.casts==1 && acStep.casts==1);
    std::cout << "Protected TC/AC loader auto-cast branches: dual-spec teacher dependencies and uncast buttons, research and Runeforging uncast; passive/stance/skill-step controls passed\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp=Path(directory)/'research.cpp'
    binary=Path(directory)/'research-tests'
    cpp.write_text(mock+tc_branch+middle+ac_branch+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
