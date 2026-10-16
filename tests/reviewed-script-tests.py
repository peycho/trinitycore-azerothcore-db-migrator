#!/usr/bin/env python3
"""Execute reviewed script callbacks with recording sinks, not full spell effects."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def method(source, cls, signature):
    source = source[source.index('class ' + cls + ' '):]
    start = source.index(signature)
    pos = source.index('{', start)
    depth, end = 1, pos + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


tc, ac = map(Path, sys.argv[1:])
generic = (tc / 'src/server/scripts/Spells/spell_generic.cpp').read_text()
warlock = (tc / 'src/server/scripts/Spells/spell_warlock.cpp').read_text()
teron = (ac / 'src/server/scripts/Outland/BlackTemple/boss_teron_gorefiend.cpp').read_text()
instance = (ac / 'src/server/scripts/Outland/BlackTemple/instance_black_temple.cpp').read_text()
for source, name, value in [(generic, 'SPELL_WILL_OF_THE_FORSAKEN_COOLDOWN_TRIGGER', 72752),
                            (generic, 'SPELL_WILL_OF_THE_FORSAKEN_COOLDOWN_TRIGGER_WOTF', 72757),
                            (warlock, 'SPELL_WARLOCK_SHADOWFLAME', 37378),
                            (warlock, 'SPELL_WARLOCK_FLAMESHADOW', 37379)]:
    assert re.search(rf'\b{name}\s*=\s*{value}\b', source)
wotf = method(generic, 'spell_pvp_trinket_wotf_shared_cd', 'void HandleScript(')
proc = method(warlock, 'spell_warl_t4_2p_bonus', 'void HandleProc(')
for name,value in [('SPELL_BRIEF_STUN',41421),('SPELL_SPIRIT_LANCE',40157),
                   ('SPELL_SPIRIT_CHAINS',40175),('SPELL_SPIRIT_VOLLEY',40314)]:
    assert re.search(rf'\b{name}\s*=\s*{value}\b',teron)
construct_load = method(teron,'spell_teron_gorefiend_shadowy_construct','bool Load()')
construct_apply = method(teron,'spell_teron_gorefiend_shadowy_construct','void HandleEffectApply(')
friend = method(instance, 'spell_black_template_free_friend', 'void HandleScriptEffect(')
mock = r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <tuple>
#include <vector>
using uint32=uint32_t; using SpellEffIndex=int;
// Recording stand-in: verify the handler passes this exact mask symbol.
constexpr uint32 IMMUNE_TO_MOVEMENT_IMPAIRMENT_AND_LOSS_CONTROL_MASK=123;
struct AuraEffect {};
struct Unit {
    std::vector<std::tuple<uint32,bool>> casts; std::vector<uint32> masks;
    void CastSpell(Unit* target,uint32 id,bool triggered) { assert(!target); casts.emplace_back(id,triggered); }
    void CastSpell(Unit* target,uint32 id,AuraEffect const*) { assert(target==this); casts.emplace_back(id,true); }
    void RemoveAurasWithMechanic(uint32 mask) { masks.push_back(mask); }
};
struct ProcEventInfo { Unit* actor; Unit* GetActor() { return actor; } };
template <uint32 TriggeredSpellId> struct Cooldown {
    Unit caster; Unit* GetCaster() { return &caster; }
'''
mock += wotf + '\n};\n'
mock += r'''
template <uint32 TriggerSpellId> struct Bonus {
    int prevented=0;
    void PreventDefaultAction() { ++prevented; }
'''
mock += proc + '\n};\n'
mock += r'''
struct Friend {
    Unit* target=nullptr; std::vector<int> prevented;
    Unit* GetHitUnit() { return target; }
    void PreventHitDefaultEffect(int effect) { prevented.push_back(effect); }
'''
mock += friend + '\n};\n'
mock += r'''
using AuraEffectHandleModes=int;
constexpr int IMMUNITY_SCHOOL=1,IMMUNITY_ALLOW_ID=2,SPELL_SCHOOL_MASK_NORMAL=4;
constexpr int SPELL_SPIRIT_LANCE=40157,SPELL_SPIRIT_CHAINS=40175,SPELL_SPIRIT_VOLLEY=40314;
constexpr int SPELL_BRIEF_STUN=41421;
struct Player { bool enemy; };
struct PlayerRef { Player* ptr; Player* GetSource() const { return ptr; } };
struct Map { using PlayerList=std::vector<PlayerRef>; PlayerList players;
    PlayerList const& GetPlayers() { return players; } };
struct ConstructOwner {
    bool creature=false; int combats=0; Map map;
    std::vector<std::tuple<int,int,int,bool>> immunities;
    std::vector<std::tuple<Player*,float>> threats;
    std::vector<std::tuple<int,bool>> casts;
    bool IsCreature() { return creature; }
    ConstructOwner* ToCreature() { assert(creature);return this; }
    void ApplySpellImmune(int id,int type,int spell,bool enabled) { immunities.emplace_back(id,type,spell,enabled); }
    void SetInCombatWithZone() { ++combats; }
    Map* GetMap() { return &map; }
    bool IsValidAttackTarget(Player* player) { return player->enemy; }
    void AddThreat(Player* player,float value) { threats.emplace_back(player,value); }
    void CastSpell(ConstructOwner* target,int spell,bool triggered) {
        assert(target==this);casts.emplace_back(spell,triggered);
    }
};
struct ConstructBase { virtual bool Load()=0; };
struct Construct : ConstructBase {
    ConstructOwner owner; ConstructOwner* GetUnitOwner() { return &owner; }
'''
mock += construct_load+'\n'+construct_apply+'\n};\n'
mock += r'''
int main() {
    Cooldown<72752> trinket;trinket.HandleScript();
    Cooldown<72757> racial;racial.HandleScript();
    assert((trinket.caster.casts==std::vector<std::tuple<uint32,bool>>{{72752,false}}));
    assert((racial.caster.casts==std::vector<std::tuple<uint32,bool>>{{72757,false}}));
    Unit actor;ProcEventInfo event{&actor};AuraEffect aura;
    Bonus<37378> fire;fire.HandleProc(&aura,event);
    Bonus<37379> shadow;shadow.HandleProc(&aura,event);
    assert(fire.prevented==1 && shadow.prevented==1);
    assert((actor.casts==std::vector<std::tuple<uint32,bool>>{{37378,true},{37379,true}}));
    Friend missing;missing.HandleScriptEffect(0);
    assert(missing.prevented==std::vector<int>{0});
    Unit target;Friend present;present.target=&target;present.HandleScriptEffect(0);
    assert(present.prevented==std::vector<int>{0});
    assert(target.masks==std::vector<uint32>{IMMUNE_TO_MOVEMENT_IMPAIRMENT_AND_LOSS_CONTROL_MASK});
    assert(target.casts.empty());
    Construct construct;
    assert(!construct.Load()); // Player-owned aura is rejected by the native filter.
    construct.owner.creature=true;assert(construct.Load());
    Player enemy{true},friendly{false};
    construct.owner.map.players={{nullptr},{&friendly},{&enemy}};
    construct.HandleEffectApply(&aura,0);
    assert((construct.owner.immunities==std::vector<std::tuple<int,int,int,bool>>{
        {0,IMMUNITY_SCHOOL,SPELL_SCHOOL_MASK_NORMAL,true},
        {0,IMMUNITY_ALLOW_ID,40157,true},{0,IMMUNITY_ALLOW_ID,40175,true},{0,IMMUNITY_ALLOW_ID,40314,true}}));
    assert(construct.owner.combats==1);
    assert((construct.owner.threats==std::vector<std::tuple<Player*,float>>{{&enemy,1000000.0f}}));
    assert((construct.owner.casts==std::vector<std::tuple<int,bool>>{{41421,true}}));
    std::cout << "Protected Shadowy Construct Load/apply: creature filter, immunities, hostile-only threat and exact stun passed; sinks mocked\n";
    std::cout << "Protected cooldown, T4 proc and Free Friend callbacks: exact casts/mask symbol and null-target control passed; sinks mocked\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'scripts.cpp'
    binary = Path(directory) / 'scripts'
    cpp.write_text(mock)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
