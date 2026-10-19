#!/usr/bin/env python3
"""Execute the pinned AC trainer function with mocked state getters.

This tests the actual consumer function against rows produced by MySQL fixture
loading. It is deliberately not a substitute for native gameplay acceptance.
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ac, rows_file = map(Path, sys.argv[1:])
source = (ac/'src/server/game/Entities/Creature/Trainer.cpp').read_text()
start = source.index('SpellState Trainer::GetDefaultSpellState(')
opening = source.index('{',start)
end,depth = opening+1,1
while depth:
    depth += (source[end]=='{')-(source[end]=='}')
    end += 1
function = source[start:end]
spec = importlib.util.spec_from_file_location('fixtures',Path(__file__).with_name('spell-fixtures.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)

mock = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <vector>
using uint32=uint32_t; using int32=int32_t;
constexpr int SPELL_EFFECT_LEARN_SPELL=36;
enum class SpellState { Known, Unavailable, Available };
struct SpellEffectInfo {
    int effect; uint32 TriggerSpell;
    bool IsEffect(int value) const { return effect==value; }
};
struct SpellInfo {
    std::vector<SpellEffectInfo> effects;
    auto const& GetEffects() const { return effects; }
};
struct SpellMgr {
    std::map<uint32,SpellInfo> spells;
    std::map<uint32,uint32> previous;
    std::map<uint32,std::vector<std::pair<uint32,uint32>>> required;
    SpellInfo const* AssertSpellInfo(uint32 id) { return &spells[id]; }
    uint32 GetPrevSpellInChain(uint32 id) { return previous[id]; }
    std::vector<std::pair<uint32,uint32>> GetSpellsRequiredForSpellBounds(uint32 id) { return required[id]; }
};
SpellMgr manager; SpellMgr* sSpellMgr=&manager;
struct Player {
    std::map<uint32,uint32> spells; uint32 spec=0;
    bool HasSpell(uint32 id) const {
        auto found=spells.find(id);
        return found!=spells.end() && (found->second & (1<<spec));
    }
    bool IsSpellFitByClassAndRace(uint32) const { return true; }
    uint32 GetBaseSkillValue(uint32) const { return 450; }
    uint32 GetLevel() const { return 80; }
};
struct Trainer {
    struct Spell {
        uint32 SpellId,ReqSkillLine=0,ReqSkillRank=0,ReqLevel=0;
        std::array<int32,3> ReqAbility{};
    };
    SpellState GetDefaultSpellState(Player const*,Spell const*) const;
};
'''
main = ['int main() { Trainer trainer; std::map<uint32,Player> players;']
for row in rows_file.read_text().splitlines():
    guid,spell,mask = map(int,row.split('\t'))
    main.append(f'players[{guid}].spells[{spell}]={mask};')
for chain in fixtures.CHAINS:
    for previous,spell in zip(chain,chain[1:]):
        main.append(f'manager.previous[{spell}]={previous};')
    for spell in chain:
        main.append(f'manager.spells[{spell}];')
        # Wrapper IDs only exist in the mock trainer catalog, never in
        # migrated character data or the reconstruction's grant set.
        main.append(f'manager.spells[{1000000+spell}].effects.push_back({{36,{spell}}});')
main.append('''
for (auto const& original : players) {
    Player player=original.second;
    for (uint32 spec=0;spec<2;++spec) {
        player.spec=spec;
        for (auto const& definition : manager.spells) {
            uint32 id=definition.first;
            uint32 learned=definition.second.effects.empty()?id:definition.second.effects[0].TriggerSpell;
            Trainer::Spell spell{id};
            bool known=trainer.GetDefaultSpellState(&player,&spell)==SpellState::Known;
            assert(known==player.HasSpell(learned));
        }
    }
}
// Known ordinary spells remain known without training prerequisites. Unknown
// spells stay unavailable; neither direct nor wrapped checks grant their parent.
manager.required[5209]={{5209,5487}};
manager.spells[1005209].effects={{36,5209}};manager.required[1005209]={{1005209,5487}};
for(uint32 guid:{128,129})for(uint32 spec:{0,1}){
 Player player=players[guid];player.spec=spec;
 Trainer::Spell direct{5209},wrapped{1005209};
 assert(player.HasSpell(5209)&&!player.HasSpell(5487)&&!player.HasSpell(9634));
 assert(trainer.GetDefaultSpellState(&player,&direct)==SpellState::Known);
 assert(trainer.GetDefaultSpellState(&player,&wrapped)==SpellState::Known);
 player.spells.erase(5209);
 assert(trainer.GetDefaultSpellState(&player,&direct)==SpellState::Unavailable);
 assert(trainer.GetDefaultSpellState(&player,&wrapped)==SpellState::Unavailable);
}
// Regression: the old highest-only copy offers rank 1 again.
Player old; old.spells[48942]=3;
Trainer::Spell low{465};
assert(trainer.GetDefaultSpellState(&old,&low)!=SpellState::Known);
assert(players[110].HasSpell(465));
// Native passive normalization cannot pretend an absent internal rank is
// trainer-known. The metadata contract rejects any real trainer offering it.
manager.spells[16958];manager.spells[1016958].effects.push_back({36,16958});
Player nativePassive;
Trainer::Spell internal{16958},wrappedInternal{1016958};
assert(trainer.GetDefaultSpellState(&nativePassive,&internal)!=SpellState::Known);
assert(trainer.GetDefaultSpellState(&nativePassive,&wrappedInternal)!=SpellState::Known);
// The consumed wrapper remains trainer-known through both native learn effects;
// no persistent wrapper or spec-count purchase effect is needed.
manager.spells[63680].effects={{36,63645},{36,63644}};
Trainer::Spell dualTeacher{63680};
for(uint32 guid:{126,127})for(uint32 spec:{0,1}){
    Player player=players[guid];player.spec=spec;
    assert(!player.HasSpell(63680)&&player.HasSpell(63644)&&player.HasSpell(63645));
    assert(trainer.GetDefaultSpellState(&player,&dualTeacher)==SpellState::Known);
    player.spells.erase(63644);assert(trainer.GetDefaultSpellState(&player,&dualTeacher)!=SpellState::Known);
}
std::cout << "Pinned AC trainer direct/wrapped spell regressions passed\\n";
}''')
with tempfile.TemporaryDirectory() as directory:
    cpp=Path(directory)/'trainer.cpp'
    binary=Path(directory)/'trainer-tests'
    cpp.write_text(mock+'\n'+function+'\n'+'\n'.join(main))
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
