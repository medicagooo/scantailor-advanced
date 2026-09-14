"""Regression coverage for persistent settings, task decisions and verified reuse."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock
from PIL import Image, ImageDraw
import pymupdf
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get('SCANTAILOR_MENU_ROOT', str(ROOT/'scripts')))
from scantailor_menu.model import Controller
from scantailor_menu.persistence import portable_config, outcome_complete
from scantailor_menu.ui import UI

CLI = None

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root/'input'; self.source.mkdir()
        for n in range(9):
            im = Image.new('RGB',(400,540),'white'); d=ImageDraw.Draw(im)
            for y in range(40,450,30): d.text((40,y),f'PAGE {n+1}  A field notebook 12345',fill='black')
            im.save(self.source/f'{n+1:03}.png',dpi=(100,100))
        self.config = self.root/'config.json'
        self.settings = {'schema_version':2,'defaults':{'deskew':{'mode':'off'},'content':{'page_mode':'off','content_mode':'off'}}}
        self.config.write_text(json.dumps(self.settings))
        self.m = Controller(CLI, self.root / 'store', language='zh-Hans')
        self.m.select('images',sorted(self.source.glob('*.png')))
        self.m.output=str(self.root/'output'); self.m.update_options({'dpi':100})
        self.m.apply(self.settings)

    def tearDown(self):
        if self.m.running:
            self.m.cancel(); self.wait(self.m)
        self.temp.cleanup()

    def run_cli(self,command='preview',output='native',extra=(),settings=True):
        args=[str(CLI),command,'--input',str(self.source),'--output',str(self.root/output),'--dpi','100']
        if settings: args+=['--config',str(self.config)]
        result=subprocess.run(args+list(map(str,extra)),capture_output=True,text=True,encoding='utf-8',timeout=90)
        self.assertIn(result.returncode,(0,1),result.stdout+result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    def wait(self,m):
        deadline=time.monotonic()+90
        while m.running and time.monotonic()<deadline: time.sleep(.03)
        self.assertFalse(m.running,'Worker did not finish')
        self.assertIn(m.status,('complete','review / partial failure'),m.lines)

    def test_preferences_and_dpi(self):
        config=copy.deepcopy(self.settings); config['defaults']['output']={'dpi':[600,600]}
        self.m.apply(config); self.m.update_options({'dpi':150,'jobs':3})
        self.assertEqual(self.m.dpi_summary('input'),'150')
        self.assertEqual(self.m.dpi_summary('output'),'600')
        loaded=Controller(CLI, self.root / 'store', language='zh-Hans')
        self.assertEqual(loaded.options['dpi'],150); self.assertEqual(loaded.options['jobs'],3)
        loaded.select('images',[self.source/'001.png'])
        self.assertEqual(loaded.config['defaults']['output']['dpi'],[600,600])
        self.assertEqual(loaded.inputs,[str(self.source/'001.png')])
        before=loaded.preferences_path.read_bytes()
        with self.assertRaises(ValueError): loaded.apply({'schema_version':2,'bogus':True})
        self.assertEqual(before,loaded.preferences_path.read_bytes())
        loaded.apply({'schema_version':2,'defaults':{'input':{'dpi':[200,200]}}})
        loaded.update_options({'jobs':2})
        self.assertEqual(loaded.config['defaults']['input']['dpi'],[200,200])
        self.assertEqual(loaded.options['dpi'],200)
        loaded.preferences_path.write_text('{bad json')
        recovered=Controller(CLI, self.root / 'store', language='zh-Hans')
        self.assertTrue(recovered.preference_error)
        self.assertEqual(recovered.options['dpi'],300)

    def test_manual_modes_are_not_orphaned(self):
        config={'schema_version':2,'defaults':{'split':{'mode':'manual','cutters':[]},'content':{'page_mode':'manual','content_mode':'manual','page_rect':[1,2,3,4]},'output':{'dewarp':'manual','distortion_model':{}}}}
        saved=portable_config(config)
        self.assertEqual(saved['defaults']['split']['mode'],'auto')
        self.assertEqual(saved['defaults']['content']['page_mode'],'off')
        self.assertEqual(saved['defaults']['output']['dewarp'],'off')

    def test_order_is_part_of_identity(self):
        first=self.m.plan()['identity']; self.m.inputs.reverse()
        self.assertNotEqual(first,self.m.plan()['identity'])

    def test_project_source_changes_invalidate_identity(self):
        self.run_cli('process')
        self.m.select('project',[self.root/'native/project.scan'])
        first=self.m.plan()['identity']
        im=Image.open(self.source/'001.png'); im.putpixel((0,0),(20,20,20)); im.save(self.source/'001.png',dpi=(100,100))
        self.assertNotEqual(first,self.m.plan()['identity'])

    def test_source_sample_and_complete_reuse(self):
        events=self.run_cli(extra=['--source-pages','sample','--stage','output','--html'])
        self.assertEqual([x['total'] for x in events if x['event']=='phase_started'],[3,3,3,3,3])
        report=json.loads((self.root/'native/report.json').read_text(encoding='utf-8'))
        self.assertEqual([Path(p['input']).name for p in report['pages']],['001.png','005.png','009.png'])
        events=self.run_cli(extra=['--source-pages','sample','--stage','output','--html','--resume'])
        self.assertTrue(any(e['event']=='task_reused' for e in events))
        self.assertFalse(any(e['event']=='page_started' for e in events))

    def test_stage_reuse_and_output_change(self):
        cache=self.root/'analysis-cache'
        self.run_cli('analyze','analysis',['--through','deskew','--analysis-cache',cache])
        events=self.run_cli('preview','preview',['--stage','output','--analysis-cache',cache])
        self.assertEqual([e['stage'] for e in events if e['event']=='phase_reused'],['split','deskew'])
        self.settings['defaults']['output']={'mode':'bw'};self.config.write_text(json.dumps(self.settings))
        events=self.run_cli('process','changed',['--analysis-cache',cache,'--overwrite'])
        self.assertEqual([e['stage'] for e in events if e['event']=='phase_reused'],['split','deskew','content','layout'])
        self.run_cli('process','fresh')
        a=json.loads((self.root/'changed/report.json').read_text(encoding='utf-8'));b=json.loads((self.root/'fresh/report.json').read_text(encoding='utf-8'))
        self.assertEqual([p.get('sha256') for p in a['pages']],[p.get('sha256') for p in b['pages']])

    def test_corrupt_completion_metadata_is_rebuilt(self):
        self.run_cli('process')
        (self.root/'native/completion.json').write_text('{broken')
        events=self.run_cli('process',extra=['--resume'])
        self.assertFalse(any(e['event']=='task_reused' for e in events))
        self.assertIn('fingerprint',json.loads((self.root/'native/completion.json').read_text(encoding='utf-8')))

    def test_external_project_resume(self):
        self.run_cli('process',extra=['--save-project',self.root/'external.scan'])
        self.run_cli('process',extra=['--save-project',self.root/'new.scan','--resume'])
        self.assertTrue((self.root/'new.scan').is_file())

    def test_cancelled_confirmation_never_launches(self):
        class Console:
            def choose(self,*args,**kwargs): return None
        ui=UI(Console(),self.m)
        ui.execute('preview',sample=True)
        self.assertIsNone(self.m.last)

    def test_duplicate_confirmations_and_snapshot_resume(self):
        self.m.start('preview',sample=True); self.wait(self.m)
        self.assertTrue(self.m.plan('preview',True)['valid'])
        self.m.start=Mock()
        console=Mock(); ui=UI(console,self.m); ui.results=Mock(); ui.monitor=Mock()
        console.choose.return_value=0
        ui.execute('preview',sample=True)
        ui.results.assert_called_once(); self.m.start.assert_not_called()
        console.choose.side_effect=[1,0]
        ui.execute('preview',sample=True)
        self.m.start.assert_not_called()  # Cancel the second overwrite confirmation.
        console.choose.side_effect=[1,1]
        ui.execute('preview',sample=True)
        self.m.start.assert_called_once_with('preview',sample=True,decision='overwrite')
        self.m.start.reset_mock(); console.choose.side_effect=None; console.choose.return_value=0
        self.m.last['outcome_complete']=False; self.m.last['status']='cancelled'; self.m.save_job(self.m.last)
        ui.execute('preview',sample=True)
        self.m.start.assert_called_once_with(resume=True)

    def test_failure_report_is_not_complete(self):
        folder=self.root/'failed';folder.mkdir()
        (folder/'batch-report.json').write_text(json.dumps({'results':[],'failures':[{'message':'bad pdf'}]}))
        self.assertFalse(outcome_complete(folder))
        (folder/'batch-report.json').write_text(json.dumps({'results':[{'errors':1}],'failures':[]}))
        self.assertFalse(outcome_complete(folder))

    def test_pdf_layout_sample_and_input_dpi_rule(self):
        pdfdir=self.root/'pdf';pdfdir.mkdir();doc=pymupdf.open()
        for n in range(9):
            page=doc.new_page(width=288,height=389);page.insert_image(page.rect,filename=str(self.source/f'{n+1:03}.png'))
        doc.save(pdfdir/'test.pdf');doc.close()
        out=self.root/'pdf-output'
        command=[sys.executable,str(ROOT/'scripts/process_pdf_folder.py'),'--pdf-dir',str(pdfdir),'--cli',str(CLI),'--output-dir',str(out),'--dpi','100','--config',str(self.config)]
        def run(extra):
            r=subprocess.run(command+extra,capture_output=True,text=True,encoding='utf-8',timeout=90)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
        events=run(['--command','preview','--sample'])
        self.assertEqual([e['source_page'] for e in events if e['event']=='page_rendered'],[1,5,9])
        self.settings['rules']=[{'select':{'images':[1]},'settings':{'input':{'dpi':[200,200]}}}]
        self.config.write_text(json.dumps(self.settings))
        events=run([])
        self.assertEqual(len([e for e in events if e['event']=='page_render_reused']),3)
        self.assertEqual(len([e for e in events if e['event']=='page_rendered']),6)
        self.assertEqual(sorted(p.name for p in out.iterdir()),['_scantailor','test.deskew.pdf'])
        result=json.loads((out/'_scantailor/batch-report.json').read_text(encoding='utf-8'))['results'][0]
        native=json.loads(next((out/'_scantailor/.work').glob('*/state.json')).read_text(encoding='utf-8'))
        processed=Path(result['pages'][0]['output_image']).parent
        report=json.loads((processed/'report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['pages'][0]['settings']['input']['dpi'],[200,200])
        self.assertEqual(report['pages'][1]['settings']['input']['dpi'],[100,100])
        self.assertTrue(any(e['event']=='pdf_reused' for e in run(['--resume'])))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cli',type=Path,required=True)
    args,rest=parser.parse_known_args();CLI=args.cli.resolve()
    unittest.main(argv=[sys.argv[0],*rest])
