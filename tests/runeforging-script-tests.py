#!/usr/bin/env python3
"""Exercise the protected TC quest-credit handler with recording cast sinks."""
from pathlib import Path
import subprocess
import sys
import tempfile

tc=Path(sys.argv[1])
source=(tc/'src/server/scripts/EasternKingdoms/ScarletEnclave/chapter1.cpp').read_text()
start=source.index('class spell_chapter1_runeforging_credit ')
start=source.index('void HandleDummy(',start)
opening=source.index('{',start)
end,depth=opening+1,1
while depth:
    depth+=(source[end]=='{')-(source[end]=='}')
    end+=1
handler=source[start:end]
mock=r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>
using uint32=uint32_t;using SpellEffIndex=int;
constexpr uint32 SPELL_RUNEFORGING_CREDIT=54586,QUEST_RUNEFORGING=12842;
constexpr int QUEST_STATUS_INCOMPLETE=1;
struct Player {
    int status=0;std::vector<uint32> casts;
    int GetQuestStatus(uint32 id) const { assert(id==QUEST_RUNEFORGING);return status; }
    void CastSpell(Player* target,uint32 id) { assert(target==this);casts.push_back(id); }
};
struct Unit { Player* player=nullptr;Player* ToPlayer() const { return player; } };
struct Handler { Unit unit;Unit* GetCaster() { return &unit; }
'''
main=r'''
};
int main() {
    Handler nonplayer;nonplayer.HandleDummy(1);
    Player completed;Handler absent;absent.unit.player=&completed;absent.HandleDummy(1);
    assert(completed.casts.empty());
    Player incomplete;incomplete.status=QUEST_STATUS_INCOMPLETE;
    Handler credit;credit.unit.player=&incomplete;credit.HandleDummy(1);
    assert((incomplete.casts==std::vector<uint32>{54586}));
    std::cout << "Protected TC Runeforging handler: incomplete quest emits only credit cast; completed/nonplayer controls passed; cast sink mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp=Path(directory)/'runeforging.cpp'
    binary=Path(directory)/'runeforging-tests'
    cpp.write_text(mock+handler+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
