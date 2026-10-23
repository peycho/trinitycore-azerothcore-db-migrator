#!/usr/bin/env python3
"""Protected skill-effect, trainer and quest consumers with mocked state; no gameplay."""
from pathlib import Path
import ast,hashlib,json,subprocess,tempfile,sys
ROOT=Path(__file__).resolve().parents[1]
tc,ac=map(Path,sys.argv[1:])

def body(s,marker):
 start=s.index('{',s.index(marker));end=start+1;depth=1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[start:end]

methods=[];proofs={}
for core,repo,prefix in [('tc',tc,'trinitycore'),('ac',ac,'azerothcore')]:
 manifest=dict((n.strip().lstrip('*'),h)for h,n in(line.split(None,1)for line in(ROOT/'compatibility/tc335-acwotlk-v2'/f'{prefix}-semantic.sha256').read_text().splitlines()))
 name='src/server/game/Spells/SpellEffects.cpp';raw=(repo/name).read_bytes();checksum=hashlib.sha256(raw).hexdigest();assert checksum==manifest[name]
 methods.append(('void Spell::Tc()'if core=='tc'else'void Spell::Ac(SpellEffIndex effIndex)')+body(raw.decode(),'void Spell::EffectLearnSkill('));proofs[core]=checksum
mock=r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
using uint16=uint16_t;using uint32=uint32_t;using SpellEffIndex=int;
constexpr int SPELL_EFFECT_HANDLE_HIT_TARGET=1,TYPEID_PLAYER=4;
struct SkillRaceClassInfoEntry{uint32 SkillTierID=1;}info;
bool eligible=true;
SkillRaceClassInfoEntry const*GetSkillRaceClassInfo(uint32,uint32,uint32){return eligible?&info:nullptr;}
struct SkillTiersEntry{uint16 Value[16]{75,150,225,300,375,450};}tier;
struct Tiers{SkillTiersEntry const*LookupEntry(uint32){return &tier;}}sSkillTiersStore;
struct Player{uint16 value=1,cap=450;int calls=0;
 uint32 GetTypeId(){return TYPEID_PLAYER;}bool IsPlayer(){return true;}uint32 GetRace(){return 1;}uint32 GetClass(){return 9;}
 Player*ToPlayer(){return this;}uint16 GetPureSkillValue(uint32){return value;}
 void SetSkill(uint32,uint16,uint16 v,uint16 m){value=v;cap=m;++calls;}
};
struct Effect{uint32 MiscValue=129;uint16 step=4;uint16 CalcValue(){return step;}}effect;
struct Info{Effect Effects[3];}spellInfo;
struct Spell{int effectHandleMode=1,damage=4;Player player;Player*unitTarget=&player;
 Effect*effectInfo=&effect;Info*m_spellInfo=&spellInfo;void Tc();void Ac(SpellEffIndex effIndex);};
'''
cases=[{'stored_skill':[v,c],'rank':step,'skill':skill,'tc_cast_cap':native,'ac_cast_cap':native}for skill,v,c,step,native in [(129,1,375,4,300),(129,450,450,4,300),(762,75,75,1,75),(762,150,150,1,75),(762,300,300,1,75),(755,450,450,6,450)]];checks=[]
for i,r in enumerate(cases):
 v,cap=r['stored_skill'];rank=r['rank'];skill=r['skill'];native=r['tc_cast_cap'];assert native==r['ac_cast_cap']
 checks.append(f'''{{Spell tc,ac;tc.player.value=ac.player.value={v};tc.player.cap=ac.player.cap={cap};tc.damage=ac.damage={rank};effect.MiscValue=spellInfo.Effects[0].MiscValue={skill};effect.step=spellInfo.Effects[0].step={rank};tc.Tc();ac.Ac(0);assert(tc.player.value=={v}&&ac.player.value=={v});assert(tc.player.cap=={native}&&ac.player.cap=={native});assert(tc.player.calls==1&&ac.player.calls==1);}}''')
main='int main(){'+''.join(checks)+'''Spell untouched;untouched.effectHandleMode=0;untouched.Tc();untouched.Ac(0);assert(untouched.player.calls==0);std::cout<<"PASS protected TC/AC EffectLearnSkill bodies: reviewed cases request matching caps 300/75/450, preserve current values, and honor effect mode; recording skill setters only, gameplay NOT TESTED\\n";}'''
with tempfile.TemporaryDirectory()as d:
 cpp=Path(d)/'native.cpp';exe=Path(d)/'native';cpp.write_text(mock+'\n'.join(methods)+main)
 subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)

# Reuse the existing trainer mock declarations, then compile the exact protected
# trainer function and quest learned-child gates against retained child books.
module=ast.parse((ROOT/'tests/trainer-spell-tests.py').read_text())
trainer_mock=ast.literal_eval(next(node.value for node in module.body if isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='mock'for t in node.targets)))
trainer_mock=trainer_mock.replace('using uint32=uint32_t;', 'using uint8=uint8_t;using uint32=uint32_t;')
trainer_mock=trainer_mock.replace('int effect;','int Effect;').replace('return effect==value;','return Effect==value;')
trainer_mock=trainer_mock.replace('std::vector<SpellEffectInfo> effects;', 'std::vector<SpellEffectInfo> Effects=std::vector<SpellEffectInfo>(3);')
trainer_mock=trainer_mock.replace('return effects;', 'return Effects;')
trainer_mock=trainer_mock.replace('SpellInfo const* AssertSpellInfo', 'SpellInfo const* GetSpellInfo(uint32 id){return &spells[id];}\n    SpellInfo const* AssertSpellInfo')
trainer_mock=trainer_mock.replace('uint32 GetLevel() const { return 80; }', 'uint32 GetLevel() const { return 80; }\n    int questCasts=0;void TcQuest(uint32);void AcQuest(uint32);')
trainer_mock+='\nconstexpr uint8 MAX_SPELL_EFFECTS=3;constexpr int SPELL_EFFECT_TRADE_SKILL=47;\n'
manifest=dict((n.strip().lstrip('*'),h)for h,n in(line.split(None,1)for line in(ROOT/'compatibility/tc335-acwotlk-v2/azerothcore-semantic.sha256').read_text().splitlines()))
file='src/server/game/Entities/Creature/Trainer.cpp';raw=(ac/file).read_bytes();assert hashlib.sha256(raw).hexdigest()==manifest[file]
trainer='SpellState Trainer::GetDefaultSpellState(Player const* player,Spell const* trainerSpell) const'+body(raw.decode(),'SpellState Trainer::GetDefaultSpellState(')
quest=''
for core,path,prefix,marker in [('Tc',tc,'trinitycore','void Player::LearnQuestRewardedSpells(Quest const* quest)'),('Ac',ac,'azerothcore','void Player::learnQuestRewardedSpells(Quest const* quest)')]:
    file='src/server/game/Entities/Player/Player.cpp';raw=(path/file).read_bytes()
    hashes=dict((n.strip().lstrip('*'),h)for h,n in(line.split(None,1)for line in(ROOT/'compatibility/tc335-acwotlk-v2'/f'{prefix}-semantic.sha256').read_text().splitlines()))
    assert hashlib.sha256(raw).hexdigest()==hashes[file]
    text=body(raw.decode(),marker);start=text.index('    bool found = false;');end=text.index('    if (!found)',start);end=text.index(';',end)+1
    fragment=text[start:end]
    quest+='void Player::'+core+'Quest(uint32 id){auto spellInfo=sSpellMgr->GetSpellInfo(id);'+fragment+'\n    ++questCasts;}\n'
rules=json.loads((ROOT/'lib/cleanup_skill_teaching_catalog.json').read_text())
lines=['int main(){Trainer trainer;']
for teacher,rule in rules['wrappers'].items():
    effects=[f'{{36,{s}}}'for s in rule['children']]+['{44,0}']
    effects+=['{0,0}']*(3-len(effects))
    lines.append('manager.spells['+teacher+'].Effects={'+','.join(effects)+'};')
    for child in rule['children']:
        chain=rules['ac'][str(child)]['chain']
        for prev,spell in zip(chain,chain[1:]):lines.append(f'manager.previous[{spell}]={prev};')
    lines.append('for(uint32 spec:{0,1}){Player player;player.spec=spec;')
    for child in rule['children']:
        for spell in rules['ac'][str(child)]['chain']:lines.append(f'player.spells[{spell}]=3;manager.spells[{spell}];')
    lines.append(f'Trainer::Spell wrapper{{{teacher}}};assert(!player.HasSpell({teacher}));assert(trainer.GetDefaultSpellState(&player,&wrapper)==SpellState::Known);')
    for child in rule['children']:lines.append(f'{{Trainer::Spell direct{{{child}}};assert(trainer.GetDefaultSpellState(&player,&direct)==SpellState::Known);}}')
    lines.append(f'player.TcQuest({teacher});player.AcQuest({teacher});assert(player.questCasts==0);')
    lines.append(f'player.spells.erase({rule["children"][0]});assert(trainer.GetDefaultSpellState(&player,&wrapper)!=SpellState::Known);'+'}')
lines.append('std::cout<<"PASS protected AC direct/wrapped trainer and TC/AC quest known-child gates: known children remain learned without stored wrappers; incomplete children remain non-known; no quest recast with all children known. Mocked state; gameplay NOT TESTED\\n";}')
with tempfile.TemporaryDirectory()as d:
    cpp=Path(d)/'trainer.cpp';exe=Path(d)/'trainer';cpp.write_text(trainer_mock+trainer+quest+'\n'.join(lines))
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
