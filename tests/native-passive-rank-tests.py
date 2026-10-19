#!/usr/bin/env python3
"""Protected AC add/remove/save and passive stacking, with state/DB sinks mocked.

The spec scheduler, aura engine and database connection are isolated fixtures.
This is consumer behavior verification, not native worldserver gameplay.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def function(source, signature):
    start=source.index(signature)
    opening=source.index('{',start)
    end,depth=opening+1,1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}')
        end+=1
    return source[start:end]


tc,ac=map(Path,sys.argv[1:])
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fixtures',root/'tests/spell-fixtures.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
profile=json.loads((root/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
data=fixtures.stores(profile)
player=(ac/'src/server/game/Entities/Player/Player.cpp').read_text()
methods='\n'.join(function(player,signature) for signature in (
    'void Player::_addTalentAurasAndSpells(', 'bool Player::_addSpell(',
    'void Player::_removeTalentAurasAndSpells(', 'void Player::removeSpell('))
methods+='\n'+function((ac/'src/server/game/Entities/Player/PlayerStorage.cpp').read_text(),'void Player::_SaveSpells(')
callbacks=[]
for repo,name in ((tc,'WillTc'),(ac,'WillAc')):
    script=(repo/'src/server/scripts/Spells/spell_dk.cpp').read_text()
    script=script[script.index('class spell_dk_will_of_the_necropolis '):]
    callbacks.append('struct '+name+r''' {
        Player* player;SpellInfo const* info;uint32 absorbPct=0;
        Player* GetCaster() const{return player;}Player* GetTarget() const{return player;}
        SpellInfo const* GetSpellInfo() const{return info;}
        Effect const& GetEffectInfo(int index) const{return info->Effects[index];}
    '''+'\n'.join(function(script,signature).replace(' override','') for signature in
                  ('bool Load()','void CalculateAmount(','void Absorb('))+'\n};\n')
nurturing=[]
for repo,name in ((tc,'TcNurturing'),(ac,'AcNurturing')):
    script=(repo/'src/server/scripts/Spells/spell_druid.cpp').read_text()
    script=script[script.index('class spell_dru_nurturing_instinct '):]
    nurturing.append('struct '+name+" { Player* player; SpellInfo const* info; Player* GetTarget(){return player;} SpellInfo const* GetSpellInfo(){return info;}\n"+
                     '\n'.join(function(script,signature) for signature in ('void AfterApply(','void AfterRemove('))+'\n};\n')
stack=[]
for repo,name in ((tc,'TcStack'),(ac,'AcStack')):
    source=(repo/'src/server/game/Spells/Auras/SpellAuras.cpp').read_text()
    text=function(source,'bool Aura::CanStackWith(')
    # Execute the early same-caster passive exclusion and, separately, the
    # non-passive same-rank branch used by Nurturing's hidden helper chain.
    end=text.index('for (',text.index('// passive auras'))
    stack.append(text[:end].replace('Aura::CanStackWith','Aura::'+name)+'\nreturn true;\n}\n')
    rank=text[text.index('// spell of same spell rank chain'):]
    stack.append('bool Aura::'+name+'Rank(Aura const*existingAura)const {auto existingSpellInfo=existingAura->GetSpellInfo();'+
                 ('bool sameCaster=true;' if repo==ac else '')+rank)
    info=(repo/'src/server/game/Spells/SpellInfo.cpp').read_text()
    stack.append(function(info,'bool SpellInfo::IsMultiSlotAura() const').replace('IsMultiSlotAura()',name+'MultiSlot()'))

mock=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <vector>
using uint8=uint8_t;using uint16=uint16_t;using uint32=uint32_t;
using int32=int32_t;
constexpr int EFFECT_0=0;
constexpr uint32 SPELL_DRUID_NURTURING_INSTINCT_R1=47179,SPELL_DRUID_NURTURING_INSTINCT_R2=47180;
constexpr uint32 SPELLFAMILY_HUNTER=9,SPELL_SPECIFIC_AURA=1;
#define UI64LIT(x) x##ULL
enum SpellAttr2 {SPELL_ATTR2_ALLOW_WHILE_NOT_SHAPESHIFTED=1};
using ShapeshiftForm=uint32;
constexpr uint32 SPELL_DK_WILL_OF_THE_NECROPOLIS_TALENT_R1=49189;
uint32 CalculatePct(uint32 value,uint32 pct){return value*pct/100;}
struct AuraEffect {};
struct DamageInfo {uint32 damage;uint32 GetDamage() const{return damage;}};
enum SpellState { PLAYERSPELL_UNCHANGED,PLAYERSPELL_CHANGED,PLAYERSPELL_NEW,PLAYERSPELL_REMOVED,PLAYERSPELL_TEMPORARY };
enum SpellAttr0 { SPELL_ATTR0_PASSIVE=64,SPELL_ATTR0_DO_NOT_DISPLAY=128,SPELL_ATTR0_CU_ENCHANT_PROC=256 };
constexpr uint8 MAX_SPELL_EFFECTS=3,SPEC_MASK_ALL=3;
constexpr uint32 SPELL_EFFECT_LEARN_SPELL=36,SPELL_EFFECT_SKILL_STEP=44;
constexpr int DYNOBJ_AURA_TYPE=1,SPELL_AURA_PERIODIC_DAMAGE=3;
constexpr int AURA_STATE_HEALTHLESS_35_PERCENT=1,AURA_STATE_HEALTH_ABOVE_75_PERCENT=23,AURA_STATE_HEALTHLESS_20_PERCENT=2;
constexpr int AURA_EFFECT_HANDLE_REAL=0,SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN=2,SKILL_LOCKPICKING=633,SKILL_RUNEFORGING=776,SKILL_MOUNTS=777;
constexpr int ACHIEVEMENT_CRITERIA_TYPE_LEARN_SKILL_LINE=1,ACHIEVEMENT_CRITERIA_TYPE_LEARN_SKILLLINE_SPELLS=2,ACHIEVEMENT_CRITERIA_TYPE_LEARN_SPELL=3;
constexpr int CHAR_DEL_CHAR_SPELL_BY_SPELL=1,CHAR_INS_CHAR_SPELL=2;
constexpr int SPELL_AURA_MOD_INCREASE_MOUNTED_FLIGHT_SPEED=207,CONFIG_MAX_PRIMARY_TRADE_SKILL=0;
struct World { uint32 getIntConfig(int) const{return 2;} } world;
World* sWorld=&world;
using AuraStateType=int;using AuraEffectHandleModes=uint32;
#define LOG_INFO(...) ((void)0)
struct Guid { uint32 id=0;bool IsEmpty() const{return !id;}explicit operator bool() const{return id;}bool operator!=(Guid other) const{return id!=other.id;}uint32 GetRawValue() const{return id;} };
struct Effect { uint32 Effect=0,TriggerSpell=0,ApplyAuraName=0;int amount=0;bool IsEffect() const{return Effect;}int CalcValue(void const* =nullptr) const{return amount;} };
struct SpellInfo {
    uint32 SpellFamilyName=7,SpellFamilyFlags[3]{};
    uint32 Id=0,flags=192,root=0,Stances=0,CasterAuraState=0,rank=1;std::array<Effect,3> Effects{};
    uint8 GetRank() const{return rank;}Effect const& GetEffect(int index) const{return Effects[index];}
    bool TcStackMultiSlot()const;bool AcStackMultiSlot()const;
    bool IsMultiSlotAura()const{return IsPassive();}uint32 GetSpellSpecific()const{return 0;}
    bool IsRankOf(SpellInfo const*other)const{return root==other->root;}
    bool HasAttribute(SpellAttr2)const{return false;}
    bool HasEffect(uint32 value) const { for(auto const& e:Effects)if(e.Effect==value)return true;return false; }
    bool HasAttribute(SpellAttr0 value) const{return flags&value;}
    bool HasAnyAura() const{for(auto const& e:Effects)if(e.Effect==6)return true;return false;}
    bool HasAura(int) const{return false;}
    bool IsPassive() const{return flags&64;}
    bool IsDifferentRankOf(SpellInfo const* other) const{return Id!=other->Id && root==other->root;}
    bool IsPrimaryProfessionFirstRank() const{return false;}
};
struct Aura {
    SpellInfo const* m_spellInfo=nullptr;Guid m_castItemGuid;
    SpellInfo const* GetSpellInfo() const{return m_spellInfo;}
    uint32 GetType() const{return 0;}uint32 GetCasterGUID() const{return 1;}
    Guid GetCastItemGUID() const{return m_castItemGuid;}
    bool IsPassive() const{return m_spellInfo->IsPassive();}
    bool TcStack(Aura const*) const;bool AcStack(Aura const*) const;
    bool TcStackRank(Aura const*)const;bool AcStackRank(Aura const*)const;bool IsArea()const{return false;}
    void* GetApplicationOfTarget(Guid) const{return nullptr;}
    void HandleAllEffects(void*,int,bool){}
};
struct PlayerSpell { bool Active=true;SpellState State=PLAYERSPELL_NEW;uint8 specMask=3;bool IsInSpec(uint8 spec) const{return specMask&(1<<spec);} };
using PlayerSpellMap=std::map<uint32,PlayerSpell*>;
struct PetAura {};
struct SkillLineEntry { uint32 id=770; };
struct SkillLineAbilityEntry { uint32 SkillLine=770,AcquireMethod=0,TrivialSkillLineRankHigh=0; };
using SkillLineAbilityMap=std::multimap<uint32,SkillLineAbilityEntry const*>;
using SkillLineAbilityMapBounds=std::pair<SkillLineAbilityMap::const_iterator,SkillLineAbilityMap::const_iterator>;
using SpellsRequiringSpellMap=std::multimap<uint32,uint32>;
using SpellsRequiringSpellMapBounds=std::pair<SpellsRequiringSpellMap::const_iterator,SpellsRequiringSpellMap::const_iterator>;
struct SpellLearnSkillNode { uint32 skill=0,value=0,maxvalue=0,step=0; };
struct TalentSpellPos {};
TalentSpellPos const* GetTalentSpellPos(uint32){return nullptr;}
uint32 GetTalentSpellCost(uint32){return 0;}
struct SkillStore { SkillLineEntry entry;SkillLineEntry const* LookupEntry(uint32) const{return &entry;} } sSkillLineStore;
struct SpellMgr {
    std::map<uint32,SpellInfo> spells;std::map<uint32,uint32> next,first;
    std::map<uint32,uint32> talentRanks;
    SkillLineAbilityMap abilities;SpellsRequiringSpellMap required;
    SpellInfo const* GetSpellInfo(uint32 id) const{return &spells.at(id);}
    SpellInfo const* AssertSpellInfo(uint32 id) const{return GetSpellInfo(id);}
    uint32 GetSpellWithRank(uint32 firstId,uint8 rank,bool=false) const{assert(firstId==49189);return talentRanks.at(rank);}
    static bool CheckSpellValid(SpellInfo const* info,uint32,bool){return info;}
    bool IsAdditionalTalentSpell(uint32) const{return false;}
    PetAura const* GetPetAura(uint32,uint8) const{return nullptr;}
    uint32 GetNextSpellInChain(uint32 id) const{auto it=next.find(id);return it==next.end()?0:it->second;}
    uint32 GetPrevSpellInChain(uint32 id) const{for(auto p:next)if(p.second==id)return p.first;return 0;}
    uint32 GetFirstSpellInChain(uint32 id) const{auto it=first.find(id);return it==first.end()?id:it->second;}
    SkillLineAbilityMapBounds GetSkillLineAbilityMapBounds(uint32 id) const{return abilities.equal_range(id);}
    SpellsRequiringSpellMapBounds GetSpellsRequiringSpellBounds(uint32 id) const{return required.equal_range(id);}
    SpellLearnSkillNode const* GetSpellLearnSkill(uint32) const{return nullptr;}
} manager;
SpellMgr* sSpellMgr=&manager;
struct ScriptMgr { void OnPlayerForgotSpell(void*,uint32){} } scripts;
ScriptMgr* sScriptMgr=&scripts;
struct Session { bool loading=true;bool PlayerLoading() const{return loading;} };
struct CharacterDatabasePreparedStatement { int kind;std::array<uint32,3> values{};void SetData(uint32 i,uint32 value){values[i]=value;} };
struct Transaction {
    std::map<uint32,uint32> saved;
    void Append(CharacterDatabasePreparedStatement* statement){if(statement->kind==CHAR_INS_CHAR_SPELL)saved[statement->values[1]]=statement->values[2];else saved.erase(statement->values[1]);}
};
using CharacterDatabaseTransaction=std::shared_ptr<Transaction>;
struct Database {
    std::vector<std::unique_ptr<CharacterDatabasePreparedStatement>> statements;
    CharacterDatabasePreparedStatement* GetPreparedStatement(int kind){auto p=std::make_unique<CharacterDatabasePreparedStatement>();p->kind=kind;statements.push_back(std::move(p));return statements.back().get();}
} CharacterDatabase;
struct Player;using Unit=Player;
void NurturingApply(Player*,uint32);void NurturingRemove(Player*,uint32);
struct Player {
    bool player=true;uint32 form=0;Player*ToPlayer(){return player?this:nullptr;}
    ShapeshiftForm GetShapeshiftForm()const{return form;}
    PlayerSpellMap m_spells;std::set<uint32> auras;Session session;uint8 m_activeSpec=0;bool eligible=true,tcStack=false;
    uint32 health=10000;
    uint32 GetHealth() const{return health;}uint32 CountPctFromMaxHealth(int pct) const{return 10000*pct/100;}
    ~Player(){for(auto p:m_spells)delete p.second;}
    void _addTalentAurasAndSpells(uint32);bool _addSpell(uint32,uint8,bool,bool=false,bool=true);
    void _removeTalentAurasAndSpells(uint32);void removeSpell(uint32,uint8,bool,bool=true);
    void _SaveSpells(CharacterDatabaseTransaction);
    bool IsInWorld() const{return !session.loading;}bool isBeingLoaded() const{return session.loading;}
    Session* GetSession(){return &session;}uint8 GetActiveSpec() const{return m_activeSpec;}
    Guid GetGUID() const{return Guid{1};}
    bool IsNeedCastPassiveSpellAtLearn(SpellInfo const*spellInfo)const;
    bool NativeStanceGate(SpellInfo const*spellInfo)const;
    void addSpell(uint32 id,uint8 mask,bool update,bool temp){assert(!update&&temp);_addSpell(id,mask,temp);}
    void CastSpell(Player*target,uint32 id,AuraEffect const*){CastSpell(target,id,true);}
    void CastSpell(Player*,uint32 id,bool){
        Aura added{manager.GetSpellInfo(id),{}};
        for(auto it=auras.begin();it!=auras.end();){Aura existing{manager.GetSpellInfo(*it),{}};
            if(!(tcStack?(added.TcStack(&existing)&&added.TcStackRank(&existing)):(added.AcStack(&existing)&&added.AcStackRank(&existing))))it=auras.erase(it);else ++it;}
        auras.insert(id);if(id==33872||id==33873)NurturingApply(this,id);
    }
    void RemoveOwnedAura(uint32 id){if(auras.erase(id)&&(id==33872||id==33873))NurturingRemove(this,id);}void RemoveAurasDueToSpell(uint32 id){auras.erase(id);}
    void RemovePetAura(PetAura const*){}void SendLearnPacket(uint32,bool){}
    uint32 GetFreePrimaryProfessionPoints() const{return 2;}void SetFreePrimaryProfessions(uint32){assert(false);}
    uint16 GetMaxSkillValueForLevel() const{return 400;}
    uint32 GetPureSkillValue(uint32) const{assert(false);return 0;}
    uint32 GetPureMaxSkillValue(uint32) const{assert(false);return 0;}
    void SetSkill(uint32,uint32,uint32,uint32){assert(false);}void LearnDefaultSkill(uint32,int){assert(false);}
    bool HasSkill(uint32) const{return true;}
    bool Has310Flyer(bool,uint32=0) const{return false;}void SetHas310Flyer(bool){}
    void UpdateAchievementCriteria(int,uint32){}Aura* GetAura(uint32){return nullptr;}
    bool HasAuraState(AuraStateType) const{return true;}
};
'''
methods+='\n'+function(player,'bool Player::IsNeedCastPassiveSpellAtLearn(').replace('IsNeedCastPassiveSpellAtLearn','NativeStanceGate')
methods+='\nbool Player::IsNeedCastPassiveSpellAtLearn(SpellInfo const*info)const{return eligible&&NativeStanceGate(info);}'
nurturing.append("void NurturingApply(Player*p,uint32 id){AcNurturing{p,manager.GetSpellInfo(id)}.AfterApply(nullptr,0);}")
nurturing.append("void NurturingRemove(Player*p,uint32 id){AcNurturing{p,manager.GetSpellInfo(id)}.AfterRemove(nullptr,0);}")
main=['int main(){ SkillLineAbilityEntry classAbility;']
for spell in(63680,63644,63645):
    row=data['Spell'][spell]
    main.append(f'manager.spells[{spell}].Id={spell};manager.spells[{spell}].root={spell};manager.spells[{spell}].flags={row[4]};')
    for i in range(3):main.append(f'manager.spells[{spell}].Effects[{i}]={{{row[71+i]},{row[116+i]},{row[95+i]}}};')
main.append(r"""
for(uint8 active:{0,1}){
    Player old;old.m_activeSpec=active;old.session.loading=false;
    assert(!old._addSpell(63680,3,false)&&old.m_spells.empty()&&old.auras.empty());
    Player normalized;normalized.m_activeSpec=active;normalized.session.loading=false;
    assert(normalized._addSpell(63644,3,false)&&normalized._addSpell(63645,3,false));
    assert(normalized.auras.empty()&&normalized.m_spells.size()==2);
    assert(normalized.m_spells[63644]->specMask==3&&normalized.m_spells[63645]->specMask==3);
    auto saved=std::make_shared<Transaction>();normalized._SaveSpells(saved);
    assert((saved->saved==std::map<uint32,uint32>{{63644,3},{63645,3}}));
    normalized.m_activeSpec=1-active;
    Player relog;relog.m_activeSpec=normalized.m_activeSpec;
    relog._addSpell(63644,3,false);relog._addSpell(63645,3,false);
    assert(relog.auras.empty()&&relog.m_spells.size()==2);
}
""")
for rank,(parent,helper) in enumerate(((33872,47179),(33873,47180)),1):
    main.append(f'manager.spells[{parent}].Id={parent};manager.spells[{parent}].rank={rank};manager.spells[{parent}].root=33872;')
    main.append(f'manager.spells[{helper}].Id={helper};manager.spells[{helper}].rank={rank};manager.spells[{helper}].root=47179;manager.spells[{helper}].flags=400;manager.spells[{helper}].Stances=1;')
    main.append(f'manager.spells[{helper}].Effects[0]={{6,0,118}};manager.first[{helper}]=47179;')
main.append(r"""
for(uint8 active:{0,1})for(uint32 parent:{33872,33873})for(uint32 form:{0,1,5,8}){
    uint32 child=parent==33872?47179:47180;
    Player ac;ac.m_activeSpec=active;ac.form=form;
    ac._addTalentAurasAndSpells(parent);
    assert(ac.m_spells.size()==1&&ac.m_spells.count(child));
    assert(ac.m_spells[child]->State==PLAYERSPELL_TEMPORARY);
    assert(ac.auras.count(child)==(form==1));assert(!ac.m_spells.count(child==47179?47180:47179));
    auto saved=std::make_shared<Transaction>();ac._SaveSpells(saved);assert(saved->saved.empty());
    ac._removeTalentAurasAndSpells(parent);assert(ac.auras.empty()&&ac.m_spells.empty());
    // The spec scheduler is mocked; native remove/apply/save bodies are real.
    ac.m_activeSpec=1-active;uint32 next=parent==33872?33873:33872;
    ac._addTalentAurasAndSpells(next);assert(ac.m_spells.count(next==33872?47179:47180));
    ac._removeTalentAurasAndSpells(next);assert(ac.m_spells.empty());
}
// Actual same-rank-chain exclusion: TC's lower known helper adds no stacked
// healing-received aura. Both native implementations keep one helper aura.
for(bool tc:{false,true}){Player p;p.tcStack=tc;p.CastSpell(&p,47179,true);p.CastSpell(&p,47180,true);assert(p.auras==std::set<uint32>{47180});}
assert(!manager.spells[47179].TcStackMultiSlot()&&!manager.spells[47180].AcStackMultiSlot());
Player unsafeNurturing;unsafeNurturing.session.loading=false;unsafeNurturing.form=1;unsafeNurturing._addSpell(47179,3,false);
unsafeNurturing._addTalentAurasAndSpells(33873);unsafeNurturing._removeTalentAurasAndSpells(33873);
auto savedUnsafe=std::make_shared<Transaction>();unsafeNurturing._SaveSpells(savedUnsafe);assert(savedUnsafe->saved.count(47179));
""")
for family,cls,owners,children in fixtures.NATIVE_PASSIVE_TALENTS:
    for owner in owners:
        row=data['Spell'][owner]
        main.append(f'manager.spells[{owner}].Id={owner};manager.spells[{owner}].root={owner};')
        for i in range(3):
            main.append(f'manager.spells[{owner}].Effects[{i}]={{{row[71+i]},{row[116+i]},{row[95+i]}}};')
for chain in fixtures.NATIVE_PASSIVE_CHAINS:
    for index,child in enumerate(chain):
        row=data['Spell'][child]
        main.append(f'manager.spells[{child}].Id={child};manager.spells[{child}].root={chain[0]};manager.first[{child}]={chain[0]};')
        main.append(f'manager.spells[{child}].CasterAuraState={row[20]};manager.abilities.emplace({child},&classAbility);')
        for i in range(3):
            main.append(f'manager.spells[{child}].Effects[{i}]={{{row[71+i]},{row[116+i]},{row[95+i]}}};')
        if index+1<len(chain):main.append(f'manager.next[{child}]={chain[index+1]};')
for family,cls,owners,children in fixtures.NATIVE_PASSIVE_TALENTS:
    for owner,learned in zip(owners,children):
        main.append('{Player tc,ac;tc.tcStack=true;')
        for child in learned:
            chain=next(chain for chain in fixtures.NATIVE_PASSIVE_CHAINS if child in chain)
            for rank in chain[:chain.index(child)+1]:main.append(f'tc.CastSpell(&tc,{rank},true);')
        expected='{'+','.join(map(str,learned))+'}'
        main.append(f'ac._addTalentAurasAndSpells({owner});assert((ac.auras==std::set<uint32>{expected}));assert(tc.auras==ac.auras);')
        main.append('auto trans=std::make_shared<Transaction>();ac._SaveSpells(trans);assert(trans->saved.empty());')
        main.append(f'ac._removeTalentAurasAndSpells({owner});assert(ac.m_spells.empty() && ac.auras.empty());')
        main.append(f'ac.session.loading=false;ac.m_activeSpec=1;ac._addTalentAurasAndSpells({owner});ac._SaveSpells(trans);assert(trans->saved.empty());')
        main.append(f'ac._removeTalentAurasAndSpells({owner});assert(ac.m_spells.empty() && ac.auras.empty());')
        main.append(f'Player relog;relog._addTalentAurasAndSpells({owner});assert((relog.auras==std::set<uint32>{expected}));')
        main.append(f'Player gated;gated.eligible=false;gated._addTalentAurasAndSpells({owner});assert(gated.auras.empty());assert(gated.m_spells.size()=={len(learned)});}}')
main.append(r'''
// Mixed ranks in two specs: native removal, re-addition, save and relog.
Player switched;
for(uint32 owner:{37117,37116,37117,37116}){
    switched._addTalentAurasAndSpells(owner);
    auto saved=std::make_shared<Transaction>();switched._SaveSpells(saved);assert(saved->saved.empty());
    switched._removeTalentAurasAndSpells(owner);assert(switched.m_spells.empty() && switched.auras.empty());
    switched.m_activeSpec=1-switched.m_activeSpec;switched.session.loading=false;
}
// Persistent-row negative control: temporary-only removal must not delete it.
Player persistent;persistent.m_spells[16958]=new PlayerSpell{true,PLAYERSPELL_UNCHANGED,3};
persistent.removeSpell(16958,3,true);assert(persistent.m_spells.count(16958));
// A persisted predecessor outlives talent ownership and returns on relog.
Player unsafe;unsafe.session.loading=false;unsafe._addSpell(16958,3,false);
unsafe._addTalentAurasAndSpells(37117);unsafe._removeTalentAurasAndSpells(37117);
assert(unsafe.m_spells.count(16958));
auto leaked=std::make_shared<Transaction>();unsafe._SaveSpells(leaked);assert(leaked->saved.count(16958));
Player leakedRelog;leakedRelog._addSpell(16958,3,false);assert(leakedRelog.auras.count(16958));
// Native Will of the Necropolis uses the exact aura rank and catalog parent,
// without consulting lower known-spell entries.
for(uint32 rank=1;rank<=3;++rank){
    uint32 child=52283+rank;
    uint32 parent=rank==1?49189:rank==2?50149:50150;
    manager.talentRanks[rank]=parent;manager.spells[child].rank=rank;
    manager.spells[child].Effects[0].amount=rank*5;manager.spells[parent].Effects[0].amount=35;
    for(auto sample:std::vector<std::pair<uint32,uint32>>{{10000,7000},{10000,1000},{3000,1000},{10000,6500},{10000,6501}}){
        Player caster;caster.health=sample.first;
        WillTc tc{&caster,manager.GetSpellInfo(child)};WillAc ac{&caster,manager.GetSpellInfo(child)};
        assert(tc.Load() && ac.Load());int32 a=0,b=0;bool recalc=false;
        tc.CalculateAmount(nullptr,a,recalc);ac.CalculateAmount(nullptr,b,recalc);assert(a==-1 && a==b);
        DamageInfo damage{sample.second};uint32 left=0,right=0;
        tc.Absorb(nullptr,damage,left);ac.Absorb(nullptr,damage,right);assert(left==right);
        uint32 expected=sample.first-sample.second<3500?sample.second*rank*5/100:0;
        assert(left==expected);
    }
}
std::cout << "Protected native passive/Nurturing consumers passed: canonical exact auras, temporary add/remove/save/stance, spec scheduling/relog and persistent-row refusal; state/DB/aura sinks mocked; gameplay NOT TESTED\n";
}''')
with tempfile.TemporaryDirectory() as directory:
    cpp,binary=Path(directory)/'passive.cpp',Path(directory)/'passive'
    cpp.write_text(mock+'\n'+'\n'.join(stack)+'\n'+methods+'\n'+'\n'.join(callbacks)+'\n'+'\n'.join(nurturing)+'\n'+'\n'.join(main))
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
