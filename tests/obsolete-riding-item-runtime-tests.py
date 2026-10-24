#!/usr/bin/env python3
"""Exercise protected item template gates; never run native deletion paths."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
tc,ac = map(Path,sys.argv[1:])
rules = json.loads((ROOT/'lib/cleanup_obsolete_riding_item_catalog.json').read_text())

def body(text,marker):
    start=text.index('{',text.index(marker)); end=start+1; depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}'); end+=1
    return text[start:end]

methods = ''
for core,path in (('tc',tc),('ac',ac)):
    files = {}
    for name,expected in rules['native_sources'][core].items():
        raw=(path/name).read_bytes(); assert hashlib.sha256(raw).hexdigest()==expected
        files[Path(name).name]=raw.decode()
    for statement in ('CHAR_SEL_CHARACTER_INVENTORY','CHAR_SEL_MAILITEMS'):
        source=files['CharacterDatabase.cpp']
        start=source.index('PrepareStatement('+statement+',')
        end=source.index('CONNECTION_',start)
        query=''.join(json.loads(s) for s in re.findall(r'"(?:[^"\\]|\\.)*"',source[start:end]))
        if statement=='CHAR_SEL_CHARACTER_INVENTORY':
            assert 'FROM character_inventory ci JOIN item_instance ii ON ci.item = ii.guid' in query
        else:
            assert 'LEFT JOIN item_instance ii ON mi.item_guid = ii.guid' in query and 'WHERE m.receiver = ?' in query
    # This exact prefix returns false before reading instance fields or owner
    # state when GetTemplate() is null. Later native login cleanup is not run.
    prefix=body(files['Item.cpp'],'bool Item::LoadFromDB(').split('    // set owner',1)[0]
    assert 'if (!proto)' in prefix and 'return false;' in prefix
    methods+='\nbool Item::'+core.capitalize()+'Load(uint32 guid,uint32 entry)'+prefix+'++accepted;return true;}\n'

mock=r'''
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
using uint32=uint32_t;using uint64=uint64_t;
enum class HighGuid{Item};
struct ObjectGuid{template<HighGuid>static uint64 Create(uint32 guid){return guid;}};
struct Object{void _Create(uint64){}void _Create(uint32,uint32,HighGuid){}};
struct ItemTemplate{uint32 RequiredSkill=0,RequiredSpell=0;};
std::map<uint32,ItemTemplate> templates;
#define TC_LOG_ERROR(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
struct Item:Object{
 uint32 id=0;int accepted=0;
 void SetEntry(uint32 entry){id=entry;}void SetObjectScale(float){}
 ItemTemplate const*GetTemplate()const{auto i=templates.find(id);return i==templates.end()?nullptr:&i->second;}
 bool TcLoad(uint32 guid,uint32 entry);bool AcLoad(uint32 guid,uint32 entry);
};
'''
main=r'''
int main(){
 templates[1234]={149,825};
 Item t,a;assert(!t.TcLoad(1,0));assert(!a.AcLoad(1,0));assert(t.accepted==0&&a.accepted==0);
 assert(t.TcLoad(1,1234));assert(a.AcLoad(1,1234));assert(t.accepted==1&&a.accepted==1);
 assert(t.GetTemplate()->RequiredSkill==149&&a.GetTemplate()->RequiredSpell==825);
 // Unknown nonzero entries are intentionally NOT authorized by the policy.
 assert(!t.TcLoad(1,777777));assert(!a.AcLoad(1,777777));
 // If a custom world defines zero, native loading could accept it: v2's
 // explicit zero-template absence guard is necessary, not an assumption.
 templates[0]={149,825};assert(t.TcLoad(1,0));assert(a.AcLoad(1,0));
 std::cout<<"PASS protected TC/AC item-load template gates and inventory/mail query joins; undefined zero rejected before instance-field access, real legacy requirements retained, custom zero control demonstrates mandatory zero-template guard. Gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory() as d:
    cpp,exe=Path(d)/'items.cpp',Path(d)/'items'
    cpp.write_text(mock+methods+main)
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
