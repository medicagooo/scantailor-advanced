"""Workbench editing, native clipboard, responsive layout and workflow evidence."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import hashlib
from contextlib import nullcontext
sys.path.insert(0, os.environ.get('SCANTAILOR_MENU_ROOT', str(Path(__file__).resolve().parents[1] / 'scripts')))
from scantailor_menu.editing import Editor, parse_paths, paste_text
from scantailor_menu.rendering import Frame, cells
from scantailor_menu.workbench import Workbench
from scantailor_menu.console import Console, Record, Coord
from scantailor_menu.model import Controller
from scantailor_menu.ui import UI

CLI = None


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = Controller(CLI, self.root / 'jobs')
        self.ui = UI(None, self.model)
        self.workbench = Workbench(self.ui)

    def tearDown(self):
        if self.model.running:
            self.model.cancel()
            self.model.process.wait(timeout=60)
        self.temp.cleanup()

    def test_edit_selection_paste_navigation(self):
        e = Editor('old location')
        e.select_all()
        self.assertTrue(e.insert('"D:\\中文 地址\\教材.pdf"'))
        self.assertEqual(e.value, '"D:\\中文 地址\\教材.pdf"')
        e.move('home')
        e.move(1, selecting=True)
        e.delete()
        e.move('end')
        e.delete(backwards=True)
        self.assertEqual(e.value, 'D:\\中文 地址\\教材.pdf')
        e.move(-1)
        e.insert('x')
        self.assertTrue(e.value.endswith('pdx f'.replace(' ', '')))
        n = Editor('300', numeric=True)
        n.select_all()
        self.assertFalse(n.insert('hello'))
        self.assertEqual(n.value, '300')
        self.assertTrue(n.insert('150'))
        self.assertEqual(n.value, '150')

    def test_path_quotes_multiline_unicode_and_dedup(self):
        paths = parse_paths(' "D:\\中文 路径\\甲.pdf"\r\n"D:\\中文 路径\\乙.pdf" "D:\\中文 路径\\丙.pdf"\n"D:\\中文 路径\\甲.pdf" ')
        self.assertEqual(len(paths), 3)
        self.assertEqual(paths[0].name, '甲.pdf')

    def test_common_mode_margins_and_scheme_review_fixes(self):
        class Choices:
            def __init__(self, choices):
                self.choices = iter(choices)
            def choose(self, *args, **kwargs):
                return next(self.choices)
        self.model.apply({'schema_version': 2, 'defaults': {'deskew': {'mode': 'manual', 'angle': 3}, 'layout': {'auto_margins': True}}})
        self.workbench.c = Choices([0, 0, 4, 6])
        self.ui.edit = lambda *args: (True, 7)
        self.workbench.common()
        settings = self.model.config['defaults']
        self.assertEqual(settings['deskew'], {'mode': 'auto'})
        self.assertFalse(settings['layout']['auto_margins'])
        self.assertEqual(settings['layout']['margins_mm']['left'], 7)
        original = json.loads(json.dumps(self.model.config))
        self.workbench.c = Choices([0, 1, 7])
        self.workbench.common()
        self.assertEqual(self.model.config, original)
        self.model.options['review_policy'] = 'report'
        self.workbench.c = Choices([0])
        self.workbench.schemes()
        self.assertEqual(self.model.options['review_policy'], 'preserve')

    def fixture(self, name):
        from PIL import Image
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (200, 300), 'white').save(path, dpi=(100, 100))
        return path

    def test_collect_validate_recursive_and_output_suggestion(self):
        image = self.fixture('中文 空格/a.png')
        second = self.fixture('中文 空格/sub/b.png')
        kind, paths = self.workbench.collect(str(image.parent))
        self.assertEqual(paths, [image])
        kind, paths = self.workbench.collect(str(image.parent), recursive=True)
        self.assertEqual(len(paths), 2)
        (image.parent / 'scantailor-output').write_text('occupied filename')
        self.workbench.select(kind, paths)
        self.assertEqual(Path(self.model.output).name, 'scantailor-output-2')
        with self.assertRaises(ValueError):
            self.workbench.collect(str(image) + '\n' + str(self.root / 'missing.pdf'))
        (self.root / 'test.pdf').write_bytes(b'not a real pdf')
        with self.assertRaises(ValueError):
            self.workbench.collect(str(image) + '\n' + str(self.root / 'test.pdf'))

    def test_responsive_enabled_actions_and_hitboxes(self):
        for width, height in [(120, 34), (80, 25), (60, 22)]:
            frame, controls = self.workbench.frame(width, height)
            self.assertNotIn('start', controls)
            self.assertIn('paste', controls)
            for x, y, w, h, key in frame.hits:
                self.assertLess(x + w, width + 1)
                self.assertLess(y, height)
                self.assertEqual(frame.hit((x, y)), key)
            self.assertEqual(len(frame.lines()), height)
        image = self.fixture('page.png')
        self.workbench.select('images', [image])
        frame, controls = self.workbench.frame(120, 34)
        self.assertIn('start', controls)
        self.assertIn('preview', controls)
        self.model.process = object()
        self.model.status = 'running'
        frame, controls = self.workbench.frame(80, 25)
        self.assertNotIn('paste', controls)
        self.assertNotIn('start', controls)
        self.assertIn('progress', controls)
        self.model.status = 'idle'

    def test_sample_preview_preserves_whole_project(self):
        files = [self.fixture(f'p{i}.png') for i in range(5)]
        self.workbench.select('images', files)
        self.model.apply({'schema_version': 2, 'defaults': {'deskew': {'mode': 'off'}, 'content': {'page_mode': 'off', 'content_mode': 'off'}}})
        self.model.options['dpi'] = 100
        self.model.start('preview', sample=True)
        deadline = time.monotonic() + 60
        while self.model.running and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertFalse(self.model.running)
        self.assertIn(self.model.status, ('complete', 'review / partial failure'), self.model.lines)
        output = Path(self.model.last['output'])
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(len(report['pages']), 5)
        self.assertEqual(sum(bool(p.get('preview')) for p in report['pages']), 3)
        viewer = (output / 'preview.html').read_text(encoding='utf-8')
        self.assertIn('只看原图', viewer)
        self.assertIn('只看结果', viewer)
        self.assertIn('放大检查细节', viewer)

    def test_preview_viewer_escapes_report_text(self):
        from scantailor_menu.preview import build_viewer
        image = self.fixture('test.png')
        output = self.root / 'preview'
        output.mkdir()
        attack = '</script><script>alert(1)</script>'
        (output / 'report.json').write_text(json.dumps({'pages': [{'input': str(image), 'preview': str(image), 'message': attack}]}), encoding='utf-8')
        html = build_viewer(output).read_text(encoding='utf-8')
        self.assertNotIn(attack, html)
        self.assertIn('\\u003c/script>', html)

    def test_native_clipboard_console(self):
        output = self.root / 'clipboard.json'
        startup = subprocess.STARTUPINFO()
        startup.dwFlags, startup.wShowWindow = subprocess.STARTF_USESHOWWINDOW, 0
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--cli', str(CLI), '--clipboard-child', str(output)],
                                 startupinfo=startup, creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.assertEqual(child.wait(timeout=30), 0, output.read_text(encoding='utf-8') if output.exists() else '')
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertTrue(report['ctrl_v'])
        self.assertTrue(report['native_clipboard_read'])
        self.assertTrue(report['shift_insert'])
        self.assertTrue(report['right_click'])
        self.assertTrue(report['terminal_injected_multiline'])
        self.assertTrue(report['workbench_visible'])

    def test_keyboard_pasted_path_to_finished_task(self):
        output = self.root / 'workflow.json'
        startup = subprocess.STARTUPINFO()
        startup.dwFlags, startup.wShowWindow = subprocess.STARTF_USESHOWWINDOW, 0
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--cli', str(CLI), '--workflow-child', str(output)],
                                 startupinfo=startup, creationflags=subprocess.CREATE_NEW_CONSOLE)
        code = child.wait(timeout=60)
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(code, 0, report)
        self.assertTrue(report['source_preserved'])
        self.assertTrue(report['output_exists'])
        self.assertIn(report['status'], ('complete', 'review / partial failure'))


def clipboard_child(path, cli):
    result = {'terminal': bool(os.environ.get('WT_SESSION'))}
    try:
        # No global clipboard writes. A read-only native smoke check plus a
        # deterministic provider tests Unicode paste without replacing user data.
        with nullcontext():
            with Console() as c:
                c.api.WriteConsoleInputW.argtypes = [W.HANDLE, C.POINTER(Record), W.DWORD, C.POINTER(W.DWORD)]
                def key(vk, char='\0', mods=0):
                    records = []
                    for down in (True, False):
                        r = Record()
                        r.type = 1
                        r.event.key.down, r.event.key.vk, r.event.key.char = down, vk, char
                        r.event.key.repeat, r.event.key.mods = 1, mods
                        records.append(r)
                    return records
                def feed(records):
                    def writer():
                        time.sleep(.25)
                        for r in records:
                            count = W.DWORD()
                            if not c.api.WriteConsoleInputW(c.input, C.byref(r), 1, C.byref(count)):
                                raise C.WinError(C.get_last_error())
                            time.sleep(.01)
                    thread = threading.Thread(target=writer, daemon=True)
                    thread.start()
                    return thread
                sample = '"D:\\中文 地址\\教材.pdf"\r\n"D:\\第二本.pdf"'
                native = c.clipboard
                existing = native()
                result['native_clipboard_read'] = isinstance(existing, str)
                thread = feed(key(86, '\x16', 8) + key(13, '\r', 8))
                actual = c.text('剪贴板只读测试', multiline=True)
                expected = paste_text(existing, True)
                result['native_ctrl_v'] = actual == (expected if len(expected) <= 32767 else '')
                thread.join()
                c.clipboard = lambda: sample
                for name, sequence in [('ctrl_v', key(86, '\x16', 8)), ('shift_insert', key(45, '\0', 16))]:
                    thread = feed(sequence + key(13, '\r', 8))
                    result[name] = c.text('路径粘贴测试', 'old', multiline=True) == sample.replace('\r\n', '\n')
                    thread.join()
                down, up = Record(), Record()
                for r in (down, up):
                    r.type = 2
                    r.event.mouse.pos.X, r.event.mouse.pos.Y = 8, 6
                down.event.mouse.buttons = 2
                thread = feed([down, up] + key(13, '\r', 8))
                result['right_click'] = c.text('右键粘贴测试', multiline=True) == sample.replace('\r\n', '\n')
                thread.join()
                sequence = []
                for char in 'aa中文\r\nbb':
                    sequence += key(13 if char in '\r\n' else 0, '\r' if char in '\r\n' else char)
                thread = feed(sequence + key(13, '\r', 8))
                result['terminal_injected_multiline'] = c.text('终端注入多行文本', multiline=True) == 'aa中文\n\nbb'
                thread.join()
                model = Controller(cli, path.parent / ('screen-' + path.stem))
                bench = Workbench(UI(c, model))
                frame, _ = bench.frame(*c.dimensions())
                c.draw(frame)
                c.api.ReadConsoleOutputCharacterW.argtypes = [W.HANDLE, W.LPWSTR, W.DWORD, Coord, C.POINTER(W.DWORD)]
                buffer = C.create_unicode_buffer(c.width * c.height + 1)
                count = W.DWORD()
                if not c.api.ReadConsoleOutputCharacterW(c.output, buffer, c.width * c.height, Coord(0, 0), C.byref(count)):
                    raise C.WinError(C.get_last_error())
                visible = ''.join(buffer.value.split())
                result['workbench_visible'] = 'ScanTailor' in visible and '输入文件' in visible and '粘贴路径' in visible
        path.write_text(json.dumps(result), encoding='utf-8')
        return 0 if all(v for k, v in result.items() if k != 'terminal') else 1
    except Exception as error:
        result['error'] = str(error)
        path.write_text(json.dumps(result), encoding='utf-8')
        return 1


def workflow_child(path, cli):
    from PIL import Image
    source = path.parent / '中文 空格' / '扫描 页面.png'
    source.parent.mkdir()
    Image.new('RGB', (200, 300), 'white').save(source, dpi=(100, 100))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    model = Controller(cli, path.parent / 'workflow-jobs')
    model.options['dpi'] = 100
    failures = []
    try:
        with Console() as c:
            c.clipboard = lambda: '"' + str(source) + '"'
            c.api.WriteConsoleInputW.argtypes = [W.HANDLE, C.POINTER(Record), W.DWORD, C.POINTER(W.DWORD)]
            def key(vk, char='\0', mods=0):
                for down in (True, False):
                    record, count = Record(), W.DWORD()
                    record.type = 1
                    record.event.key.down, record.event.key.vk, record.event.key.char = down, vk, char
                    record.event.key.repeat, record.event.key.mods = 1, mods
                    if not c.api.WriteConsoleInputW(c.input, C.byref(record), 1, C.byref(count)):
                        raise C.WinError(C.get_last_error())
                    time.sleep(.025)
            def until(predicate):
                deadline = time.monotonic() + 30
                while not predicate():
                    if time.monotonic() > deadline:
                        raise TimeoutError('UI workflow did not reach expected state')
                    time.sleep(.02)
            def hits():
                return [h[4] for h in c.frame.hits] if c.frame else []
            def title_contains(text):
                return c.frame and any(text in span[2] for row in c.frame.rows for span in row)
            def drive():
                try:
                    until(lambda: 'paste' in hits())
                    key(13, '\r')
                    until(lambda: 'field' in hits())
                    key(86, '\x16', 8)
                    key(13, '\r', 8)
                    until(lambda: title_contains('找到 1 项'))
                    key(13, '\r')
                    until(lambda: model.inputs and 'start' in hits())
                    key(9, '\t')  # Successful import focuses Preview; next is Start.
                    key(13, '\r')
                    until(lambda: model.last is not None)
                    until(lambda: not model.running and title_contains('查看结果'))
                    key(27, '\x1b')
                    until(lambda: 'start' in hits())
                    key(27, '\x1b')
                except Exception as error:
                    failures.append(str(error))
                    key(27, '\x1b')
            thread = threading.Thread(target=drive, daemon=True)
            thread.start()
            Workbench(UI(c, model)).run()
            thread.join(timeout=2)
        result = {'status': model.status, 'source_preserved': before == hashlib.sha256(source.read_bytes()).hexdigest(),
                  'output_exists': bool(model.last) and (Path(model.last['output']) / 'report.json').exists(), 'failures': failures}
        path.write_text(json.dumps(result), encoding='utf-8')
        return 0 if not failures and model.status in ('complete', 'review / partial failure') else 1
    except Exception as error:
        path.write_text(json.dumps({'error': str(error), 'failures': failures}), encoding='utf-8')
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--clipboard-child', type=Path)
    parser.add_argument('--workflow-child', type=Path)
    args, rest = parser.parse_known_args()
    CLI = args.cli.resolve()
    if args.clipboard_child:
        raise SystemExit(clipboard_child(args.clipboard_child, CLI))
    if args.workflow_child:
        raise SystemExit(workflow_child(args.workflow_child, CLI))
    unittest.main(argv=[sys.argv[0], *rest])
