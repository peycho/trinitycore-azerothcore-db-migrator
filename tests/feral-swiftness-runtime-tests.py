#!/usr/bin/env python3
"""Protected TC dependency/stance loops and AC talent/stance/aura callbacks.

State stores, aura dispatch, spec scheduling and persistence sinks are mocked.
This verifies the native consumers, not complete worldserver gameplay.
"""
from pathlib import Path
import re
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
tc_player = (tc/'src/server/game/Entities/Player/Player.cpp').read_text()
ac_player = (ac/'src/server/game/Entities/Player/Player.cpp').read_text()
script = (ac/'src/server/scripts/Spells/spell_druid.cpp').read_text()
for constant, spell in [('R1',17002),('R2',24866),('PASSIVE_1',24867),('PASSIVE_2',24864)]:
    assert re.search(rf'SPELL_DRUID_FERAL_SWIFTNESS_{constant}\s*=\s*{spell}',script)
script = script[script.index('class spell_dru_feral_swiftness :'):]
apply, remove = body(script,'void AfterApply('), body(script,'void AfterRemove(')
registration = body(script,'void Register() override')
assert 'EFFECT_0, SPELL_AURA_ANY, AURA_EFFECT_HANDLE_REAL' in registration
assert 'AfterEffectApply' in registration and 'AfterEffectRemove' in registration
start = tc_player.index('// learn dependent spells',tc_player.index('bool Player::AddSpell('))
dependency = tc_player[start:tc_player.index('if (!GetSession()->PlayerLoading())',start)]
tc_shape = (tc/'src/server/game/Spells/Auras/SpellAuraEffects.cpp').read_text()
tc_shape = tc_shape[tc_shape.index('void AuraEffect::HandleShapeshiftBoosts('):]
tc_loop = tc_shape[tc_shape.index('PlayerSpellMap const& sp_list'):tc_shape.index('// Also do it for Glyphs')]
ac_shape = (ac/'src/server/game/Spells/Auras/SpellAuraEffects.cpp').read_text()
ac_shape = ac_shape[ac_shape.index('void AuraEffect::HandleShapeshiftBoosts('):]
ac_loop = ac_shape[ac_shape.index('PlayerTalentMap const& tl_list'):ac_shape.index('// Also do it for Glyphs')]
mock = r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <vector>
using uint8=uint8_t;using uint32=uint32_t;using uint64=uint64_t;
using AuraEffectHandleModes=uint32;
#define UI64LIT(x) x##ULL
constexpr uint32 SPELL_DRUID_FERAL_SWIFTNESS_R1=17002,SPELL_DRUID_FERAL_SWIFTNESS_R2=24866;
constexpr uint32 SPELL_DRUID_FERAL_SWIFTNESS_PASSIVE_1=24867,SPELL_DRUID_FERAL_SWIFTNESS_PASSIVE_2=24864;
constexpr int MAX_SPELL_EFFECTS=3,SPELL_EFFECT_LEARN_SPELL=36,SPEC_MASK_ALL=3;
enum SpellAttr0 {SPELL_ATTR0_PASSIVE=64,SPELL_ATTR0_DO_NOT_DISPLAY=128,SPELL_ATTR0_HIDDEN_CLIENTSIDE=128};
enum SpellAttr2 {SPELL_ATTR2_ALLOW_WHILE_NOT_SHAPESHIFTED=1};
enum SpellState {PLAYERSPELL_UNCHANGED,PLAYERSPELL_REMOVED};
using ShapeshiftForm=uint32;
struct SpellInfo {
 uint32 Id=0,Stances=0,flags=0;
 struct Effect {uint32 Effect=0,TriggerSpell=0;} Effects[3]{};
 bool IsPassive()const{return flags&64;}
 bool HasAttribute(SpellAttr0 flag)const{return flags&flag;}
 bool HasAttribute(SpellAttr2)const{return false;}
 bool HasEffect(uint32 kind)const{for(auto const&e:Effects)if(e.Effect==kind)return true;return false;}
};
struct SpellLearnSpellNode {uint32 Spell=0;bool Active=false,AutoLearned=false;};
using SpellLearnSpellMap=std::multimap<uint32,SpellLearnSpellNode>;
using SpellLearnSpellMapBounds=std::pair<SpellLearnSpellMap::const_iterator,SpellLearnSpellMap::const_iterator>;
struct SpellMgr {
 SpellLearnSpellMap rows;std::map<uint32,SpellInfo> infos;
 SpellLearnSpellMapBounds GetSpellLearnSpellMapBounds(uint32 id)const{return rows.equal_range(id);}
 SpellInfo const*GetSpellInfo(uint32 id)const{auto it=infos.find(id);return it==infos.end()?nullptr:&it->second;}
 bool IsAdditionalTalentSpell(uint32)const{return false;}
} manager;SpellMgr*sSpellMgr=&manager;
struct PlayerSpell {SpellState state=PLAYERSPELL_UNCHANGED;bool disabled=false,active=false;};
struct PlayerTalent {SpellState State=PLAYERSPELL_UNCHANGED;uint8 mask=0;bool IsInSpec(uint8 spec)const{return mask&(1<<spec);}};
using PlayerSpellMap=std::map<uint32,PlayerSpell>;
using PlayerTalentMap=std::map<uint32,PlayerTalent*>;
struct AuraEffect {};
struct Player;
void OnFeralApply(Player*,AuraEffect const*);
struct Player {
 bool player=true,ac=false;uint8 active=0;uint32 form=0,slots=2;
 PlayerSpellMap spells;PlayerTalentMap talents;std::set<uint32>auras;
 std::vector<uint32> casts,removed,learned;std::map<uint32,uint32>skills{{134,400},{171,320},{762,300}};
 ~Player(){for(auto const&entry:talents)delete entry.second;}
 Player*ToPlayer(){return player?this:nullptr;}
 uint8 GetActiveSpec()const{return active;}uint32 GetGUID()const{return 1;}
 ShapeshiftForm GetShapeshiftForm()const{return form;}
 bool HasTalent(uint32 id,uint8 spec)const {auto it=talents.find(id);return it!=talents.end()&&it->second->State!=PLAYERSPELL_REMOVED&&it->second->IsInSpec(spec);}
 PlayerSpellMap const&GetSpellMap()const{return spells;}
 PlayerTalentMap const&GetTalentMap()const{return talents;}
 bool IsInWorld()const{return false;}
 void AddSpell(uint32 id,bool activeFlag,bool learning,bool dependent,bool disabledFlag){
  assert(!activeFlag&&learning&&dependent&&!disabledFlag);spells[id]={PLAYERSPELL_UNCHANGED,false,false};learned.push_back(id);
 }
 void LearnSpell(uint32,bool){assert(false);}
 void CastSpell(Player*,uint32 id,AuraEffect const*){casts.push_back(id);auras.insert(id);}
 void CastSpell(Player*,uint32 id,bool,void* =nullptr,AuraEffect const*effect=nullptr,uint32=0){
  casts.push_back(id);auras.insert(id);
  if(ac&&(id==17002||id==24866))OnFeralApply(this,effect);
 }
 void RemoveAurasDueToSpell(uint32 id){removed.push_back(id);auras.erase(id);}
 void _addSpell(uint32,uint8,bool){assert(false);}
 bool IsNeedCastPassiveSpellAtLearn(SpellInfo const*)const;
 void AddTalentAuras(uint32);void RestoreTc(uint32 spellId);
};
using Unit=Player;
struct Feral {
 Player*player;Player*GetTarget(){return player;}uint32 GetCasterGUID()const{return 1;}
 void Apply(AuraEffect const*aurEff,AuraEffectHandleModes);
 void Remove(AuraEffect const*,AuraEffectHandleModes);
};
void OnFeralApply(Player*p,AuraEffect const*effect){Feral{p}.Apply(effect,0);}
struct Shape:AuraEffect {
 uint32 form;uint32 GetMiscValue()const{return form;}
 void Tc(Player*plrTarget){Player*target=plrTarget;uint32 spellId=0,spellId2=0;
'''
mock += tc_loop + '}\n void Ac(Player*player){Player*target=player;uint32 spellId=0,spellId2=0;\n' + ac_loop + '}\n};\n'
mock += ('void Feral::Apply(AuraEffect const*aurEff,AuraEffectHandleModes)'+apply+
         '\nvoid Feral::Remove(AuraEffect const*,AuraEffectHandleModes)'+remove+
         '\nbool Player::IsNeedCastPassiveSpellAtLearn(SpellInfo const*spellInfo)const'+
         body(ac_player,'bool Player::IsNeedCastPassiveSpellAtLearn(')+
         '\nvoid Player::AddTalentAuras(uint32 spellId)'+body(ac_player,'void Player::_addTalentAurasAndSpells(')+
         '\nvoid Player::RestoreTc(uint32 spellId){'+dependency+'}\n')
mock += r'''
int main(){
 manager.infos[17002]=SpellInfo{17002,1,464};manager.infos[24866]=SpellInfo{24866,1,464};
 manager.infos[24867]=SpellInfo{24867,145,128};manager.infos[24864]=SpellInfo{24864,145,128};
 manager.rows.emplace(17002,SpellLearnSpellNode{24867,false,false});
 manager.rows.emplace(24866,SpellLearnSpellNode{24864,false,false});
 for(uint8 active:{0,1})for(uint32 selected:{17002,24866}){
  uint32 helper=selected==17002?24867:24864,other=selected==17002?24866:17002;
  Player tc,ac;tc.active=ac.active=active;ac.ac=true;
  ac.talents[selected]=new PlayerTalent{PLAYERSPELL_UNCHANGED,uint8(1<<active)};
  ac.talents[other]=new PlayerTalent{PLAYERSPELL_UNCHANGED,uint8(1<<(1-active))};
  tc.spells[selected]={PLAYERSPELL_UNCHANGED,false,true};
  tc.spells[other]={PLAYERSPELL_UNCHANGED,true,true};
  tc.RestoreTc(selected);assert(tc.learned==std::vector<uint32>{helper});
  assert(!tc.spells[helper].active&&!tc.spells[helper].disabled);
  auto skills=ac.skills;auto talentCount=ac.talents.size();
  // Loading out of form does not cast the stance-restricted Cat talent.
  ac.AddTalentAuras(selected);assert(ac.auras.empty()&&ac.spells.empty());
  for(uint32 form:{1,5,8}){
   tc.form=ac.form=form;Shape shape;shape.form=form;
   shape.Tc(&tc);shape.Ac(&ac);
   // Native Bear form bindings supply the callback; Cat uses the talent loop.
   if(form==5||form==8)Feral{&ac}.Apply(&shape,0);
   assert(tc.auras.count(helper)&&ac.auras.count(helper));
   assert(!ac.auras.count(other==17002?24867:24864));
   Feral{&ac}.Remove(&shape,0);assert(!ac.auras.count(24867)&&!ac.auras.count(24864));
   tc.auras.clear();ac.auras.clear();
  }
  assert(ac.spells.empty()&&ac.learned.empty()&&ac.skills==skills&&ac.slots==2&&ac.talents.size()==talentCount);
  // After a spec switch/relog, only the newly active exact rank is cast.
  ac.active=1-active;ac.form=1;ac.AddTalentAuras(other);
  assert(ac.auras.count(other==17002?24867:24864));assert(!ac.auras.count(helper));
 }
 Player none;none.ac=true;Feral{&none}.Apply(nullptr,0);assert(none.casts.empty());
 none.player=false;Feral{&none}.Apply(nullptr,0);assert(none.casts.empty());
 Player inactive;inactive.ac=true;inactive.talents[24866]=new PlayerTalent{PLAYERSPELL_UNCHANGED,2};
 Feral{&inactive}.Apply(nullptr,0);assert(inactive.casts.empty());
 Player removed;removed.ac=true;removed.talents[24866]=new PlayerTalent{PLAYERSPELL_REMOVED,1};
 Feral{&removed}.Apply(nullptr,0);assert(removed.casts.empty());
 std::cout<<"Protected Feral Swiftness TC dependency/stance and AC talent/stance/apply/remove bodies PASS; both ranks/specs, Cat/Bear/Dire Bear, no ownership/skill/spellbook grants; sinks mocked, gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory)/'feral.cpp', Path(directory)/'feral'
    cpp.write_text(mock)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
