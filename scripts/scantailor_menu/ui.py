"""Menu adapters for schema-2 settings and CLI project/page commands.

All edits are local drafts until Apply. Project mutations save a new project
inside the menu job store and adopt it only after the native validator succeeds.
"""
from __future__ import annotations
from .i18n import tr, LANGUAGES, NAMES, language
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .console import Console
from .model import Controller, seed, validate, write_json, elapsed_seconds

LABELS = {'defaults': 'msg_031', 'project': 'msg_032', 'rules': 'msg_033', 'preset': 'msg_034',
          'input': 'msg_035', 'orientation': 'msg_036', 'split': 'msg_037', 'deskew': 'msg_038',
          'content': 'msg_039', 'layout': 'msg_040', 'output': 'msg_041',
          'picture_zones': 'msg_042', 'fill_zones': 'msg_043', 'select': 'msg_044', 'settings': 'msg_045',
          'reading_direction': 'msg_046', 'dpi': 'DPI', 'jobs': 'msg_047', 'pages': 'msg_048',
          'stage': 'msg_049', 'page_size': 'msg_050', 'review_policy': 'msg_051'}
LABELS.update({stage: 'stage.' + stage for stage in ('orientation','split','deskew','content','layout')})
LABELS['sample_pages'] = 'msg_030'
LABELS.update(dict(image_encoding='msg_090', format='msg_091', png_compression='msg_092', tiff_compression='msg_093', jpeg_quality='msg_094'))
LABELS.update(dict(rotation='msg_095', trim='msg_096', enabled='msg_097', left='msg_098', right='msg_099', top='msg_100', bottom='msg_101',
                  mode='msg_102', angle='msg_103', oblique_mode='msg_104', oblique_angle='msg_105',
                  space='msg_106', cutters='msg_107', page_mode='msg_108', content_mode='msg_109', page_rect='msg_110',
                  content_rect='msg_111', basis='msg_112', fine_tune='msg_113', margins_mm='msg_114',
                  match_size='msg_115', auto_margins='msg_116', horizontal='msg_117', vertical='msg_118',
                  points='msg_119', color='msg_120', layer='msg_121', category='msg_122',
                  threshold_method='msg_123', threshold='msg_124', threshold_window='msg_125', despeckle='msg_126',
                  dewarp='msg_127', distortion_model='msg_128', depth='msg_129', top_spline='msg_130', bottom_spline='msg_131',
                  point='msg_132', tension='msg_133', fill_color='msg_134', fill_margins='msg_135', fill_offcut='msg_136',
                  fill_outside_page='msg_137', normalize_bw='msg_138', normalize_color='msg_139',
                  black_on_white='msg_140', morphological_smoothing='msg_141', savitzky_golay='msg_142',
                  wiener_window='msg_143', wiener_coefficient='msg_144', posterize='msg_145', posterize_level='msg_146',
                  posterize_normalize='msg_147', posterize_force_bw='msg_148', color_segmentation='msg_149',
                  segment_noise='msg_150', segment_red='msg_151', segment_green='msg_152', segment_blue='msg_153',
                  split_output='msg_154', foreground='msg_155', original_background='msg_156',
                  picture_shape='msg_157', picture_sensitivity='msg_158', picture_high_sensitivity='msg_159',
                  sauvola_coefficient='msg_160', wolf_coefficient='msg_161', wolf_lower='msg_162', wolf_upper='msg_163',
                  post_deskew='msg_164', post_deskew_angle='msg_165', deskew_algorithm='msg_166',
                  freeze_layout='msg_167', frozen_size_mm='msg_168', guides='msg_169', position='msg_170',
                  page_detection_size_mm='msg_171', page_detection_tolerance='msg_172', show_middle_rect='msg_173',
                  images='msg_174', ids='msg_175', image_ids='msg_176', parity='msg_177', side='msg_178',
                  max_angle='msg_179', min_page_ratio='msg_180', existing_output='msg_181'))
VALUES = dict(auto='msg_052', off='msg_053', manual='msg_054', single='msg_055', two='msg_056', cut='msg_057',
              colorOrGray='msg_058', bw='msg_059', mixed='msg_060', source='msg_061', oriented='msg_062',
              deskew='msg_063', ltr='msg_064', rtl='msg_065', preserve='msg_066', report='msg_067',
              original='msg_068', processed='msg_069', reject='msg_070', overwrite='msg_071',
              odd='msg_072', even='msg_073', left='msg_074', right='msg_075', center='msg_076', top='msg_077', bottom='msg_078',
              horizontal='msg_079', vertical='msg_080', white='msg_081', black='msg_082', background='msg_083', foreground='msg_084',
              rectangular='msg_085', free='msg_086', noop='msg_087', picture='msg_042', marginal='msg_088', color='msg_089')
IMAGE = {'.png', '.tif', '.tiff', '.jpg', '.jpeg', '.bmp'}


def label(key):
    return tr(LABELS.get(key, key))


def summary(value, field=None):
    if field in ('stage', 'through') and isinstance(value, str):
        return tr('stage.' + value)
    if isinstance(value, dict):
        return '、'.join(label(k) for k in value) or tr('msg_182')
    if isinstance(value, list):
        return f"{len(value)}{tr('msg_189')}" + str(value)[:70]
    if type(value) is bool:
        return tr('msg_183') if value else tr('msg_053')
    return tr(VALUES.get(value, str(value)))


class UI:
    def __init__(self, console, controller):
        self.c, self.m = console, controller
        self.folder = Path.home()

    def message(self, title, text):
        self.c.choose(title, str(text).splitlines() + [tr('msg_227')])

    def browse(self, suffixes=None, multi=False, directory=False):
        folder, chosen = self.folder, []
        while True:
            try:
                entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
                entries = [p for p in entries if p.is_dir() or (not directory and p.suffix.lower() in suffixes)]
            except OSError as error:
                self.message(tr('msg_266'), error)
                folder = Path.home()
                continue
            rows = [tr('msg_228') if directory else f"{tr('msg_267')}{len(chosen)}{tr('msg_268')}",
                    tr('msg_190'), tr('msg_191'), tr('msg_192'), tr('msg_193'), tr('msg_194'), tr('msg_195')]
            rows += [('▸ ' if p.is_dir() else ('[✓] ' if p in chosen else '[ ] ')) + p.name for p in entries]
            index = self.c.choose(str(folder), rows, tr('msg_196'))
            if index is None:
                return None
            if index == 0:
                if directory or chosen:
                    self.folder = folder
                    return [folder] if directory else chosen
            elif index == 1:
                text = self.c.text(tr('msg_269'), str(folder))
                if text:
                    p = Path(text.strip('"')).expanduser()
                    if p.is_dir():
                        folder = p.resolve()
                    elif not directory and p.is_file() and p.suffix.lower() in suffixes:
                        if not multi:
                            return [p.resolve()]
                        if p.resolve() not in chosen:
                            chosen.append(p.resolve())
                    else:
                        self.message(tr('msg_293'), tr('msg_294'))
            elif index == 2:
                drives = [Path(f'{c}:/') for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' if Path(f'{c}:/').exists()]
                choice = self.c.choose(tr('msg_277'), [str(p) for p in drives])
                if choice is not None:
                    folder = drives[choice]
            elif index == 3:
                folder = folder.parent
            elif index == 4:
                name = self.c.text(tr('msg_295'))
                if name:
                    if name in ('.', '..') or any(c in name for c in '<>:"/\\|?*'):
                        self.message(tr('msg_305'), tr('msg_306'))
                    else:
                        try:
                            (folder / name).mkdir()
                            folder /= name
                        except OSError as error:
                            self.message(tr('msg_314'), error)
            elif index == 5:
                if not directory:
                    if multi:
                        chosen += [p for p in entries if p.is_file() and p not in chosen]
                    else:
                        self.message(tr('msg_310'), tr('msg_311'))
            elif index == 6:
                chosen = []
            else:
                p = entries[index - 7]
                if p.is_dir():
                    folder = p
                elif not multi:
                    self.folder = folder
                    return [p]
                elif p in chosen:
                    chosen.remove(p)
                else:
                    chosen.append(p)

    def edit(self, title, schema, original):
        value = copy.deepcopy(original)
        if 'enum' in schema:
            options = schema['enum']
            stages = set(options) == {'orientation','split','deskew','content','layout','output'}
            choice = self.c.choose(title, [tr('stage.' + v) if stages else tr(VALUES.get(v, str(v))) for v in options], tr('msg_197'))
            return (False, original) if choice is None else (True, options[choice])
        kind = schema['type']
        if kind == 'boolean':
            choice = self.c.choose(title, [tr('msg_183'), tr('msg_053')])
            return (False, original) if choice is None else (True, choice == 0)
        if kind in ('number', 'integer', 'string'):
            while True:
                text = self.c.text(title, value, f"{tr('msg_270')}{kind}{tr('msg_271')}{schema.get('minimum', '')}..{schema.get('maximum', '')}", kind != 'string')
                if text is None:
                    return False, original
                try:
                    candidate = int(text) if kind == 'integer' else float(text) if kind == 'number' else text
                    validate(schema, candidate, title)
                    return True, candidate
                except ValueError as error:
                    self.message(tr('msg_278'), error)
        selected = 0
        while True:
            if kind == 'object':
                keys = [k for k in schema['properties'] if k != 'schema_version']
                rows = [f'{label(k)} = {summary(value[k], k) if k in value else tr('msg_286')}' for k in keys]
            else:
                keys = list(range(len(value)))
                rows = [f'{i + 1}: {summary(v)}' for i, v in enumerate(value)]
            actions = [tr('msg_198'), tr('msg_199'), tr('msg_200')]
            if kind == 'array':
                actions += [tr('msg_229'), tr('msg_230')]
            index = self.c.choose(title, actions + rows, tr('msg_201'), selected=selected)
            if index is None or index == 1:
                return False, original
            selected = index
            if index == 0:
                try:
                    validate(schema, value, title)
                    return True, value
                except ValueError as error:
                    self.message(tr('msg_279'), error)
            elif index == 2:
                choice = self.c.choose(tr('msg_272'), rows)
                if choice is not None:
                    key = keys[choice]
                    if kind == 'object' and key in schema.get('required', []):
                        self.message(tr('msg_287'), key)
                    elif kind == 'object':
                        value.pop(key, None)
                    else:
                        value.pop(key)
            elif kind == 'array' and index == 3:
                if len(value) >= schema.get('maxItems', 100000):
                    self.message(tr('msg_288'), len(value))
                    continue
                ok, item = self.edit(title + f'[{len(value) + 1}]', schema['items'], seed(schema['items']))
                if ok:
                    value.append(item)
            elif kind == 'array' and index == 4:
                source = self.c.choose(tr('msg_289'), rows)
                if source is not None:
                    target = self.c.choose(tr('msg_296'), [str(i + 1) for i in keys])
                    if target is not None:
                        value.insert(target, value.pop(source))
            else:
                key = keys[index - len(actions)]
                sub = schema['properties'][key] if kind == 'object' else schema['items']
                current = value.get(key, seed(sub)) if kind == 'object' else value[key]
                ok, item = self.edit(title + '.' + label(str(key)), sub, current)
                if ok:
                    value[key] = item

    def monitor(self):
        from .workbench import STATES
        from .rendering import Frame, ACCENT, MUTED
        self.c.flush()
        selected = 0
        while True:
            with self.m.lock:
                progress = self.m.progress.copy()
                status = self.m.status
            # This screen represents active work. Once the reader has finalized
            # the task, move to results without requiring another key or click.
            if status in ('complete', 'review / partial failure', 'failed', 'cancelled'):
                self.results()
                return
            width, height = self.c.dimensions()
            frame = Frame(width, height)
            done, total = progress['done'], progress['total']
            percent = min(1, done / total) if total else 0
            count = f"{done} / {total}{tr('msg_231')}" if total else tr('msg_202')
            seconds = int(elapsed_seconds(progress))
            frame.text(3, 1, tr(STATES.get(status, status)), ACCENT)
            frame.text(3, 3, tr('msg_203'), MUTED)
            frame.rule(3, 4, width - 7)
            frame.text(4, 6, label(progress['stage']) + (tr('msg_025') if progress.get('reused') else '') + '    ' + count)
            bar_width = max(4, min(50, width - 10))
            frame.text(4, 8, '━' * int(percent * bar_width) + '─' * (bar_width - int(percent * bar_width)), ACCENT)
            frame.text(4, 10, tr('msg_232') + Path(progress['current']).name)
            frame.text(4, 12, tr('msg_233') + (self.m.last or {}).get('output', ''), MUTED)
            frame.text(4, 14, f"{tr('msg_234')}{seconds // 60:02d}:{seconds % 60:02d}", MUTED)
            labels = [tr('msg_235') if self.m.running else tr('msg_236'), tr('msg_204'), tr('msg_205')]
            controls = [i for i in range(3) if i != 0 or self.m.status != 'cancelling']
            if selected not in controls:
                selected = controls[0]
            frame.rule(3, height - 6, width - 7)
            for i, title in enumerate(labels):
                frame.button(3 + i * 17, height - 4, 16, title, i, selected == i, i in controls)
            self.c.draw(frame)
            event = self.c.read()
            if not event:
                continue
            action, data = event
            if action == 'escape':
                return
            choice = None
            if action in ('tab', 'left', 'right', 'up', 'down'):
                delta = -1 if action in ('up', 'left') or (action == 'tab' and data) else 1
                selected = controls[(controls.index(selected) + delta) % len(controls)]
            elif action == 'enter':
                choice = selected
            elif action in ('hover', 'click'):
                hit = frame.hit(data)
                if hit is not None:
                    selected = hit
                    if action == 'click':
                        choice = hit
            if choice == 1:
                return
            if choice == 0:
                if self.m.running:
                    self.m.cancel()
                else:
                    self.results()
                    return
            elif choice == 2:
                with self.m.lock:
                    logs = '\n'.join(self.m.lines)
                self.message(tr('msg_205'), logs)
                self.c.flush()

    def execute(self, command='process', sample=False):
        plan = self.m.plan(command, sample)
        previous = plan['match']
        if previous:
            complete = previous.get('outcome_complete', previous.get('status') == 'complete')
            rows = [tr('msg_237') if complete and plan['valid'] else tr('msg_238'), tr('msg_206'), tr('msg_004')]
            hint = tr('msg_207') + (tr('msg_239') if plan['valid'] else tr('msg_240'))
            choice = self.c.choose(tr('msg_208'), rows, hint)
            if choice is None or choice == 2: return
            self.m.last = previous
            if choice == 0 and complete and plan['valid']:
                self.results(); return
            if choice == 0:
                self.m.start(resume=True); self.monitor(); return
            decision = 'overwrite'
        else:
            decision = None
            root = Path(self.m.output)
            conflict = plan['conflict']
            occupied = command == 'process' and root.exists() and any(root.iterdir())
            hint = (tr('msg_209')
                    if sample else tr('msg_210'))
            stage = 'output' if command == 'process' else self.m.options['stage']
            hint = tr('plan.scope', total=plan['source_count'], selected=plan['selected_count'], stage=tr('stage.' + stage)) + hint
            if conflict:
                hint += tr('msg_244') + '；'.join(plan['changes'][:5])
            hint += tr('msg_184')
            self.message(tr('msg_211'), hint)
            rows = [tr('msg_212'), tr('msg_004')]
            if occupied:
                rows = [tr('msg_245'), tr('msg_004')]
                hint += tr('msg_213')
            if conflict and not conflict.get('outcome_complete', conflict.get('status') == 'complete'):
                choice = self.c.choose(tr('msg_246'), [tr('msg_273'), tr('msg_274'), tr('msg_004')], tr('msg_247'))
                if choice == 0:
                    self.m.last = conflict; self.m.start(resume=True); self.monitor(); return
                if choice != 1: return
            choice = self.c.choose(tr('msg_214'), rows, hint.splitlines()[0])
            if choice != 0: return
            if occupied: decision = 'overwrite'
        if decision == 'overwrite':
            if self.c.choose(tr('msg_248'), [tr('msg_004'), tr('msg_275')], tr('msg_249')) != 1:
                return
        self.m.start(command, sample=sample, decision=decision)
        self.monitor()

    def results(self):
        from .workbench import STATES
        if not self.m.last:
            self.message(tr('msg_215'), tr('msg_216'))
            return
        root = Path(self.m.last['output'])
        while True:
            viewer = root / 'preview.html'
            rows = [tr('msg_250') if viewer.exists() else tr('msg_251'), tr('msg_217'), tr('msg_218'), tr('msg_219'), tr('msg_252') if self.m.last.get('status') == 'complete' else tr('msg_238')]
            status = self.m.last.get('status', 'unknown')
            seconds = self.m.last.get('elapsed_seconds')
            hint = str(root)
            if isinstance(seconds, (int, float)):
                hint = f"{tr('msg_253')}{int(seconds) // 60:02d}:{int(seconds) % 60:02d} · {hint}"
            choice = self.c.choose(tr(STATES.get(status, status)), rows, hint)
            if choice is None:
                return
            if choice == 0:
                os.startfile(viewer if viewer.exists() else root)
            elif choice == 1:
                self.message(tr('msg_276'), (Path(self.m.last['folder']) / 'events.log').read_text(encoding='utf-8')[-20000:])
            elif choice in (2, 3):
                files = sorted(root.rglob('*.scan' if choice == 2 else '*.html')) if root.exists() else []
                index = self.c.choose(tr('msg_280'), [str(p.relative_to(root)) for p in files])
                if index is not None:
                    if choice == 2:
                        self.m.select('project', [files[index]])
                        self.message(tr('msg_297'), tr('msg_298'))
                    else:
                        os.startfile(files[index])
            elif choice == 4:
                if self.c.choose(tr('msg_299'), [tr('msg_301'), tr('msg_004')], tr('msg_300')) != 0: return
                self.m.start(resume=True)
                self.monitor()
                return

    def save_management(self, command, extra=None):
        folder = self.m.new_folder()
        args = command.split() + self.m.source_args(folder)
        if self.m.kind != 'project':
            args += ['--dpi', str(self.m.options['dpi'])]
        if command == 'project edit':
            # Apply ordinal/stable-ID rules before changing source structure;
            # project edit then preserves the resulting page settings.
            configured = self.configured_project(folder / 'configured.scan')
            args = ['project', 'edit', '--project', str(configured)]
        target = folder / 'project.scan'
        args += ['--save', str(target)]
        if command in ('project create', 'project apply'):
            config = folder / 'settings.json'
            write_json(config, self.m.config)
            args += ['--config', str(config)]
        if extra:
            path = folder / 'operations.json'
            write_json(path, extra)
            args += ['--operations', str(path)]
        self.m.query(args + ['--dry-run'])
        self.m.query(args)
        self.m.select('project', [target])
        self.message(tr('msg_185'), str(target))

    def configured_project(self, target):
        config = target.parent / 'gui-or-edit-config.json'
        write_json(config, self.m.config)
        args = ['project', 'apply', '--project', self.m.inputs[0], '--config', config, '--save', target]
        self.m.query(args + ['--dry-run'])
        self.m.query(args)
        return target

    def project(self):
        if self.m.kind == 'pdf':
            self.m.start('analyze')
            self.monitor()
            return
        if self.m.kind != 'project':
            self.save_management('project create')
        while True:
            choice = self.c.choose(tr('msg_220'), [tr('msg_254'), tr('msg_255'), tr('msg_256'), tr('msg_257'),
                                    tr('msg_258'), tr('msg_259'), tr('msg_260'), tr('msg_261'), tr('msg_262'), tr('msg_263')])
            if choice is None:
                return
            project = self.m.inputs[0]
            report = self.m.query(['project', 'inspect', '--project', project])[-1]
            pages = report['pages']
            images = list(dict.fromkeys(p['image_id'] for p in pages))
            page_labels = [f'{p["number"]} {p["id"]} {Path(p["input"]).name}' for p in pages]
            if choice == 0:
                index = self.c.choose(tr('msg_264'), page_labels)
                if index is not None:
                    page = pages[index]
                    action = self.c.choose(tr('msg_281') + page['id'], [tr('msg_282'), tr('msg_283'), tr('msg_284')])
                    if action == 0:
                        self.message(tr('msg_285'), json.dumps(page, ensure_ascii=False, indent=2))
                    elif action in (1, 2):
                        schema = copy.deepcopy(self.m.schema['properties']['defaults'])
                        allowed = {'input', 'orientation', 'split'}
                        schema['properties'] = {k: v for k, v in schema['properties'].items() if (k in allowed) == (action == 2)}
                        ok, settings = self.edit(tr('msg_290'), schema, {})
                        if ok and settings:
                            if 'content' in settings and any(k in settings['content'] for k in ('page_rect', 'content_rect')):
                                basis = page['settings'].get('_geometry', {}).get('basis')
                                if not basis:
                                    raise ValueError(tr('msg_307'))
                                settings['content']['basis'] = basis
                            draft = copy.deepcopy(self.m.config)
                            draft.setdefault('rules', []).append({'select': {'ids' if action == 1 else 'image_ids': [page['id'] if action == 1 else page['image_id']]}, 'settings': settings})
                            self.m.apply(draft)
            elif choice == 1:
                self.save_management('project apply')
            elif choice == 2:
                files = self.browse(IMAGE, multi=True)
                if files:
                    anchor = self.c.choose(tr('msg_291'), [tr('msg_302')] + [tr('msg_308') + i for i in images])
                    if anchor is not None:
                        op = {'type': 'insert', 'files': list(map(str, files)), 'dpi': self.m.options['dpi']}
                        if anchor:
                            op['before_image'] = images[anchor - 1]
                        self.save_management('project edit', {'schema_version': 1, 'operations': [op]})
            elif choice == 3:
                index = self.c.choose(tr('msg_292'), page_labels)
                if index is not None:
                    self.save_management('project edit', {'schema_version': 1, 'operations': [{'type': 'remove', 'ids': [pages[index]['id']]}]})
            elif choice == 4:
                ordered = images[:]
                while True:
                    index = self.c.choose(tr('msg_303'), [tr('msg_312')] + ordered)
                    if index is None:
                        break
                    if index == 0:
                        self.save_management('project edit', {'schema_version': 1, 'operations': [{'type': 'reorder', 'image_ids': ordered}]})
                        break
                    target = self.c.choose(tr('msg_296'), [str(i + 1) for i in range(len(ordered))])
                    if target is not None:
                        ordered.insert(target, ordered.pop(index - 1))
            elif choice == 5:
                paths = list(dict.fromkeys(p['input'] for p in pages))
                index = self.c.choose(tr('msg_304'), paths)
                files = self.browse(IMAGE) if index is not None else None
                if files:
                    self.save_management('project edit', {'schema_version': 1, 'operations': [{'type': 'relink', 'from': paths[index], 'to': str(files[0])}]})
            elif choice == 6:
                index = self.c.choose(tr('msg_309'), images)
                side = self.c.choose(tr('msg_313'), ['left', 'right']) if index is not None else None
                if side is not None:
                    self.save_management('project edit', {'schema_version': 1, 'operations': [{'type': 'restore-half', 'image_id': images[index], 'side': ['left', 'right'][side]}]})
            elif choice == 7:
                self.geometry(pages)
            elif choice == 8:
                folder = self.m.new_folder()
                target = folder / 'export.json'
                self.m.query(['config', 'export', '--project', project, '--save', target])
                self.message(tr('msg_315'), target)
            elif choice == 9:
                # GUI gets a private project copy. Wait before adopting its save.
                folder = self.m.new_folder()
                target = folder / 'graphical.scan'
                self.configured_project(target)
                env = os.environ.copy()
                env.pop('QT_QPA_PLATFORM', None)
                subprocess.run([str(self.m.cli.parent / 'scantailor-advanced.exe'), str(target)], env=env, check=True)
                self.m.query(['project', 'inspect', '--project', target])
                self.m.select('project', [target])

    def geometry(self, pages):
        index = self.c.choose(tr('msg_186'), [p['id'] for p in pages])
        if index is None:
            return
        spaces = ['source', 'oriented', 'split', 'deskew', 'content', 'layout', 'output']
        point = {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {'type': 'number', 'minimum': -10000000, 'maximum': 10000000}}
        schema = {'type': 'object', 'properties': {'from': {'type': 'string', 'enum': spaces}, 'to': {'type': 'string', 'enum': spaces},
                  'points': {'type': 'array', 'minItems': 1, 'items': point}}, 'required': ['from', 'to', 'points']}
        ok, data = self.edit(tr('msg_187'), schema, seed(schema))
        if ok:
            folder = self.m.new_folder()
            data.update(schema_version=1, id=pages[index]['id'])
            write_json(folder / 'geometry.json', data)
            mapped = self.m.query(['geometry', 'map', '--project', self.m.inputs[0], '--geometry', folder / 'geometry.json', '--save', folder / 'mapped.json'])
            self.message(tr('msg_221'), json.dumps(mapped, indent=2, ensure_ascii=False))

    def run(self):
        from .workbench import Workbench
        return Workbench(self).run()

    def choose_language(self):
        choices = list(LANGUAGES)
        current = self.m.language_override or self.m.language_preference
        selected = self.c.choose(tr('language.title'), [tr('language.auto')] + [NAMES[k] for k in choices[1:]],
                                 tr('language.hint'), selected=choices.index(current))
        if selected is not None:
            self.m.set_language(choices[selected])

    def options(self):
        props = {'dpi': {'type': 'integer', 'minimum': 72, 'maximum': 1200}, 'jobs': {'type': 'integer', 'minimum': 1, 'maximum': 16},
                 'page_size': {'type': 'string', 'enum': ['original', 'processed']}, 'pages': {'type': 'string', 'minLength': 1},
                 'stage': {'type': 'string', 'enum': ['orientation', 'split', 'deskew', 'content', 'layout', 'output']},
                 'review_policy': {'type': 'string', 'enum': ['preserve', 'report']},
                 'max_angle': {'type': 'number', 'minimum': 0, 'maximum': 45},
                 'min_page_ratio': {'type': 'number', 'minimum': .1, 'maximum': 1},
                 'sample_pages': {'type': 'string', 'minLength': 1},
                 'existing_output': {'type': 'string', 'enum': ['reject', 'overwrite']}}
        if self.m.kind == 'pdf':
            props = {k: v for k, v in props.items() if k != 'pages'}
        current = {k: v for k, v in self.m.options.items() if k in props}
        ok, value = self.edit(tr('msg_188'), {'type': 'object', 'properties': props, 'required': list(props)}, current)
        if ok:
            self.m.update_options(value)

    def presets(self):
        choice = self.c.choose(tr('msg_034'), [tr('msg_222'), tr('msg_223'), 'physics-safe', tr('msg_224'), tr('msg_225')])
        if choice == 0:
            folder = self.m.new_folder()
            write_json(folder / 'preset.json', self.m.config)
            self.message(tr('msg_226'), folder / 'preset.json')
        elif choice == 1:
            files = self.browse({'.json'})
            if files:
                self.m.apply(json.loads(files[0].read_text(encoding='utf-8-sig')))
        elif choice == 4:
            self.m.apply({'schema_version': 2})
            self.m.update_options(self.m.default_options)
        elif choice in (2, 3):
            self.m.apply({'schema_version': 2, **({'preset': 'physics-safe'} if choice == 2 else {})})


def main():
    parser = argparse.ArgumentParser(description='ScanTailor Windows console menu')
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--language', choices=LANGUAGES, help='Interface language for this launch only')
    parser.add_argument('--state-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ScanTailorCLI' / 'menu')
    args = parser.parse_args()
    try:
        with Console() as console:
            model = Controller(args.cli, args.state_dir, language=args.language)
            ui = UI(console, model)
            if model.preference_error: ui.message(tr('msg_265'), model.preference_error)
            return ui.run()
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 3
