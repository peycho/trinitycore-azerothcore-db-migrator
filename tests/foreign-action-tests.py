#!/usr/bin/env python3
"""Inactive foreign Lockpicking is a fixed retirement, never a prerequisite bypass."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from cleanup_console import CleanupError,parser
from cleanup_eligibility import select
from spells import Metadata,Unsupported,reconstruct

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tests'/file)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
semantic=module('action_semantic','spell-state-tests.py');fixture=module('action_assets','spell-fixtures.py');actions=module('action_catalog_assets','foreign-action-fixtures.py')

class ActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name)
        profile=json.loads((ROOT/'compatibility/tc335-acwotlk-v2/spell-metadata.json').read_text())
        original=fixture.stores;fixture.stores=lambda p:actions.extend(original(p),p)
        fixture.write_assets(p,profile)
        class World(semantic.World):
            def table(self,world,table,columns):
                rows=super().table(world,table,columns)
                if table=='spell_ranks':rows += [['1804','1804','1']]+[['1809',str(s),str(i)]for i,s in enumerate((1809,1810,6460),1)]
                return rows
        cls.tc=Metadata('tc',p/'tc-dbc','tc',profile,World());cls.ac=Metadata('ac',p/'ac-dbc','ac',profile,World())
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.tc,self.ac=copy.deepcopy(type(self).tc),copy.deepcopy(type(self).ac)
        self.state={'characters':[[1,7,1,80,0,2,0,32]],'character_spell':[[1,1804,0,0],[1,6603,1,0]],'character_talent':[],'character_skills':[[1,43,400,400]]}
    def review(self):return select(self.state,self.tc,self.ac,preview=True,inactive_foreign_actions=True)
    def test_explicit_only_and_exact_inverse_input(self):
        original=copy.deepcopy(self.state)
        for kwargs in ({},{'absent_teachers':True},{'reviewed_racials':True}):
            self.assertFalse(select(self.state,self.tc,self.ac,preview=True,**kwargs)[0])
        with self.assertRaises(Unsupported)as e:reconstruct((7,1,0,2),{1804:(0,0),6603:(1,0)},{},{43:(400,400)},self.tc,self.ac,'tc-to-ac',level=80)
        self.assertEqual(e.exception.reason,'UNREPRESENTABLE_INACTIVE_SPELL')
        rows,excluded,_,summary,_=self.review()
        self.assertEqual(rows,[(1,1804,0,0)]);self.assertFalse(excluded)
        self.assertEqual(summary['inactive_rows_removed'],1);self.assertEqual(summary['skill_rows_changed'],0)
        self.assertEqual(self.state,original)
        self.assertEqual(set(reconstruct((7,1,0,2),{6603:(1,0)},{},{43:(400,400)},self.tc,self.ac,'tc-to-ac',level=80)),{6603})
        native=reconstruct((7,1,0,2),{6603:(1,0)},{},{43:(400,400)},self.tc,self.ac,'tc-to-ac',level=80)
        reverse=reconstruct((7,1,0,2),{s:(r['mask'],)for s,r in native.items()if r['disposition']=='PERSISTENT'},{},{43:(400,400)},self.ac,self.tc,'ac-to-tc',level=80)
        self.assertEqual(set(reverse),{6603})
        self.assertEqual(select(self.state,self.tc,self.ac,1,inactive_foreign_actions=True)[0],rows)
        with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,2,inactive_foreign_actions=True)
    def test_rogues_enabled_disabled_and_known_teacher_defer(self):
        self.state['characters'][0][2]=4;self.assertFalse(self.review()[0]);self.state['characters'][0][2]=1
        for flags in ((1,0),(1,1),(0,1)):
            self.state['character_spell'][0][2:]=flags;self.assertFalse(self.review()[0])
        self.state['character_spell'][0][2:]=[0,0]
        for teacher in (1809,1810,6460):
            for flags in ((1,0),(1,1),(0,0)):
                self.state['character_spell'].append([1,teacher,*flags]);self.assertFalse(self.review()[0]);self.state['character_spell'].pop()
    def test_skills_ownership_reset_and_character_guards(self):
        for field,value in ((6,1),(7,4),(3,200),(5,0)):
            original=self.state['characters'][0][field];self.state['characters'][0][field]=value
            self.assertFalse(self.review()[0]);self.state['characters'][0][field]=original
        self.state['character_skills'].append([1,633,1,400]);self.assertFalse(self.review()[0]);self.state['character_skills'].pop()
        self.state['character_talent'].append([1,900000,0]);self.assertFalse(self.review()[0])
    def test_routes_scripts_and_mechanics_cannot_expand_exception(self):
        for core in ('tc','ac'):
            for mutate in (lambda m:m.spells[1804].__setitem__(71,36),lambda m:m.requires[1804].add(6603),
                lambda m:m.prerequisite_users[1804].add(6603),lambda m:m.scripts[1804].add('spell_unknown'),
                lambda m:m.learns[6603].append((1804,1,False)),lambda m:m.effect_learns[1804].append((6603,1,False)),
                lambda m:m.stores['SkillRaceClassInfo'][601].__setitem__(3,0),lambda m:m.aura_owners[1804].add(12282),
                lambda m:m.additional.add(1804),lambda m:m.spells[1810].__setitem__(110,633),
                lambda m:m.scripts[6460].add('spell_unknown')):
                tc,ac=copy.deepcopy(self.tc),copy.deepcopy(self.ac);mutate(tc if core=='tc'else ac)
                self.assertFalse(select(self.state,tc,ac,preview=True,inactive_foreign_actions=True)[0],(core,mutate))
    def test_other_families_and_modes_remain_outside(self):
        self.state['character_spell']=[[1,48942,0,0]];self.assertFalse(self.review()[0])
        with self.assertRaises(CleanupError):select(self.state,self.tc,self.ac,preview=True,inactive_foreign_actions=True,absent_teachers=True)
        with self.assertRaises(SystemExit):parser().parse_args(['plan','spell-eligibility','--migration-inspection','latest','--inactive-foreign-actions','--reviewed-racials','--preview'])

if __name__=='__main__':unittest.main()
