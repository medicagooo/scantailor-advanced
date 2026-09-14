"""Guided terminal workbench; business commands still use UI/Controller adapters."""
from .i18n import tr, NAMES, language
import copy
import json
import os
import subprocess
from pathlib import Path
import image_encoding
import time
from .editing import parse_paths
from .rendering import Frame, FG, MUTED, ACCENT, WARN

IMAGE = {'.png', '.tif', '.tiff', '.jpg', '.jpeg', '.bmp'}
STATES = {'idle': 'msg_316', 'running': 'msg_317', 'cancelling': 'msg_318',
          'complete': 'msg_319', 'cancelled': 'msg_320', 'failed': 'msg_321',
          'review / partial failure': 'msg_322'}
KINDS = {'pdf': 'msg_323', 'images': 'msg_324', 'project': 'msg_325'}


class Workbench:
    def __init__(self, ui):
        self.ui, self.c, self.m = ui, ui.c, ui.m
        self.focus = 'paste'
        self.scheme = 'msg_326' if self.m.config.get('defaults') else 'msg_327'
        self.suggested_output = ''

    def select(self, kind, paths):
        suggest = not self.m.output or self.m.output == self.suggested_output
        self.m.select(kind, paths)
        parent = Path(paths[0]).resolve().parent
        if suggest:
            target = parent / 'scantailor-output'
            suffix = 2
            while target.exists() and not target.is_dir():
                target = parent / f'scantailor-output-{suffix}'
                suffix += 1
            self.m.output = self.suggested_output = str(target)
        self.scheme = 'msg_017' if kind == 'project' else ('msg_349' if self.m.config.get('defaults') else 'msg_327')
        self.focus = 'preview'

    def collect(self, text, recursive=False):
        paths = parse_paths(text)
        if not paths:
            raise ValueError(tr('msg_350'))
        files, errors = [], []
        excluded = Path(self.m.output).resolve() if self.m.output else None
        for path in paths:
            if path.is_dir():
                candidates = path.rglob('*') if recursive else path.iterdir()
                files.extend(sorted((p.resolve() for p in candidates if p.is_file() and p.suffix.lower() in IMAGE | {'.pdf', '.scan'}
                                     and (excluded is None or not p.resolve().is_relative_to(excluded))), key=lambda p: str(p).casefold()))
            elif path.is_file() and path.suffix.lower() in IMAGE | {'.pdf', '.scan'}:
                files.append(path.resolve())
            else:
                errors.append(f"{tr('msg_445')}{path}")
        unique = {str(p).casefold(): p for p in files}
        files = list(unique.values())
        if errors:
            raise ValueError('\n'.join(errors[:5]))
        if not files:
            raise ValueError(tr('msg_351'))
        kinds = {'pdf' if p.suffix.lower() == '.pdf' else 'project' if p.suffix.lower() == '.scan' else 'images' for p in files}
        if len(kinds) != 1:
            raise ValueError(tr('msg_352'))
        kind = kinds.pop()
        if kind == 'project' and len(files) != 1:
            raise ValueError(tr('msg_353'))
        return kind, files

    def import_paths(self, initial=''):
        text = initial
        while True:
            text = self.c.text(tr('msg_354'), text, tr('msg_355'),
                               multiline=True, validator=lambda t: self.validate_paths(t), apply_label=tr('msg_393'))
            if text is None:
                return
            directories = any(p.is_dir() for p in parse_paths(text))
            recursive = False
            if directories:
                choice = self.c.choose(tr('msg_394'), [tr('msg_427'), tr('msg_428')], tr('msg_395'))
                if choice is None:
                    continue
                recursive = choice == 1
            try:
                kind, files = self.collect(text, recursive)
            except (ValueError, OSError) as error:
                self.ui.message(tr('msg_429'), error)
                continue
            choice = self.c.choose(f"{tr('msg_396')}{len(files)}{tr('msg_397')}{tr(KINDS[kind])}", [tr('msg_430'), tr('msg_431')] + [str(p) for p in files],
                                   tr('msg_356'))
            if choice == 0:
                self.select(kind, files)
                return
            if choice is None:
                return

    @staticmethod
    def validate_paths(text):
        paths = parse_paths(text)
        if not paths:
            raise ValueError(tr('msg_357'))
        invalid = [str(p) for p in paths if not p.exists()]
        if invalid:
            raise ValueError(tr('msg_398') + invalid[0])

    def output(self):
        def validate(text):
            paths = parse_paths(text)
            if len(paths) != 1:
                raise ValueError(tr('msg_399'))
            path = paths[0].resolve()
            if path.exists() and not path.is_dir():
                raise ValueError(tr('msg_400'))
            if any(Path(p).resolve().is_relative_to(path) for p in self.m.inputs):
                raise ValueError(tr('msg_401'))
        choice = self.c.choose(tr('msg_328'), [tr('msg_358'), tr('msg_359')], tr('msg_329'))
        if choice == 0:
            text = self.c.text(tr('msg_360'), self.m.output, tr('msg_361'), validator=validate)
            if text is not None:
                self.m.invalidate()
                self.m.output = str(parse_paths(text)[0].resolve())
        elif choice == 1:
            folders = self.ui.browse(directory=True)
            if folders:
                validate(str(folders[0]))
                self.m.invalidate()
                self.m.output = str(folders[0])

    def common(self):
        draft = copy.deepcopy(self.m.config)
        defaults = draft.setdefault('defaults', {})
        fields = [(tr('msg_362'), 'deskew', 'mode', ['auto', 'off'], [tr('msg_402'), tr('msg_403')]),
                  (tr('msg_363'), 'split', 'layout', ['single', 'auto', 'two'], [tr('msg_404'), tr('msg_405'), tr('msg_406')]),
                  (tr('msg_364'), 'output', 'mode', ['colorOrGray', 'bw', 'mixed'], [tr('msg_058'), tr('msg_407'), tr('msg_408')]),
                  (tr('msg_447') if self.m.kind == 'pdf' else tr('msg_035'), 'input', 'dpi', [[150, 150], [300, 300], [600, 600]], ['150', '300', '600']),
                  (tr('msg_365'), 'output', 'dpi', [[150, 150], [300, 300], [600, 600]], [tr('msg_409'), tr('msg_410'), tr('msg_411')])]
        while True:
            labels = []
            for name, section, key, values, names in fields:
                current = defaults.get(section, {}).get(key)
                description = names[values.index(current)] if current in values else tr('msg_412')
                if section == 'input':
                    description = ('×'.join(map(str, current)) if current and current[0] != current[1]
                                   else str(current[0]) if current else
                                   tr('msg_017') if self.m.kind == 'project' else str(self.m.options['dpi']))
                    if any('dpi' in rule.get('settings', {}).get('input', {}) for rule in draft.get('rules', [])):
                        description += ' · ' + tr('common.input_dpi.rules')
                labels.append(f'{name}    {description}')
            index = self.c.choose(tr('msg_346'), labels + [tr('msg_432'), tr('msg_433'), tr('msg_434'), tr('msg_435'), tr('msg_436')],
                                  tr('msg_366'))
            if index is None or index == len(fields) + 3:
                return
            if index == len(fields) + 4:
                value = self.encoding(draft.get('image_encoding', {}))
                if value is not None:
                    draft['image_encoding'] = value
            elif index < len(fields):
                name, section, key, values, names = fields[index]
                if section == 'input':
                    selected = self.c.choose(name, names + [tr('common.input_dpi.custom')],
                                             tr('common.input_dpi.pdf_hint' if self.m.kind == 'pdf' else 'common.input_dpi.image_hint'))
                    if selected == len(values):
                        current = defaults.get('input', {}).get('dpi')
                        ok, value = self.ui.edit(name, {'type': 'integer', 'minimum': 72, 'maximum': 1200},
                                                 current[0] if current else self.m.options['dpi'])
                        if ok:
                            # Controller.apply persists this global override and synchronizes
                            # PDF rendering options; source-page rules remain untouched.
                            defaults.setdefault('input', {})['dpi'] = [value, value]
                        continue
                else:
                    selected = self.c.choose(name, names)
                if selected is not None:
                    defaults.setdefault(section, {})[key] = values[selected]
                    if section == 'deskew' and key == 'mode':
                        defaults[section].pop('angle', None)
            elif index == len(fields):
                ok, value = self.ui.edit(tr('msg_114'), {'type': 'number', 'minimum': 0, 'maximum': 100},
                                         defaults.get('layout', {}).get('margins_mm', {}).get('left', 0))
                if ok:
                    defaults.setdefault('layout', {})['margins_mm'] = {k: value for k in ('left', 'right', 'top', 'bottom')}
                    defaults['layout']['auto_margins'] = False
            elif index == len(fields) + 1:
                selected = self.c.choose(tr('msg_449'), [tr('msg_450'), tr('msg_451')])
                if selected is not None:
                    # Kept in this form draft until Apply, like processing settings.
                    draft_policy = ['preserve', 'report'][selected]
                    draft['_menu_policy'] = draft_policy
            elif index == len(fields) + 2:
                policy = draft.pop('_menu_policy', self.m.options['review_policy'])
                self.m.apply(draft)
                self.m.update_options({'review_policy': policy})
                self.scheme = 'msg_349'
                return

    def encoding(self, current):
        draft = image_encoding.resolve(current)
        while True:
            fmt = draft['format']
            key = {'png': 'png_compression', 'tiff': 'tiff_compression', 'jpeg': 'jpeg_quality'}[fmt]
            label = {'png': tr('msg_413'), 'tiff': tr('msg_414'), 'jpeg': tr('msg_415')}[fmt]
            value = draft[key]
            display = {'none': tr('msg_437'), 'lzw': 'LZW', 'deflate': 'Deflate'}.get(value, str(value))
            hint = tr('msg_367') if fmt == 'png' else tr('msg_416') if fmt == 'tiff' else tr('msg_417')
            choice = self.c.choose(tr('msg_090'), [tr('msg_438') + fmt.upper(), label + '    ' + display, tr('msg_418'), tr('msg_004')], hint)
            if choice is None or choice == 3:
                return None
            if choice == 0:
                selected = self.c.choose(tr('msg_091'), [tr('msg_439'), tr('msg_440'), tr('msg_441')])
                if selected is not None:
                    draft = image_encoding.resolve(draft, {'format': ['png', 'tiff', 'jpeg'][selected]})
            elif choice == 1:
                if fmt == 'tiff':
                    selected = self.c.choose(tr('msg_446'), [tr('msg_437'), 'LZW', 'Deflate'])
                    if selected is not None: draft[key] = ['none', 'lzw', 'deflate'][selected]
                else:
                    ok, value = self.ui.edit(label, {'type': 'integer', 'minimum': 0 if fmt == 'png' else 1, 'maximum': 9 if fmt == 'png' else 100}, draft[key])
                    if ok: draft[key] = value
            elif choice == 2:
                return image_encoding.resolve(draft)

    def schemes(self):
        choice = self.c.choose(tr('msg_330'), [tr('msg_368'), tr('msg_369'), tr('msg_370'), tr('msg_371'), tr('msg_372')])
        if choice in (0, 1):
            config = {'schema_version': 2, 'preset': 'physics-safe', 'image_encoding': self.m.config.get('image_encoding', {})}
            if choice == 1:
                config['defaults'] = {'output': {'mode': 'bw'}}
            self.m.apply(config)
            self.m.update_options({'review_policy': 'preserve'})
            self.scheme = ['msg_327', 'msg_419'][choice]
        elif choice == 2:
            self.common()
        elif choice == 3:
            self.advanced()
        elif choice == 4:
            self.ui.presets()
            self.scheme = 'msg_349'

    def advanced(self):
        choice = self.c.choose(tr('msg_331'), [tr('msg_373'), tr('msg_374'), tr('msg_375'), tr('msg_376'), tr('msg_372'), tr('language.title')],
                               tr('msg_332'))
        if choice == 0:
            ok, config = self.ui.edit(tr('msg_377'), self.m.schema, self.m.config)
            if ok:
                self.m.apply(config)
                self.scheme = 'msg_349'
        elif choice == 1:
            self.ui.options()
        elif choice in (2, 3):
            self.ui.execute('analyze' if choice == 2 else 'preview')
        elif choice == 4:
            self.ui.presets()
        elif choice == 5:
            self.ui.choose_language()

    def frame(self, width, height):
        frame = Frame(width, height)
        if width < 54 or height < 22:
            frame.text(2, 2, tr('msg_378'), ACCENT)
            frame.text(2, 4, tr('msg_379'), MUTED)
            return frame, []
        running = self.m.running
        ready = bool(self.m.inputs and self.m.output)
        controls = []
        def button(x, y, w, title, key, enabled=True):
            frame.button(x, y, w, title, key, self.focus == key, enabled)
            if enabled:
                controls.append(key)
        wide = width >= 104 and height >= 28
        main_width = int(width * .63) if wide else width - 5
        frame.text(3, 1, tr('msg_333'), ACCENT)
        if width >= 104:
            frame.text(width - 43, 1, tr('msg_380'), MUTED, 40)
        button(3, 3, 14, tr('msg_334'), 'home')
        button(18, 3, 12, tr('workbench.project'), 'project', not running and bool(self.m.inputs))
        button(31, 3, 12, tr('msg_336'), 'history', not running)
        button(44, 3, 8, tr('msg_337'), 'help')
        frame.rule(3, 4, width - 7)
        frame.text(4, 6, tr('msg_338'), ACCENT)
        desc = f"{tr(KINDS.get(self.m.kind, ''))} · {tr('count.files', count=len(self.m.inputs))}" if self.m.inputs else tr('msg_339')
        frame.text(5, 7, desc, FG, main_width - 5)
        if wide:
            frame.text(5, 8, str(self.m.inputs[0]) if self.m.inputs else tr('msg_420'), MUTED, main_width - 5)
        y = 9 if wide else 8
        button(4, y, 16, tr('msg_340'), 'paste', not running)
        button(21, y, 15, tr('msg_341'), 'browse', not running)
        button(36, y, 16, tr('msg_342'), 'folder', not running)
        oy = 12 if wide else 10
        frame.text(4, oy, tr('msg_343'), ACCENT)
        frame.text(5, oy + 1, self.m.output or tr('msg_382'), MUTED, main_width - 5)
        button(4, oy + 2, 20, tr('msg_344'), 'output', not running)
        sy = 17 if wide else 14
        frame.text(4, sy, tr('msg_345'), ACCENT)
        scheme = tr('msg_017') if self.m.kind == 'project' and self.m.config == {'schema_version': 2} else tr(self.scheme)
        editable = not running and bool(self.m.inputs)
        button(4, sy + 1, 22, scheme + '  ▾', 'scheme', editable)
        button(26, sy + 1, 12, tr('workbench.common'), 'common', editable)
        button(39, sy + 1, min(18, width - 40), tr('workbench.advanced'), 'advanced', not running)
        if wide:
            frame.text(5, sy + 3, tr('msg_383'), MUTED, main_width - 5)
            x = main_width + 3
            for row in range(6, height - 7):
                frame.text(main_width, row, '│', MUTED)
            frame.rule(x, 6, width - x - 4, tr('msg_384'))
            current = self.m.running or (self.m.last and self.m.last.get('revision') == self.m.revision)
            status = tr(STATES.get(self.m.status, self.m.status)) if current else (tr('msg_421') if ready else tr('msg_316'))
            frame.text(x + 1, 8, status, ACCENT, width - x - 4)
            frame.text(x + 1, 10, f"""{tr('msg_447') if self.m.kind == "pdf" else tr('msg_035')}     {self.m.input_dpi()[0] if self.m.kind == "pdf" else self.m.dpi_summary("input")}""", FG)
            frame.text(x + 1, 11, f"{tr('msg_422')}{self.m.dpi_summary('output')}", FG)
            frame.text(x + 1, 12, tr('overview.workers', count=self.m.options['jobs']), FG)
            frame.text(x + 1, 14, tr('msg_424') + (tr('msg_442') if self.m.options['review_policy'] == 'preserve' else tr('msg_443')), FG)
            encoding = image_encoding.resolve(self.m.config.get('image_encoding', {}))
            compression = next(v for k, v in encoding.items() if k != 'format')
            frame.text(x + 1, 16, f"{tr('msg_425')}{encoding['format'].upper()} · {compression}", FG, width - x - 4)
            frame.text(x + 1, 17, tr('msg_385'), ACCENT)
            frame.text(x + 1, 19, tr('msg_386'), MUTED)
            frame.text(x + 1, 20, tr('msg_387'), MUTED)
        by = height - 5
        frame.rule(3, by - 1, width - 7)
        button(4, by, 18, tr('msg_388') if running else tr('msg_389'), 'progress' if running else 'preview', running or bool(self.m.inputs))
        button(23, by, 18, tr('msg_390') if running else tr('msg_391'), 'start', ready and not running)
        button(42, by, 12, tr('msg_347'), 'exit')
        if not ready and not running:
            frame.text(4, by + 1, tr('msg_392'), MUTED)
        frame.text(3, height - 2, tr('msg_348'), MUTED)
        return frame, controls

    def run(self):
        self.c.flush()
        while True:
            width, height = self.c.dimensions()
            frame, controls = self.frame(width, height)
            if controls and self.focus not in controls:
                self.focus = controls[0]
                frame, controls = self.frame(width, height)
            self.c.draw(frame)
            event = self.c.read()
            if not event:
                continue
            action, data = event
            key = None
            if action == 'escape':
                key = 'exit'
            elif action in ('tab', 'up', 'down', 'left', 'right') and controls:
                index = controls.index(self.focus)
                delta = -1 if action in ('up', 'left') or (action == 'tab' and data) else 1
                self.focus = controls[(index + delta) % len(controls)]
            elif action in ('enter', 'space'):
                key = self.focus if self.focus in controls else None
            elif action in ('click', 'hover'):
                hit = frame.hit(data)
                if hit is not None:
                    self.focus = hit
                    if action == 'click':
                        key = hit
            if key:
                try:
                    if key == 'exit':
                        if self.m.running:
                            self.ui.monitor()
                        else:
                            return 0
                    else:
                        self.dispatch(key)
                except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
                    self.ui.message(tr('msg_448'), error)
                self.c.flush()

    def dispatch(self, key):
        if key == 'paste':
            self.import_paths()
        elif key == 'browse':
            choice = self.c.choose(tr('msg_426'), [tr('msg_323'), tr('msg_324'), tr('msg_444')])
            if choice is not None:
                files = self.ui.browse([{'.pdf'}, IMAGE, {'.scan'}][choice], multi=choice != 2)
                if files:
                    self.select(['pdf', 'images', 'project'][choice], files)
        elif key == 'folder':
            paths = self.ui.browse(directory=True)
            if paths:
                self.import_paths(str(paths[0]))
        elif key == 'output':
            self.output()
        elif key == 'scheme':
            self.schemes()
        elif key == 'common':
            self.common()
        elif key == 'advanced':
            self.advanced()
        elif key == 'preview':
            self.ui.execute('preview', sample=True)
        elif key == 'start':
            self.ui.execute()
        elif key == 'progress':
            self.ui.monitor()
        elif key == 'project':
            self.ui.project()
        elif key == 'history':
            jobs = self.m.history()
            index = self.c.choose(tr('msg_336'), [f'{tr(STATES.get(j.get("status"), j.get("status")))} · {j.get("output")}' for j in jobs], tr('msg_452'))
            if index is not None:
                self.m.last = jobs[index]
                self.ui.results()
        elif key == 'help':
            self.ui.message(tr('msg_453'), tr('msg_454'))
