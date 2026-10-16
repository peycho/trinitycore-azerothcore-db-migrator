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
mock=r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
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
struct Player {
    int casts=0;
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
    std::cout << "Protected TC/AC loader auto-cast branches: research and Runeforging uncast; passive/stance/skill-step controls passed\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp=Path(directory)/'research.cpp'
    binary=Path(directory)/'research-tests'
    cpp.write_text(mock+tc_branch+middle+ac_branch+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
