#!/usr/bin/env python3
"""Verify the native predecessor-call difference that keeps ranked children blocked."""
from pathlib import Path
import subprocess
import sys
import tempfile


tc, ac = map(Path, sys.argv[1:])
tc_source = (tc / 'src/server/game/Entities/Player/Player.cpp').read_text()
start = tc_source.index('// talent: unlearn all other talent ranks (high and low)')
end = tc_source.index('std::pair<PlayerSpellMap::iterator, bool> inserted', start)
tc_branch = tc_source[start:end]
start=tc_source.index('bool Player::HasSpell(uint32 spell) const')
end=tc_source.index('\nbool Player::HasTalent(',start)
tc_known=tc_source[start:end]
start=tc_source.index('// return false if spell disabled',tc_source.index('bool Player::AddSpell('))
end=tc_source.index('\n    }',start)
tc_disabled=tc_source[start:end]
ac_source = (ac / 'src/server/game/Entities/Player/Player.cpp').read_text()
start = ac_source.index('void Player::_addTalentAurasAndSpells(')
pos = ac_source.index('{', start)
depth, end = 1, pos + 1
while depth:
    depth += (ac_source[end] == '{') - (ac_source[end] == '}')
    end += 1
ac_function = ac_source[start:end]
mock = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <vector>
using uint8=uint8_t;using uint32=uint32_t;
constexpr uint8 MAX_SPELL_EFFECTS=3,MAX_TALENT_RANK=5,SPEC_MASK_ALL=3;
constexpr int SPELL_EFFECT_LEARN_SPELL=36,SPELL_ATTR0_DO_NOT_DISPLAY=128;
constexpr int PLAYERSPELL_REMOVED=1;
struct PlayerSpell {int state=0;bool disabled=false;};
using PlayerSpellMap=std::map<uint32,PlayerSpell>;
struct TalentSpellPos { uint32 talent_id=1; };
TalentSpellPos position;
TalentSpellPos const* GetTalentSpellPos(uint32 id) { return id==37117?&position:nullptr; }
struct TalentEntry { std::array<uint32,5> SpellRank{37116,37117,0,0,0}; };
struct TalentStore { TalentEntry row;TalentEntry const* LookupEntry(uint32) const { return &row; } };
TalentStore sTalentStore;
struct Effect { int Effect=0;uint32 TriggerSpell=0; };
struct SpellInfo {
    std::array<Effect,3> Effects{Effect{36,16961},{},{}};uint32 Stances=0;
    bool HasEffect(int effect) const { return effect==36; }
    bool IsPassive() const { return false; }
    bool HasAttribute(int) const { return false; }
};
struct SpellMgr {
    SpellInfo info;
    uint32 GetPrevSpellInChain(uint32 id) const {
        static std::map<uint32,uint32> previous{{16961,16958},{50111,50110},{50110,50109},{50109,50108},{50108,50096},{10308,5589}};
        auto it=previous.find(id);return it==previous.end()?0:it->second;
    }
    SpellInfo const* GetSpellInfo(uint32 id) const { assert(id==37117);return &info; }
    bool IsAdditionalTalentSpell(uint32) const { return false; }
};
SpellMgr manager;SpellMgr* sSpellMgr=&manager;
struct Player {
    std::vector<uint32> predecessors,temporary,removed;
    std::vector<bool> predecessorDisabled;
    PlayerSpellMap m_spells;
    bool HasSpell(uint32)const;
    bool IsInWorld() const { return false; }
    void RemoveSpell(uint32 id,bool,bool) { removed.push_back(id); }
    void AddSpell(uint32 id,bool,bool learning,bool dependent,bool disabled,bool loading,uint32) {
        assert(learning && dependent && !loading);predecessors.push_back(id);predecessorDisabled.push_back(disabled);
        m_spells[id]={0,disabled};
    }
    void LearnSpell(uint32,bool,uint32) { assert(false); }
    void _addSpell(uint32 id,uint8 mask,bool temp) { assert(mask==3 && temp);temporary.push_back(id); }
    bool IsNeedCastPassiveSpellAtLearn(SpellInfo const*) const { return false; }
    void CastSpell(Player*,uint32,bool) { assert(false); }
    void _addTalentAurasAndSpells(uint32);
    void TcRankBranch(uint32 spellId,bool active=true,bool disabled=false,uint32 fromSkill=0) {
'''
mock += tc_branch + '\n}\n bool RunPostLoadEffects(bool disabled){PlayerSpell newspell{0,disabled};'+tc_disabled+'\nreturn true;}\n};\n' + ac_function+'\n'+tc_known
mock += r'''
int main() {
    Player tc,ac;
    tc.TcRankBranch(16961);ac._addTalentAurasAndSpells(37117);
    assert(tc.predecessors==std::vector<uint32>{16958});
    assert(ac.temporary==std::vector<uint32>{16961});
    Player direct;direct.TcRankBranch(37117);
    assert(direct.predecessors.empty());
    assert(direct.removed==std::vector<uint32>{37116});
    Player history;history.m_spells[6603]={0,false};
    for(uint32 id:{50111,50110,50109,50108}){
        history.m_spells[id]={0,true};history.TcRankBranch(id,true,true);
        assert(!history.HasSpell(id)&&!history.RunPostLoadEffects(true));
    }
    assert((history.predecessors==std::vector<uint32>{50110,50109,50108,50096}));
    for(bool disabled:history.predecessorDisabled)assert(disabled);
    for(uint32 id:{50111,50110,50109,50108,50096}){
        assert(!history.HasSpell(id));history.m_spells.erase(id);assert(!history.HasSpell(id));
    }
    assert(history.HasSpell(6603)&&history.RunPostLoadEffects(false));
    Player ordinary;ordinary.m_spells[6603]={0,false};
    ordinary.m_spells[10308]={0,true};ordinary.m_spells[5589]={0,true};
    ordinary.TcRankBranch(10308,true,true);
    assert((ordinary.predecessors==std::vector<uint32>{5589}));
    assert(ordinary.predecessorDisabled.front());
    assert(!ordinary.HasSpell(10308)&&!ordinary.HasSpell(5589));
    assert(!ordinary.RunPostLoadEffects(true));
    ordinary.m_spells.erase(10308);ordinary.m_spells.erase(5589);
    assert(!ordinary.HasSpell(10308)&&!ordinary.HasSpell(5589)&&ordinary.HasSpell(6603));
    std::cout << "Protected ordinary disabled rank/HasSpell/early-return controls passed before and after exact removal; state sinks mocked\n";
    std::cout << "Protected rank/talent consumers passed: TC predecessor calls retain disabled flags; HasSpell excludes disabled history before/after removal, post-load disabled guard prevents effects, enabled control retained; AC exact temporary child and direct-talent controls passed; sinks mocked, gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'ranks.cpp'
    binary = Path(directory) / 'ranks'
    cpp.write_text(mock)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
