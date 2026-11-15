import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from core import *
import config
import install
import media
import pipeline


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.p=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def test_timestamps(self):
        for value, expected in [('01:02:03.250',3723.25),('62:03',3723),('12.5',12.5),(0,0)]:
            self.assertEqual(seconds(value),expected)
    def test_reject_timestamps(self):
        for value in [True,-1,float('nan'),float('inf'),'1:60','1:2','-2','1e3','1:02:03:04',None]:
            with self.subTest(value=value), self.assertRaises(ClipError): seconds(value)
    def test_intervals(self):
        self.assertEqual(interval(3,28,30,20,60),(3,28))
        for a,b in [(30,3),(0,0),(0,31),(3,5)]:
            with self.assertRaises(ClipError): interval(a,b,30,20,60)
    def test_strict_json(self):
        for s in ['{"x":1,"x":2}','[NaN]','[Infinity]','{bad}']:
            (self.p/'a').write_text(s)
            with self.assertRaises(ValueError): read(self.p/'a')
    def test_candidates(self):
        c=config.load(); good=dict(start=0,end=25,title='Title',reason='Complete thought',score=80)
        self.assertEqual(len(candidates([good],30,c)),1)
        for changes in [dict(start=-2),dict(end=40),dict(score=True),dict(title=''),dict(unexpected=1),dict(score=float('nan'))]:
            with self.assertRaises(ClipError): candidates([dict(good,**changes)],30,c)
        with self.assertRaises(ClipError): candidates([good],30,c,(10,20))
    def test_overlap(self):
        items=[dict(start=0,end=20,score=80,id='a'),dict(start=10,end=30,score=90,id='b'),dict(start=30,end=50,score=70,id='c')]
        self.assertEqual([m['id'] for m in select(items,3)],['b','c'])
    def test_identity(self):
        self.assertNotEqual(source_id('youtube','same-title-1'),source_id('youtube','same-title-2'))
        self.assertNotEqual(source_id('youtube','123'),source_id('twitch','123'))
        self.assertEqual(source_id('youtube','123'),source_id('youtube','123'))
    def test_path_escape(self):
        with self.assertRaises(ClipError): pipeline.folder(self.p,'../escape')
    def test_atomic(self):
        atomic(self.p/'state.json',{'a':1}); atomic(self.p/'state.json',{'a':2})
        self.assertEqual(read(self.p/'state.json'),{'a':2}); self.assertFalse(list(self.p.glob('*.tmp')))
    def test_resume_and_corruption(self):
        calls=[]
        def producer(): calls.append(1); return {'done':len(calls)}
        self.assertFalse(checkpoint(self.p,'block','k',producer)[1])
        self.assertTrue(checkpoint(self.p,'block','k',producer)[1])
        self.assertEqual(len(calls),1)
        (self.p/'block.json').write_text('broken')
        self.assertFalse(checkpoint(self.p,'block','k',producer)[1]); self.assertEqual(len(calls),2)
        self.assertTrue(list(self.p.glob('*.previous')))
    def test_failure_then_resume(self):
        with self.assertRaises(RuntimeError): checkpoint(self.p,'block','k',lambda: (_ for _ in ()).throw(RuntimeError()))
        self.assertFalse((self.p/'block.state.json').exists())
        self.assertEqual(checkpoint(self.p,'block','k',lambda:[])[0],[])
    def test_key_invalidates(self):
        checkpoint(self.p,'block','a',lambda:1)
        self.assertEqual(checkpoint(self.p,'block','b',lambda:2),(2,False))
    def test_lock(self):
        with lock(self.p):
            with self.assertRaises(ClipError):
                with lock(self.p): pass
        self.assertFalse((self.p/'.lock').exists())
    def test_subprocess_failure(self):
        with self.assertRaises(ClipError): run([sys.executable,'-c','raise SystemExit(3)'])
    def test_subprocess_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired): run([sys.executable,'-c','import time;time.sleep(10)'],.1)
    def test_face_clusters(self):
        samples=[(i,[10+i,10,40,40]) for i in range(5)]+[(i,[700,20,30,30]) for i in range(3)]
        r=media.face_cluster(samples,1000,500)
        self.assertLess(r['box'][0],20); self.assertEqual(r['hits'],5); self.assertEqual(r['clusters'],2)
    def test_face_distinct_frames(self):
        self.assertIsNone(media.face_cluster([(0,[10,10,40,40])]*5,1000,500))
        self.assertIsNone(media.face_cluster([],1000,500))
    def test_captions(self):
        p=self.p/'captions.ass'
        media.captions(p,[dict(start=-1,end=3,word='{\\bad}\ntext')],'Title',2,360,640,config.load())
        text=p.read_text(encoding='utf-8')
        self.assertNotIn('{\\bad}',text); self.assertIn('0:00:02.00',text)
        self.assertEqual(media.ass_time(59.999),'0:01:00.00')
    def test_config(self):
        for x in [{'width':100},{'min_duration':100,'max_duration':20},{'device':'magic'},{'fps':True},{'unknown':1},{'face_threshold':float('inf')}]:
            (self.p/'c.json').write_text(json.dumps(x))
            with self.assertRaises(ValueError): config.load(self.p/'c.json')
    def test_profiles(self):
        for profile in ['9:16','16:9','1:1']:
            atomic(self.p/'c.json',dict(profile=profile)); c=config.load(self.p/'c.json')
            graph=media.compose(c['width'],c['height'],{'box':None},c)
            self.assertIn('ass=captions.ass[v]',graph)
    def test_authorization(self):
        src=self.p/'source.txt'; src.write_text('original')
        meta=dict(platform='local',url=str(src),content_hash=file_hash(src))
        atomic(self.p/'source.json',meta)
        with self.assertRaises(ClipError): pipeline.authorized(self.p)
        pipeline.authorize(self.p,'Explicit approval')
        self.assertEqual(pipeline.authorized(self.p),meta)
        src.write_text('changed')
        with self.assertRaises(ClipError): pipeline.authorized(self.p)
    def test_full_download_gate(self):
        with self.assertRaises(ClipError): pipeline.full_source(self.p,{},config.load())
    def test_install_update_rollback(self):
        source=Path(__file__).resolve().parents[1]; dest=self.p/'skills'/'stream-clipper'
        first=install.install(source,dest)
        self.assertIsNone(first['backup']); self.assertEqual(install.manifest(source),install.manifest(dest))
        (dest/'local-note.txt').write_text('preserve me')
        second=install.install(source,dest); backup=Path(second['backup'])
        self.assertEqual((backup/'local-note.txt').read_text(),'preserve me')
        install.rollback(dest,backup)
        self.assertTrue((dest/'local-note.txt').exists())
    def test_invoke_other_cwd(self):
        cli=Path(__file__).resolve().parents[1]/'scripts'/'clip.py'
        value=json.loads(run([sys.executable,str(cli),'config'],cwd=self.p))
        self.assertEqual(value['profile'],'9:16')
    def test_no_unknown_install_overwrite(self):
        d=self.p/'existing'; d.mkdir(); (d/'a').write_text('keep')
        with self.assertRaises(ClipError): install.install(Path(__file__).resolve().parents[1],d)
        self.assertEqual((d/'a').read_text(),'keep')


if __name__=='__main__': unittest.main()
