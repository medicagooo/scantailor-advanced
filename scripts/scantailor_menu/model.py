"""Typed drafts and immutable worker snapshots; no processing algorithms here.

The UI edits copies, then commits them. Each run writes its own manifest and
configuration; resume reuses that snapshot instead of the current UI draft.
"""
from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import image_encoding
import signal
import subprocess
import threading
import uuid
import time


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temp, path)


def validate(schema, value, path='settings'):
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'boolean': type(value) is bool,
             'integer': type(value) is int,
             'number': type(value) in (int, float) and math.isfinite(value)}
    if not valid.get(kind, False):
        raise ValueError(f'{path}: expected {kind}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: choose {schema["enum"]}')
    if kind == 'object':
        props = schema['properties']
        if set(value) - set(props):
            raise ValueError(f'{path}: unknown fields {set(value) - set(props)}')
        if set(schema.get('required', [])) - set(value):
            raise ValueError(f'{path}: missing {set(schema["required"]) - set(value)}')
        for key, item in value.items():
            validate(props[key], item, f'{path}.{key}')
    elif kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 100000):
            raise ValueError(f'{path}: item count {schema.get("minItems", 0)}..{schema.get("maxItems", 100000)}')
        for i, item in enumerate(value):
            validate(schema['items'], item, f'{path}[{i + 1}]')
    elif kind in ('number', 'integer'):
        if not schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf):
            raise ValueError(f'{path}: range {schema.get("minimum")}..{schema.get("maximum")}')
    elif kind == 'string' and len(value) < schema.get('minLength', 0):
        raise ValueError(f'{path}: value required')


def seed(schema):
    if 'enum' in schema:
        return schema['enum'][0]
    kind = schema['type']
    if kind == 'object':
        return {k: seed(schema['properties'][k]) for k in schema.get('required', [])}
    if kind == 'array':
        return [seed(schema['items']) for _ in range(schema.get('minItems', 0))]
    return {'string': '', 'boolean': False, 'integer': schema.get('minimum', 0),
            'number': max(0, schema.get('minimum', 0))}[kind]


class Controller:
    def __init__(self, cli, state_dir):
        self.cli = Path(cli).resolve()
        self.home = Path(state_dir).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.schema = self.query(['config', 'schema'])[-1]
        self.kind, self.inputs, self.output = '', [], ''
        self.config = {'schema_version': 2}
        self.options = {'dpi': 300, 'jobs': 1, 'page_size': 'original', 'pages': 'all', 'stage': 'output', 'review_policy': 'preserve',
                        'max_angle': 8, 'min_page_ratio': .8, 'existing_output': 'reject'}
        self.revision = 0
        self.preview = None
        self.process = None
        self.status = 'idle'
        self.last = None
        self.lines = []
        self.lock = threading.Lock()
        self.progress = {'current': '', 'done': 0, 'total': 0, 'stage': '', 'started': 0}

    def query(self, args):
        result = subprocess.run([str(self.cli), *map(str, args)], capture_output=True, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            raise ValueError((result.stderr + '\n' + result.stdout)[-6000:])
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    def invalidate(self):
        if self.running:
            raise ValueError('Task running; wait for completion before editing')
        self.revision += 1
        self.preview = None

    def select(self, kind, paths):
        resolved = [str(Path(p).resolve(strict=True)) for p in paths]
        if not resolved or len({p.casefold() for p in resolved}) != len(resolved):
            raise ValueError('Select distinct existing files')
        if kind == 'project' and (len(resolved) != 1 or Path(resolved[0]).suffix.lower() != '.scan'):
            raise ValueError('Choose one .scan project')
        suffixes = {'.pdf'} if kind == 'pdf' else {'.png', '.tif', '.tiff', '.jpg', '.jpeg', '.bmp'}
        if kind != 'project' and any(Path(p).suffix.lower() not in suffixes for p in resolved):
            raise ValueError('Unsupported input type')
        self.invalidate()
        self.kind, self.inputs = kind, resolved
        # Stable IDs, page numbers and geometric coordinates belong to old sources.
        self.config = {'schema_version': 2, **({'image_encoding': self.config['image_encoding']} if 'image_encoding' in self.config else {})}
        self.options['pages'] = 'all'

    def apply(self, config):
        validate(self.schema, config)
        image_encoding.resolve(config.get("image_encoding", {}))
        for rule in config.get('rules', []):
            if not rule['select'] or not rule['settings']:
                raise ValueError('Rules require a nonempty scope and settings')
            if {'input', 'orientation', 'split'} & set(rule['settings']):
                if set(rule['select']) - {'images', 'image_ids'}:
                    raise ValueError('Source settings require images/image_ids scope only')
        self.invalidate()
        self.config = copy.deepcopy(config)

    @property
    def running(self):
        return self.process is not None and self.status in ('running', 'cancelling')

    def new_folder(self):
        folder = self.home / uuid.uuid4().hex
        folder.mkdir()
        return folder

    def source_args(self, folder):
        if not self.inputs:
            raise ValueError('Choose input first')
        if self.kind == 'project':
            return ['--project', self.inputs[0]]
        manifest = folder / 'inputs.json'
        write_json(manifest, {'schema_version': 1, 'files': self.inputs})
        return ['--manifest', str(manifest)]

    def start(self, command='process', resume=False, sample=False):
        if self.running:
            raise ValueError('A task is already running')
        if resume:
            if not self.last or not self.last.get('resumable'):
                raise ValueError('No resumable task selected')
            job = copy.deepcopy(self.last)
            args = job['args'][:]
            args = [arg for arg in args if arg != '--overwrite']
            if '--resume' not in args:
                args.append('--resume')
            self.launch(job, args)
            return
        if not self.inputs:
            raise ValueError('Choose input first')
        if command == 'process' and not self.output:
            raise ValueError('Choose output directory first')
        validate(self.schema, self.config)
        image_encoding.resolve(self.config.get("image_encoding", {}))
        folder = self.new_folder()
        config = folder / 'settings.json'
        write_json(config, self.config)
        output = Path(self.output).resolve() if command == 'process' else folder / command
        args = [str(self.cli), command, *self.source_args(folder), '--config', str(config), '--output', str(output),
                '--jobs', str(self.options['jobs']), '--pages', 'sample' if sample else self.options['pages'], '--review-policy', self.options['review_policy'],
                '--max-angle', str(self.options['max_angle']), '--min-page-ratio', str(self.options['min_page_ratio']), '--html']
        if self.kind != 'project':
            args += ['--dpi', str(self.options['dpi'])]
        if command == 'preview':
            args += ['--stage', self.options['stage']]
        if command == 'analyze':
            args += ['--through', self.options['stage']]
        if self.kind == 'pdf':
            args = [sys_executable(), str(self.cli.parent / 'process_pdf_folder.py'), '--cli', str(self.cli),
                    '--pdf-manifest', str(folder / 'inputs.json'), '--output-dir', str(output), '--config', str(config),
                    '--dpi', str(self.options['dpi']), '--jobs', str(self.options['jobs']), '--page-size', self.options['page_size'],
                    '--command', command, '--stage', self.options['stage'], '--review-policy', self.options['review_policy'],
                    '--max-angle', str(self.options['max_angle']), '--min-page-ratio', str(self.options['min_page_ratio'])]
            if sample:
                args += ['--sample']
        if command == 'process' and self.options['existing_output'] == 'overwrite':
            args += ['--overwrite']
        job = {'folder': str(folder), 'output': str(output), 'args': args, 'revision': self.revision,
               'command': command, 'resumable': True, 'status': 'running'}
        self.launch(job, args)

    def launch(self, job, args):
        if self.running:
            raise ValueError('A task is already running')
        write_json(Path(job['folder']) / 'job.json', job)
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        self.process, self.last, self.status = process, job, 'running'
        self.lines = []
        self.progress = {'current': '', 'done': 0, 'total': 0, 'stage': '', 'started': time.monotonic()}
        threading.Thread(target=self._read, args=(process, job), daemon=True).start()

    def _read(self, process, job):
        with process.stdout, (Path(job['folder']) / 'events.log').open('a', encoding='utf-8') as log:
            for line in process.stdout:
                log.write(line)
                log.flush()
                with self.lock:
                    self.lines.append(line.rstrip())
                    del self.lines[:-200]
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    name = event.get('event', '')
                    if name == 'phase_started':
                        self.progress.update(done=0, total=event.get('total', 0), stage=event.get('stage', ''))
                    elif name == 'pdf_started':
                        self.progress.update(current=event.get('input', ''), done=0, total=0, stage='正在打开 PDF')
                    elif name == 'page_rendered':
                        self.progress.update(current=event.get('input', ''), done=event.get('page', 0), total=event.get('total', 0), stage='准备预览图片')
                    elif name == 'page_started':
                        self.progress.update(current=event.get('input', self.progress['current']))
                    elif name in ('page_finished', 'page_reused'):
                        self.progress['done'] = event.get('completed', self.progress['done'] + 1)
                    elif name == 'processing':
                        self.progress.update(stage='图像处理与布局分析', done=0, total=0)
        code = process.wait()
        if code in (0, 1) and job['command'] == 'preview':
            try:
                from .preview import build_viewer
                build_viewer(job['output'])
            except (OSError, ValueError, KeyError) as error:
                with self.lock:
                    self.lines.append('预览对比页生成失败：' + str(error))
        state = 'cancelled' if code == 130 else {0: 'complete', 1: 'review / partial failure'}.get(code, 'failed')
        job.update(status=state, exit_code=code)
        write_json(Path(job['folder']) / 'job.json', job)
        with self.lock:
            self.status = state
            if code in (0, 1) and job['command'] == 'preview':
                self.preview = (job['revision'], job['output'])

    def cancel(self):
        with self.lock:
            if self.running and self.status != 'cancelling' and self.process.poll() is None:
                self.status = 'cancelling'
                try:
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                except ProcessLookupError:
                    pass  # Reader publishes the terminal status after pipe EOF.

    def history(self):
        result = []
        for path in self.home.glob('*/job.json'):
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
                result.append((path.stat().st_mtime, value))
            except (OSError, ValueError):
                continue
        return [v for _, v in sorted(result, key=lambda x: x[0], reverse=True)]


def sys_executable():
    import sys
    return sys.executable
