"""Regression: completed jobs must leave monitor without user input or timer drift."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, os.environ.get('SCANTAILOR_MENU_ROOT', str(Path(__file__).resolve().parents[1] / 'scripts')))
from scantailor_menu.model import Controller, elapsed_seconds
from scantailor_menu.ui import UI
CLI=None

class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.model=Controller(CLI,self.root/'jobs')
        self.console=Mock();self.console.dimensions.return_value=(100,30)
        self.ui=UI(self.console,self.model);self.ui.results=Mock()

    def tearDown(self):
        if self.model.running:
            self.model.process.wait(timeout=15)
            limit=time.monotonic()+5
            while self.model.running and time.monotonic()<limit: time.sleep(.01)
        self.temp.cleanup()

    def test_terminal_states_open_results_without_input(self):
        for state in ('complete','review / partial failure','failed','cancelled'):
            with self.subTest(state=state):
                self.ui.results.reset_mock();self.console.reset_mock()
                self.model.status=state
                self.ui.monitor()
                self.ui.results.assert_called_once_with()
                self.console.read.assert_not_called()
                self.console.draw.assert_not_called()

    def test_idle_input_poll_observes_completion(self):
        self.model.process=Mock();self.model.status='running'
        self.model.progress.update(started=10,done=3,total=3)
        def complete():
            with self.model.lock:
                self.model.progress['finished']=12
                self.model.status='complete'
            return None
        self.console.read.side_effect=complete
        self.ui.monitor()
        self.console.read.assert_called_once_with()
        self.ui.results.assert_called_once_with()
        self.assertEqual(elapsed_seconds(self.model.progress),2)

    def test_cancelling_waits_for_worker_exit(self):
        self.model.process=Mock();self.model.status='cancelling'
        self.console.read.return_value=('escape',None)
        self.ui.monitor()
        self.ui.results.assert_not_called()
        self.console.read.assert_called_once_with()
        self.model.status='cancelled'

    def test_worker_freezes_and_persists_all_terminal_durations(self):
        for code,state in ((0,'complete'),(1,'review / partial failure'),(3,'failed'),(130,'cancelled')):
            with self.subTest(code=code):
                folder=self.model.new_folder()
                job={'folder':str(folder),'output':str(folder),'args':[],'revision':0,'command':'process','resumable':True,'status':'running'}
                self.model.launch(job,[sys.executable,'-c',f'import sys; print("worker finished"); sys.exit({code})'])
                deadline=time.monotonic()+10
                while self.model.running and time.monotonic()<deadline: time.sleep(.01)
                self.assertEqual(self.model.status,state)
                duration=elapsed_seconds(self.model.progress)
                self.assertIsNotNone(self.model.progress['finished'])
                with patch('scantailor_menu.model.time.monotonic',return_value=time.monotonic()+1000):
                    self.assertEqual(elapsed_seconds(self.model.progress),duration)
                saved=json.loads((folder/'job.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['status'],state)
                self.assertAlmostEqual(saved['elapsed_seconds'],duration,places=3)

    def test_real_preview_finalizes_before_results(self):
        from PIL import Image
        image=self.root/'page.png'
        Image.new('RGB',(160,200),'white').save(image,dpi=(150,150))
        self.model.select('images',[image])
        self.model.apply({'schema_version':2,'defaults':{'deskew':{'mode':'off'}}})
        self.model.start('preview',sample=True)
        def poll():
            time.sleep(.01)
            return None
        self.console.read.side_effect=poll
        def results():
            self.assertEqual(self.model.status,'complete')
            self.assertTrue((Path(self.model.last['output'])/'preview.html').exists())
            self.assertGreaterEqual(self.model.last['elapsed_seconds'],0)
        self.ui.results.side_effect=results
        self.ui.monitor()
        self.ui.results.assert_called_once_with()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cli',type=Path,required=True)
    args,rest=parser.parse_known_args();CLI=args.cli.resolve()
    unittest.main(argv=[sys.argv[0],*rest])
