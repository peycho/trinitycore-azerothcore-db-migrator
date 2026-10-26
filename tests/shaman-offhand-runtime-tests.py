#!/usr/bin/env python3
"""Execute the pinned native off-hand decision gates; no login/gameplay claim."""
from pathlib import Path
import hashlib,subprocess,sys,tempfile,re
ROOT=Path(__file__).resolve().parents[1]
def body(text,marker):
 start=text.index('{',text.index(marker));end=start+1;depth=1
 while depth:
  depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]
methods=''
for core,path in zip(('trinitycore','azerothcore'),map(Path,sys.argv[1:])):
 manifest={n.strip():h for h,n in(line.split(None,1)for line in(ROOT/'compatibility/tc335-acwotlk-v2'/f'{core}-semantic.sha256').read_text().splitlines())}
 files={}
 for name in('src/server/game/Entities/Player/Player.cpp','src/server/game/Entities/Player/Player.h'):
  raw=(path/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==manifest[name];files[name]=raw.decode()
 header=files['src/server/game/Entities/Player/Player.h']
 for constant,value in(('INVENTORY_SLOT_ITEM_START',23),('INVENTORY_SLOT_ITEM_END',39),('BANK_SLOT_ITEM_START',39),('BANK_SLOT_ITEM_END',67)):
  assert re.search(r'\b'+constant+r'\s*=\s*'+str(value)+r'\b',header)
 gate=body(files['src/server/game/Entities/Player/Player.cpp'],'void Player::AutoUnequipOffhandIfNeed(')
 gate=gate[:gate.index('    ItemPosCountVec off_dest;')]
 methods+='\nvoid Player::'+('Tc'if core=='trinitycore'else'Ac')+'(bool force)'+gate+'\n ++stow;\n}\n'
mock=r'''
#include <cassert>
#include <iostream>
constexpr int INVENTORY_SLOT_BAG_0=255,EQUIPMENT_SLOT_OFFHAND=16,EQUIPMENT_SLOT_MAINHAND=15;
constexpr int INVTYPE_WEAPON=13,INVTYPE_WEAPONOFFHAND=22,INVTYPE_2HWEAPON=17;
constexpr int ITEM_SUBCLASS_WEAPON_POLEARM=6,ITEM_SUBCLASS_WEAPON_STAFF=10,ITEM_SUBCLASS_WEAPON_FISHING_POLE=20;
struct ItemTemplate{int InventoryType=13,SubClass=0;int GetInventoryType()const{return InventoryType;}};
struct Item{ItemTemplate t;ItemTemplate const*GetTemplate()const{return &t;}};
struct Player{
 Item off,main;bool occupied=true,hasMain=true,dual=false;int stow=0;
 Item*GetItemByPos(int,int slot){return slot==16?(occupied?&off:nullptr):(hasMain?&main:nullptr);}
 bool CanDualWield()const{return dual;}
 bool CanTitanGrip()const{return false;}bool CanTitanGrip(Item*)const{return false;}
 bool IsTwoHandUsed()const{return main.t.InventoryType==17;}
 void UpdateTitansGrip(){}
 void Tc(bool force=false);void Ac(bool force=false);
};
'''
main=r'''
int main(){
 for(int type:{13,22}){Player p;p.off.t.InventoryType=type;p.Tc();p.Ac();assert(p.stow==2);}
 Player shield;shield.off.t.InventoryType=14;shield.main.t.InventoryType=21;shield.Tc();shield.Ac();assert(shield.stow==0);
 Player empty;empty.occupied=false;empty.Tc();empty.Ac();assert(empty.stow==0);
 Player invalid;invalid.off.t.InventoryType=14;invalid.main.t.InventoryType=17;invalid.Tc();invalid.Ac();assert(invalid.stow==2);
 Player selected;selected.dual=true;selected.off.t.InventoryType=22;selected.Tc();selected.Ac();assert(selected.stow==0);
 std::cout<<"PASS pinned TC/AC off-hand decisions: unselected weapons require stowing; shield with one-handed main hand stays equipped; empty, selected Dual Wield and two-handed controls; native backpack/bank bounds verified. Mocked consumers; gameplay NOT TESTED\n";
}
'''
with tempfile.TemporaryDirectory()as d:
 cpp=Path(d)/'equipment.cpp';exe=Path(d)/'equipment';cpp.write_text(mock+methods+main)
 subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
