"""Menu state, schema, PDF selection and actual Win32 input-record tests."""
import argparse
import copy
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.environ.get('SCANTAILOR_MENU_ROOT', str(Path(__file__).resolve().parents[1] / 'scripts')))
from scantailor_menu.model import Controller, validate, seed, write_json
from scantailor_menu.console import Console, Record, fit, clean
from scantailor_menu.ui import UI

CLI = None


def wait(model):
    deadline = time.monotonic() + 120
    while model.running and time.monotonic() < deadline:
        time.sleep(.05)
    if model.running:
        model.cancel()
        raise AssertionError('Worker timeout')


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.m = Controller(CLI, self.root / 'menu')

    def tearDown(self):
        if self.m.running:
            self.m.cancel()
            wait(self.m)
        self.temp.cleanup()

    def fixture(self, name='中文 image.png'):
        from PIL import Image, ImageDraw
        path = self.root / name
        im = Image.new('RGB', (240, 320), 'white')
        ImageDraw.Draw(im).text((30, 40), 'MENU TEST 123', fill='black')
        im.save(path, dpi=(100, 100))
        return path

    def test_schema_types_ranges_and_source_scope(self):
        with self.assertRaises(ValueError):
            self.m.apply({'schema_version': 2, 'unknown': True})
        with self.assertRaises(ValueError):
            self.m.apply({'schema_version': 2, 'defaults': {'deskew': {'angle': float('nan')}}})
        with self.assertRaises(ValueError):
            self.m.apply({'schema_version': 2, 'rules': [{'select': {'pages': [1]}, 'settings': {'orientation': {'rotation': 90}}}]})
        with self.assertRaises(ValueError):
            self.m.apply({'schema_version': 2, 'rules': [{'select': {}, 'settings': {}}]})

    def test_sources_reset_rules_and_preview(self):
        path = self.fixture()
        self.m.config = {'schema_version': 2, 'rules': [{'old': True}]}
        self.m.preview = ('old', 'output')
        self.m.select('images', [path])
        self.assertEqual(self.m.config, {'schema_version': 2})
        self.assertIsNone(self.m.preview)
        with self.assertRaises(ValueError):
            self.m.select('images', [path, path])

    def test_project_edit_keeps_applied_settings_and_rebases_paths(self):
        self.m.select('images', [self.fixture()])
        ui = UI(None, self.m)
        ui.message = lambda *args: None
        ui.save_management('project create')
        self.m.apply({'schema_version': 2, 'defaults': {'deskew': {'mode': 'manual', 'angle': 2}}})
        second = self.fixture('second.png')
        ui.save_management('project edit', {'schema_version': 1, 'operations': [{'type': 'insert', 'files': [str(second)], 'dpi': 100}]})
        pages = self.m.query(['project', 'inspect', '--project', self.m.inputs[0]])[-1]['pages']
        self.assertEqual(pages[0]['settings']['deskew']['angle'], 2)
        self.assertEqual(self.m.config, {'schema_version': 2})
        self.m.apply({'schema_version': 2, 'defaults': {'deskew': {'angle': 3}}})
        target = self.m.new_folder() / 'graphical.scan'
        ui.configured_project(target)
        copied = self.m.query(['project', 'inspect', '--project', target])[-1]['pages']
        self.assertTrue(all(Path(p['input']).is_file() for p in copied))
        self.assertEqual(copied[0]['settings']['deskew']['angle'], 3)

    def test_completion_cannot_be_overwritten_by_cancel(self):
        class Process:
            def poll(self):
                return None
            def send_signal(process, signal):
                def finish():
                    with self.m.lock:
                        self.m.status = 'complete'
                process.thread = threading.Thread(target=finish)
                process.thread.start()
                time.sleep(.02)
        self.m.process = Process()
        self.m.status = 'running'
        self.m.cancel()
        self.m.process.thread.join(timeout=2)
        self.assertEqual(self.m.status, 'complete')
        self.assertFalse(self.m.running)

    def test_snapshot_process_resume_and_preview(self):
        self.m.select('images', [self.fixture()])
        self.m.output = str(self.root / 'out')
        config = {'schema_version': 2, 'defaults': {'deskew': {'mode': 'off'}, 'content': {'page_mode': 'off', 'content_mode': 'off'}}}
        self.m.apply(config)
        config['defaults']['deskew']['mode'] = 'manual'
        self.assertEqual(self.m.config['defaults']['deskew']['mode'], 'off')
        self.m.options['dpi'] = 100
        self.m.start()
        with self.assertRaises(ValueError):
            self.m.start()
        with self.assertRaises(ValueError):
            self.m.apply({'schema_version': 2})
        wait(self.m)
        self.assertEqual(self.m.status, 'complete', self.m.lines)
        args = self.m.last['args'][:]
        self.m.apply({'schema_version': 2})
        self.m.start(resume=True)
        wait(self.m)
        self.assertEqual(self.m.last['args'], args)
        self.assertEqual(self.m.status, 'complete', self.m.lines)
        self.m.options['stage'] = 'deskew'
        self.m.start('preview')
        wait(self.m)
        self.assertIn(self.m.status, ('complete', 'review / partial failure'), self.m.lines)
        self.assertEqual(self.m.preview[0], self.m.revision)
        self.assertEqual(len(self.m.history()), 2)

    def test_pdf_exact_selection_same_names_and_preview(self):
        import pymupdf
        paths = []
        for folder in ('a', 'b', 'excluded'):
            parent = self.root / folder
            parent.mkdir()
            path = parent / '同名.pdf'
            doc = pymupdf.open()
            page = doc.new_page(width=180, height=240)
            page.insert_text((20, 30), folder)
            doc.save(path)
            doc.close()
            paths.append(path)
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        self.m.select('pdf', paths[:2])
        self.m.options['dpi'] = 72
        self.m.options['stage'] = 'deskew'
        self.m.start('preview')
        wait(self.m)
        self.assertIn(self.m.status, ('complete', 'review / partial failure'), self.m.lines)
        report = json.loads((Path(self.m.last['output']) / '_scantailor' / 'batch-report.json').read_text(encoding='utf-8'))
        self.assertEqual({r['input'] for r in report['results']}, set(map(str, paths[:2])))
        self.assertEqual(len(list(Path(self.m.last['output']).rglob('project.scan'))), 2)
        self.assertEqual(hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])

    def test_real_console_records_and_launcher(self):
        target = self.root / 'console.json'
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--console-child', str(target), '--cli', str(CLI)],
                                   creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
        self.assertEqual(process.wait(timeout=45), 0)
        report = json.loads(target.read_text(encoding='utf-8'))
        self.assertTrue(report['keyboard'])
        self.assertTrue(report['mouse'])
        self.assertTrue(report['text'])
        self.assertTrue(report['restored'])
        self.assertTrue(report['release_drain'])
        self.assertEqual(report['launcher'], 0)
        self.assertEqual(report['cancelled'], 'cancelled')

    def test_display_sanitizes_controls_and_unicode_width(self):
        self.assertEqual(clean('a\x1b\n\x07b'), 'ab')
        self.assertEqual(fit('中文abc', 5), '中文a')


def console_child(path, cli):
    report = {}
    try:
        c = Console()
        api = c.api
        api.WriteConsoleInputW.argtypes = [W.HANDLE, C.POINTER(Record), W.DWORD, C.POINTER(W.DWORD)]
        def write(records):
            for record in records:
                count = W.DWORD()
                if not api.WriteConsoleInputW(c.input, C.byref(record), 1, C.byref(count)):
                    raise C.WinError(C.get_last_error())
                time.sleep(.02)
        def key(vk, char='\0', mods=0):
            records = []
            for down in (True, False):
                r = Record()
                r.type = 1
                r.event.key.down, r.event.key.vk, r.event.key.char = down, vk, char
                r.event.key.repeat, r.event.key.mods = 1, mods
                records.append(r)
            return records
        def feed(records, delay=.3):
            thread = threading.Thread(target=lambda: (time.sleep(delay), write(records)), daemon=True)
            thread.start()
            return thread
        with c:
            t = feed(key(65, 'a') + key(13, '\r', 8) + key(40) + key(13, '\r'))
            report['keyboard'] = c.choose('test', ['one', 'two']) == 1
            t.join()
            down, up = Record(), Record()
            for r in (down, up):
                r.type = 2
                r.event.mouse.pos.X, r.event.mouse.pos.Y = 5, 5
            down.event.mouse.buttons = 1
            t = feed([down, up])
            report['mouse'] = c.choose('test', ['one', 'two']) == 1
            t.join()
            t = feed(key(65, 'a') + key(49, '1') + key(190, '.') + key(50, '2') + key(13, '\r'))
            report['text'] = c.text('number', '', numeric=True) == '1.2'
            t.join()
            # Transition after the Enter release was queued, as with slow I/O.
            write(key(13, '\r'))
            c.read()
            c.flush()
            report['release_drain'] = 13 not in c.held
        im, om = W.DWORD(), W.DWORD()
        api.GetConsoleMode(c.input, C.byref(im))
        api.GetConsoleMode(c.output, C.byref(om))
        report['restored'] = im.value == c.imode.value and om.value == c.omode.value
        child = subprocess.Popen([str(cli), 'menu', '--python', sys.executable, '--state-dir', str(path.parent / 'launcher')])
        t = feed(key(27, '\x1b'), delay=3)
        report['launcher'] = child.wait(timeout=20)
        t.join()
        model = Controller(cli, path.parent / 'cancel-menu')
        folder = model.new_folder()
        worker = folder / 'worker.py'
        worker.write_text('import signal,time,sys\nsignal.signal(signal.SIGBREAK, lambda *args: sys.exit(130))\nprint("ready", flush=True)\ntime.sleep(20)\n', encoding='utf-8')
        args = [sys.executable, str(worker)]
        job = {'folder': str(folder), 'output': str(folder), 'args': args, 'revision': 0, 'command': 'process', 'resumable': False, 'status': 'running'}
        model.launch(job, args)
        deadline = time.monotonic() + 5
        while 'ready' not in model.lines and time.monotonic() < deadline:
            time.sleep(.02)
        model.cancel()
        wait(model)
        report['cancelled'] = model.status
        path.write_text(json.dumps(report), encoding='utf-8')
        return 0
    except Exception as error:
        path.write_text(json.dumps({'error': str(error), **report}), encoding='utf-8')
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--console-child', type=Path)
    args, rest = parser.parse_known_args()
    CLI = args.cli.resolve()
    if args.console_child:
        raise SystemExit(console_child(args.console_child, CLI))
    unittest.main(argv=[sys.argv[0], *rest])
