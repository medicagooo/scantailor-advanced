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
from .persistence import digest, identity, portable_config, output_inventory, verified, outcome_complete, differences


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temp, path)


def elapsed_seconds(progress):
    """Monotonic run duration; a finalized run never accrues idle UI time."""
    started = progress.get('started', 0)
    if not started:
        return 0
    finished = progress.get('finished')
    return max(0, (time.monotonic() if finished is None else finished) - started)


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
                        'max_angle': 8, 'min_page_ratio': .8, 'existing_output': 'reject', 'sample_pages': 'sample'}
        self.default_options = copy.deepcopy(self.options)
        self.revision = 0
        self.preview = None
        self.process = None
        self.status = 'idle'
        self.last = None
        self.lines = []
        self.lock = threading.Lock()
        self.progress = {'current': '', 'done': 0, 'total': 0, 'stage': '', 'started': 0, 'finished': None}

        self.preference_error = ''
        self.preferences_path = self.home / 'settings.json'
        try:
            if self.preferences_path.exists():
                saved = json.loads(self.preferences_path.read_text(encoding='utf-8-sig'))
                if saved.get('schema_version') != 1: raise ValueError('Unsupported settings version')
                validate(self.schema, saved['config'])
                self.config = portable_config(saved['config'])
                image_encoding.resolve(self.config.get('image_encoding', {}))
                self.update_options(saved.get('options', {}), persist=False)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.config = {'schema_version': 2}
            self.options = copy.deepcopy(self.default_options)
            self.preference_error = '已保存设置无法读取，使用默认值：' + str(error)

    def save_preferences(self):
        write_json(self.preferences_path, {'schema_version': 1, 'config': portable_config(self.config),
                   'options': {k: v for k, v in self.options.items() if k not in ('pages', 'existing_output', 'sample_pages')}})

    def update_options(self, values, persist=True):
        if set(values) - set(self.default_options): raise ValueError('Unknown run options')
        updated = {**self.options, **values}
        if updated['stage'] not in ('orientation','split','deskew','content','layout','output'): raise ValueError('Invalid stage')
        if updated['existing_output'] not in ('reject','overwrite'): raise ValueError('Invalid overwrite policy')
        for key in ('max_angle','min_page_ratio'):
            value = updated[key]
            if type(value) not in (int,float) or not math.isfinite(value) or not (0 if key == 'max_angle' else .1) <= value <= (45 if key == 'max_angle' else 1):
                raise ValueError('Invalid review threshold')
        for key, low, high in [('dpi',72,1200), ('jobs',1,16)]:
            if type(updated[key]) is not int or not low <= updated[key] <= high:
                raise ValueError(key + ' out of range')
        if updated['page_size'] not in ('original','processed') or updated['review_policy'] not in ('preserve','report'):
            raise ValueError('Invalid run options')
        if persist: self.invalidate()
        previous_dpi = self.options["dpi"]
        self.options = updated
        # A scalar input-DPI edit replaces a global input override, not page rules.
        if 'dpi' in values and values['dpi'] != previous_dpi and persist:
            self.config.get('defaults', {}).get('input', {}).pop('dpi', None)
        if persist: self.save_preferences()

    def input_dpi(self):
        value = self.config.get('defaults', {}).get('input', {}).get('dpi')
        if value and self.kind == 'pdf' and value[0] != value[1]:
            raise ValueError('PDF 渲染 DPI 的横纵值必须相同')
        return value or [self.options['dpi'], self.options['dpi']]

    def dpi_summary(self, section):
        if any(section in rule.get('settings', {}) and 'dpi' in rule['settings'][section] for rule in self.config.get('rules', [])):
            return '按页配置'
        value = self.config.get('defaults', {}).get(section, {}).get('dpi')
        if value:
            return str(value[0]) if value[0] == value[1] else f'{value[0]}×{value[1]}'
        if self.kind == 'project': return '沿用项目'
        return str(self.options['dpi']) if section == 'input' else '跟随输入'

    def plan(self, command='process', sample=False):
        if not self.inputs: raise ValueError('Choose input first')
        if not self.output: raise ValueError('Choose output directory first')
        if sample and self.config.get('rules'):
            raise ValueError('快速抽样暂不支持按页规则，请选择指定阶段精确预览；执行前将确认全项目分析。')
        sources = [{'path': str(p), 'sha256': digest(p)} for p in self.inputs]
        dependencies = []
        if self.kind == 'project':
            inspected = self.query(['pages', 'list', '--project', self.inputs[0]])[-1]
            if inspected.get('import_errors'): raise ValueError('项目源图无法读取，请先修复路径')
            dependencies = [{'path': p, 'sha256': digest(p)} for p in dict.fromkeys(page['input'] for page in inspected['pages'])]
        request = {'kind': self.kind, 'inputs': sources, 'dependencies': dependencies,
                   'config': self.config, 'options': {k:v for k,v in self.options.items() if k not in ('existing_output','jobs')},
                   'command': command, 'sample': sample, 'cli': digest(self.cli),
                   'scripts': {str(p): digest(p) for p in list(self.cli.parent.glob('*.py')) + list(Path(__file__).parent.glob('*.py'))},
                   'output': str(Path(self.output).resolve())}
        counts = []
        if self.kind == 'pdf':
            import pymupdf
            for path in self.inputs:
                with pymupdf.open(path) as document: counts.append(document.page_count)
        elif self.kind == 'project':
            counts = [len({(page['input'], page.get('image_page', 0)) for page in inspected['pages']})]
        else:
            from PIL import Image
            total = 0
            for path in self.inputs:
                with Image.open(path) as image: total += getattr(image, 'n_frames', 1)
            counts = [total]
        selected = []
        for count in counts:
            if sample:
                expression = self.options['sample_pages']
                numbers = {1, count // 2 + 1, count} if expression == 'sample' else {int(v.strip()) for v in expression.split(',')}
                if not numbers or min(numbers) < 1 or max(numbers) > count: raise ValueError('快速预览源页超出范围')
                selected.append(len(numbers))
            else: selected.append(count)
        key = identity(request)
        candidates = self.history()
        match = next((job for job in candidates if job.get('identity') == key), None)
        conflict = next((job for job in candidates if job.get('requested_output') == request['output'] and job.get('command') == command), None)
        return {'identity': key, 'request': request, 'match': match, 'conflict': conflict,
                'valid': bool(match and verified(match)), 'command': command, 'sample': sample,
                'source_count': sum(counts), 'selected_count': sum(selected),
                'changes': differences(conflict.get('snapshot', {}) if conflict else {}, request)}

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
        if not self.output: self.output = str(Path(resolved[0]).parent / 'scantailor-output')
        # Stable IDs, page numbers and geometric coordinates belong to old sources.
        self.config = portable_config(self.config) if kind != 'project' else {'schema_version': 2}
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
        dpi = config.get('defaults', {}).get('input', {}).get('dpi')
        if dpi and dpi[0] == dpi[1]: self.options['dpi'] = dpi[0]
        self.save_preferences()

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

    def start(self, command='process', resume=False, sample=False, decision=None):
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
        plan = self.plan(command, sample)
        folder = Path(self.output).resolve() / '_scantailor' / 'tasks' / plan['identity']
        if plan['match'] and decision != 'overwrite':
            self.last = plan['match']
            return self.start(resume=True)
        folder.mkdir(parents=True, exist_ok=True)
        config = folder / 'settings.json'
        write_json(config, self.config)
        output = Path(self.output).resolve() if command == 'process' and self.kind == 'pdf' else Path(self.output).resolve() / '_scantailor' / 'operations' / plan['identity']
        args = [str(self.cli), command, *self.source_args(folder), '--config', str(config), '--output', str(output),
                '--analysis-cache', str(Path(self.output).resolve() / '_scantailor' / 'analysis-cache'),
                '--jobs', str(self.options['jobs']), '--pages', 'all' if sample else self.options['pages'], '--review-policy', self.options['review_policy'],
                '--max-angle', str(self.options['max_angle']), '--min-page-ratio', str(self.options['min_page_ratio']), '--html']
        if self.kind != 'project' and not self.config.get('defaults', {}).get('input', {}).get('dpi') and not any('input' in r.get('settings', {}) for r in self.config.get('rules', [])):
            args += ['--dpi', str(self.options['dpi'])]
        if sample:
            args += ['--source-pages', self.options['sample_pages']]
        if command == 'preview':
            args += ['--stage', self.options['stage']]
        if command == 'analyze':
            args += ['--through', self.options['stage']]
        if self.kind == 'pdf':
            args = [sys_executable(), str(self.cli.parent / 'process_pdf_folder.py'), '--cli', str(self.cli),
                    '--pdf-manifest', str(folder / 'inputs.json'), '--output-dir', str(output), '--config', str(config),
                    '--dpi', str(self.input_dpi()[0]), '--jobs', str(self.options['jobs']), '--page-size', self.options['page_size'],
                    '--command', command, '--stage', self.options['stage'], '--review-policy', self.options['review_policy'],
                    '--max-angle', str(self.options['max_angle']), '--min-page-ratio', str(self.options['min_page_ratio']),
                    '--cache-dir', str(Path(self.output).resolve() / '_scantailor' / 'cache')]
            if sample:
                args += ['--sample', '--source-pages', self.options['sample_pages']]
        if decision == 'overwrite' or (command == 'process' and self.options['existing_output'] == 'overwrite'):
            args += ['--overwrite']
        job = {'folder': str(folder), 'output': str(output), 'args': args, 'revision': self.revision,
               'command': command, 'resumable': True, 'status': 'running', 'identity': plan['identity'],
               'requested_output': str(Path(self.output).resolve()), 'snapshot': plan['request']}
        self.launch(job, args)

    def save_job(self, job):
        write_json(Path(job['folder']) / 'job.json', job)
        if job.get('identity'):
            index = self.home / job['identity']
            index.mkdir(exist_ok=True)
            write_json(index / 'job.json', job)

    def launch(self, job, args):
        if self.running:
            raise ValueError('A task is already running')
        job.update(status='running', outcome_complete=False, artifacts={})
        self.save_job(job)
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        self.process, self.last, self.status = process, job, 'running'
        self.lines = []
        self.progress = {'current': '', 'done': 0, 'total': 0, 'stage': '', 'started': time.monotonic(), 'finished': None}
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
                    if name == 'phase_reused':
                        self.progress.update(done=event.get('total', 0), total=event.get('total', 0), stage=event.get('stage', '') + '（已复用）')
                    elif name == 'phase_started':
                        self.progress.update(done=0, total=event.get('total', 0), stage=event.get('stage', ''))
                    elif name == 'pdf_started':
                        self.progress.update(current=event.get('input', ''), done=0, total=0, stage='正在打开 PDF')
                    elif name in ('page_rendered', 'page_render_reused'):
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
        finished = time.monotonic()
        with self.lock:
            duration = elapsed_seconds({**self.progress, 'finished': finished})
        job.update(status=state, exit_code=code, elapsed_seconds=round(duration, 3))
        if code in (0, 1):
            try:
                job['artifacts'] = output_inventory(job['output'])
                job['outcome_complete'] = outcome_complete(job['output'])
            except (OSError, ValueError):
                job['artifacts'] = {}
                job['outcome_complete'] = False
        self.save_job(job)
        with self.lock:
            # Publish completion only after preview generation and checkpoint save.
            # UI.monitor observes status + frozen duration under this same lock.
            self.progress['finished'] = finished
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
