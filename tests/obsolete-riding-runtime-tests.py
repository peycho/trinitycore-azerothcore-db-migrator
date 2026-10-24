#!/usr/bin/env python3
"""Compile protected skill lookup and load consumers.

Recording sinks verify retirement of forbidden 149, preservation of modern
Riding caps, and the eligible Orc control. This is not a full worldserver login.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
tc,ac = map(Path,sys.argv[1:])
rules = json.loads((ROOT/'lib/cleanup_obsolete_riding_catalog.json').read_text())

def body(text,marker):
    start = text.index('{',text.index(marker)); end = start+1; depth = 1
    while depth:
        depth += (text[end]=='{')-(text[end]=='}'); end += 1
    return text[start:end]

sources = {}
for core,path in (('tc',tc),('ac',ac)):
    sources[core] = {}
    for name,expected in rules['native_sources'][core].items():
        raw = (path/name).read_bytes(); assert hashlib.sha256(raw).hexdigest() == expected
        sources[core][Path(name).name] = raw.decode()

mock = r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <utility>
using uint8=uint8_t; using uint16=uint16_t; using uint32=uint32_t;
struct SkillRaceClassInfoEntry {uint32 SkillID,RaceMask,ClassMask,Flags,SkillTierID;};
using SkillRaceClassInfoMap=std::multimap<uint32,SkillRaceClassInfoEntry const*>;
using SkillRaceClassInfoBounds=std::pair<SkillRaceClassInfoMap::iterator,SkillRaceClassInfoMap::iterator>;
SkillRaceClassInfoMap SkillRaceClassInfoBySkill;
constexpr uint32 SKILL_RUNEFORGING=776,SKILL_CATEGORY_ARMOR=8,SKILL_CATEGORY_LANGUAGES=10;
enum SkillRangeType {SKILL_RANGE_NONE,SKILL_RANGE_LANGUAGE,SKILL_RANGE_LEVEL,SKILL_RANGE_MONO,SKILL_RANGE_RANK};
struct SkillLineEntry {uint32 id=149,CategoryID=0,categoryId=0;};
struct SkillLines {SkillLineEntry line;SkillLineEntry const* LookupEntry(uint32){return &line;}}sSkillLineStore;
struct Tiers {void const* LookupEntry(uint32 id){return id==223?this:nullptr;}}sSkillTiersStore;
enum {SKILL_DELETED};
struct SkillStatusData {SkillStatusData(uint32,int){}};
using SkillStatusMap=std::map<uint32,SkillStatusData>;
#define LOG_ERROR(...) ((void)0)
#define TC_LOG_ERROR(...) ((void)0)
struct Guid {uint32 GetCounter()const{return 1;}auto ToString()const{return "fixture";}};
struct Loader {
 uint8 race=10,cls=5;uint16 level=80;SkillStatusMap mSkillStatus;
 uint8 getRace()const{return race;}uint8 GetRace()const{return race;}
 uint8 getClass()const{return cls;}uint8 GetClass()const{return cls;}
 Guid GetGUID()const{return {};}auto GetName()const{return "fixture";}
 uint16 GetMaxSkillValueForLevel()const{return level*5;}
 bool TcLoad(uint16 skill,uint16& value,uint16& max);
 bool AcLoad(uint16 skill,uint16& value,uint16& max);
};
'''
methods = ''
for core in ('tc','ac'):
    title = core.capitalize()
    methods += '\nSkillRaceClassInfoEntry const* '+title+'Info(uint32 skill,uint8 race,uint8 class_)'+body(sources[core]['DBCStores.cpp'],'SkillRaceClassInfoEntry const* GetSkillRaceClassInfo(')
    methods += '\nSkillRangeType '+title+'Range(SkillRaceClassInfoEntry const* rcEntry)'+body(sources[core]['ObjectMgr.cpp'],'SkillRangeType GetSkillRangeType(')
    load = body(sources[core]['Player.cpp'],'void Player::_LoadSkills(')
    start = load.index('            SkillRaceClassInfoEntry const* rcEntry')
    end = load.index('\n\n            if (value == 0)',start)
    # The original continue skips loading the forbidden row. The recording
    # wrapper has one row, so returning false records precisely that branch.
    fragment = load[start:end].replace('continue;','return false;')
    fragment = fragment.replace('GetSkillRaceClassInfo(',title+'Info(').replace('GetSkillRangeType(',title+'Range(')
    methods += '\nbool Loader::'+title+'Load(uint16 skill,uint16& value,uint16& max){'+fragment+'return true;}\n'

data = ''
for core in ('tc','ac'):
    rows = rules[core]['skills']['149']['infos']+rules[core]['skills']['762']['infos']
    data += '\nvoid '+core+'Rows(){SkillRaceClassInfoBySkill.clear();'
    for i,r in enumerate(rows):
        data += f'static SkillRaceClassInfoEntry r{i}{{{r[1]},{r[2]}u,{r[3]}u,{r[4]},{r[6]}}};SkillRaceClassInfoBySkill.emplace({r[1]},&r{i});'
    data += '}\n'

main = r'''
int main(){
 for(uint8 race:{10,11})for(uint8 cls:{5,6,7})for(uint16 cap:{225,300}){
  tcRows();Loader t;t.race=race;t.cls=cls;uint16 old=1,oldmax=75,value=cap,max=cap;
  assert(!t.TcLoad(149,old,oldmax));assert(t.mSkillStatus.count(149)==1);
  assert(t.TcLoad(762,value,max));assert(value==cap&&max==cap);
  acRows();Loader a;a.race=race;a.cls=cls;value=max=cap;
  assert(!a.AcLoad(149,old,oldmax));assert(a.mSkillStatus.count(149)==1);
  assert(a.AcLoad(762,value,max));assert(value==cap&&max==cap);
 }
 tcRows();assert(TcInfo(149,2,1)!=nullptr);
 acRows();assert(AcInfo(149,2,1)!=nullptr);
 std::cout<<"PASS protected TC/AC skill lookup and load fragments: forbidden Wolf Riding 149 is skipped/marked deleted, modern Riding 762 stays 225/225 or 300/300; eligible Orc control retained. Recording sinks; gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory() as d:
    cpp,exe = Path(d)/'riding.cpp',Path(d)/'riding'
    cpp.write_text(mock+methods+data+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-implicit-fallthrough',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
