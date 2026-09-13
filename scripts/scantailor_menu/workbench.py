"""Guided terminal workbench; business commands still use UI/Controller adapters."""
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
STATES = {'idle': '等待创建任务', 'running': '正在处理', 'cancelling': '正在取消，请等待保存检查点',
          'complete': '全部完成', 'cancelled': '已取消，可继续处理', 'failed': '处理失败',
          'review / partial failure': '需要复核 / 部分失败'}
KINDS = {'pdf': 'PDF 文档', 'images': '扫描图片', 'project': 'ScanTailor 项目'}


class Workbench:
    def __init__(self, ui):
        self.ui, self.c, self.m = ui, ui.c, ui.m
        self.focus = 'paste'
        self.scheme = '保真整理'
        self.suggested_output = ''

    def select(self, kind, paths):
        self.m.select(kind, paths)
        parent = Path(paths[0]).resolve().parent
        if not self.m.output or self.m.output == self.suggested_output:
            target = parent / 'scantailor-output'
            suffix = 2
            while target.exists() and (not target.is_dir() or any(target.iterdir())):
                target = parent / f'scantailor-output-{suffix}'
                suffix += 1
            self.m.output = self.suggested_output = str(target)
        self.scheme = '沿用项目' if kind == 'project' else '保真整理'
        self.focus = 'preview'

    def collect(self, text, recursive=False):
        paths = parse_paths(text)
        if not paths:
            raise ValueError('请粘贴文件或文件夹路径，每行一项。')
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
                errors.append(f'无法读取或不支持：{path}')
        unique = {str(p).casefold(): p for p in files}
        files = list(unique.values())
        if errors:
            raise ValueError('\n'.join(errors[:5]))
        if not files:
            raise ValueError('没有找到 PDF、图片或 .scan 项目，请检查目录。')
        kinds = {'pdf' if p.suffix.lower() == '.pdf' else 'project' if p.suffix.lower() == '.scan' else 'images' for p in files}
        if len(kinds) != 1:
            raise ValueError('请将 PDF、图片和 .scan 项目分别创建任务，不要混合导入。')
        kind = kinds.pop()
        if kind == 'project' and len(files) != 1:
            raise ValueError('一次只能打开一个 .scan 项目。')
        return kind, files

    def import_paths(self, initial=''):
        text = initial
        while True:
            text = self.c.text('粘贴文件或文件夹地址', text, '每行一个路径；支持资源管理器“复制为路径”产生的引号。',
                               multiline=True, validator=lambda t: self.validate_paths(t), apply_label='识别路径')
            if text is None:
                return
            directories = any(p.is_dir() for p in parse_paths(text))
            recursive = False
            if directories:
                choice = self.c.choose('如何读取文件夹', ['只读取本目录', '包含全部子目录'], '同一任务内请使用同一种文件类型')
                if choice is None:
                    continue
                recursive = choice == 1
            try:
                kind, files = self.collect(text, recursive)
            except (ValueError, OSError) as error:
                self.ui.message('请修改路径', error)
                continue
            choice = self.c.choose(f'找到 {len(files)} 项 · {KINDS[kind]}', ['确认导入', '返回修改地址'] + [str(p) for p in files],
                                   '文件顺序如下；源文件不会被覆盖')
            if choice == 0:
                self.select(kind, files)
                return
            if choice is None:
                return

    @staticmethod
    def validate_paths(text):
        paths = parse_paths(text)
        if not paths:
            raise ValueError('请输入至少一个文件或文件夹地址。')
        invalid = [str(p) for p in paths if not p.exists()]
        if invalid:
            raise ValueError('路径不存在：' + invalid[0])

    def output(self):
        def validate(text):
            paths = parse_paths(text)
            if len(paths) != 1:
                raise ValueError('请填写一个输出文件夹地址。')
            path = paths[0].resolve()
            if path.exists() and not path.is_dir():
                raise ValueError('此地址是文件，请选择文件夹。')
            if any(Path(p).resolve().is_relative_to(path) for p in self.m.inputs):
                raise ValueError('输出文件夹不能包含输入文件，请使用独立子目录。')
        choice = self.c.choose('保存位置', ['粘贴或编辑地址', '浏览文件夹'], '建议使用独立的输出文件夹；输入文件保持不变')
        if choice == 0:
            text = self.c.text('结果保存到', self.m.output, '可填写尚未创建的文件夹；开始任务时自动创建。', validator=validate)
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
        fields = [('纠偏方式', 'deskew', 'mode', ['auto', 'off'], ['自动扶正页面', '保持原角度']),
                  ('页面拆分', 'split', 'layout', ['single', 'auto', 'two'], ['每张图一页', '自动判断单双页', '每张图分成左右两页']),
                  ('输出颜色', 'output', 'mode', ['colorOrGray', 'bw', 'mixed'], ['保留颜色与灰度', '纯黑白文字', '黑白文字 + 彩色图片']),
                  ('输出清晰度', 'output', 'dpi', [[150, 150], [300, 300], [600, 600]], ['150 DPI · 较小文件', '300 DPI · 常用', '600 DPI · 较大文件'])]
        while True:
            labels = []
            for name, section, key, values, names in fields:
                current = defaults.get(section, {}).get(key)
                description = names[values.index(current)] if current in values else '沿用已有设置'
                labels.append(f'{name}    {description}')
            index = self.c.choose('常用设置', labels + ['四边页边距', '疑难页处理方式', '应用设置', '放弃修改', '中间图片格式与压缩'],
                                  '修改仅在此草稿中生效；高级参数在“全部设置”中')
            if index is None or index == 7:
                return
            if index == 8:
                value = self.encoding(draft.get('image_encoding', {}))
                if value is not None:
                    draft['image_encoding'] = value
            elif index < 4:
                name, section, key, values, names = fields[index]
                selected = self.c.choose(name, names)
                if selected is not None:
                    defaults.setdefault(section, {})[key] = values[selected]
                    if section == 'deskew' and key == 'mode':
                        defaults[section].pop('angle', None)
            elif index == 4:
                ok, value = self.ui.edit('四边页边距（毫米）', {'type': 'number', 'minimum': 0, 'maximum': 100},
                                         defaults.get('layout', {}).get('margins_mm', {}).get('left', 0))
                if ok:
                    defaults.setdefault('layout', {})['margins_mm'] = {k: value for k in ('left', 'right', 'top', 'bottom')}
                    defaults['layout']['auto_margins'] = False
            elif index == 5:
                selected = self.c.choose('疑难页处理', ['保留原页并提醒复核（推荐）', '生成处理结果并标记复核'])
                if selected is not None:
                    # Kept in this form draft until Apply, like processing settings.
                    draft_policy = ['preserve', 'report'][selected]
                    draft['_menu_policy'] = draft_policy
            elif index == 6:
                policy = draft.pop('_menu_policy', self.m.options['review_policy'])
                self.m.apply(draft)
                self.m.options['review_policy'] = policy
                self.scheme = '自定义'
                return

    def encoding(self, current):
        draft = image_encoding.resolve(current)
        while True:
            fmt = draft['format']
            key = {'png': 'png_compression', 'tiff': 'tiff_compression', 'jpeg': 'jpeg_quality'}[fmt]
            label = {'png': '压缩等级（0–9）', 'tiff': '压缩方式', 'jpeg': '图像质量（1–100）'}[fmt]
            value = draft[key]
            display = {'none': '无压缩', 'lzw': 'LZW', 'deflate': 'Deflate'}.get(value, str(value))
            hint = '无损；更高压缩等级通常更慢' if fmt == 'png' else '无损压缩' if fmt == 'tiff' else '有损编码；不支持透明分层输出；疑难页仍无损保留'
            choice = self.c.choose('中间图片', ['格式    ' + fmt.upper(), label + '    ' + display, '应用', '取消'], hint)
            if choice is None or choice == 3:
                return None
            if choice == 0:
                selected = self.c.choose('图片格式', ['PNG · 无损（推荐）', 'TIFF · 无损', 'JPEG · 有损'])
                if selected is not None:
                    draft = image_encoding.resolve(draft, {'format': ['png', 'tiff', 'jpeg'][selected]})
            elif choice == 1:
                if fmt == 'tiff':
                    selected = self.c.choose('TIFF 压缩', ['无压缩', 'LZW', 'Deflate'])
                    if selected is not None: draft[key] = ['none', 'lzw', 'deflate'][selected]
                else:
                    ok, value = self.ui.edit(label, {'type': 'integer', 'minimum': 0 if fmt == 'png' else 1, 'maximum': 9 if fmt == 'png' else 100}, draft[key])
                    if ok: draft[key] = value
            elif choice == 2:
                return image_encoding.resolve(draft)

    def schemes(self):
        choice = self.c.choose('选择处理方案', ['保真整理 · 保留颜色、细线，疑难页保留原页', '黑白文档 · 适合纯文字扫描', '自定义常用设置', '全部设置 / 按页规则', '保存或载入设置文件'])
        if choice in (0, 1):
            config = {'schema_version': 2, 'preset': 'physics-safe', 'image_encoding': self.m.config.get('image_encoding', {})}
            if choice == 1:
                config['defaults'] = {'output': {'mode': 'bw'}}
            self.m.apply(config)
            self.m.options['review_policy'] = 'preserve'
            self.scheme = ['保真整理', '黑白文档'][choice]
        elif choice == 2:
            self.common()
        elif choice == 3:
            self.advanced()
        elif choice == 4:
            self.ui.presets()
            self.scheme = '自定义'

    def advanced(self):
        choice = self.c.choose('全部设置', ['六阶段设置 / 项目设置 / 按页规则', '运行选项 / 选页 / 并发', '阶段分析', '指定阶段预览', '保存或载入设置文件'],
                               '高级功能保留完整参数；多数文档只需调整常用设置')
        if choice == 0:
            ok, config = self.ui.edit('全部处理设置', self.m.schema, self.m.config)
            if ok:
                self.m.apply(config)
                self.scheme = '自定义'
        elif choice == 1:
            self.ui.options()
        elif choice in (2, 3):
            self.m.start('analyze' if choice == 2 else 'preview')
            self.ui.monitor()
        elif choice == 4:
            self.ui.presets()

    def frame(self, width, height):
        frame = Frame(width, height)
        if width < 54 or height < 22:
            frame.text(2, 2, 'ScanTailor · 请放大终端窗口', ACCENT)
            frame.text(2, 4, '建议至少 54 列 × 22 行；Esc 可退出。', MUTED)
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
        frame.text(3, 1, 'ScanTailor  /  扫描文档整理', ACCENT)
        if width >= 80:
            frame.text(width - 29, 1, '本地处理 · 源文件保持不变', MUTED)
        button(3, 3, 14, '任务工作台', 'home')
        button(18, 3, 12, '项目编辑', 'project', not running and bool(self.m.inputs))
        button(31, 3, 12, '任务记录', 'history', not running)
        button(44, 3, 8, '帮助', 'help')
        frame.rule(3, 4, width - 7)
        frame.text(4, 6, '01  输入文件', ACCENT)
        desc = f'{KINDS.get(self.m.kind, "")} · {len(self.m.inputs)} 项' if self.m.inputs else '粘贴文件地址，或选择一个扫描文件夹'
        frame.text(5, 7, desc, FG, main_width - 5)
        if wide:
            frame.text(5, 8, str(self.m.inputs[0]) if self.m.inputs else '支持 PDF、PNG、JPG、TIFF 和 .scan 项目', MUTED, main_width - 5)
        y = 9 if wide else 8
        button(4, y, 16, '粘贴路径', 'paste', not running)
        button(21, y, 14, '浏览文件', 'browse', not running)
        button(36, y, 16, '选择文件夹', 'folder', not running)
        oy = 12 if wide else 10
        frame.text(4, oy, '02  保存位置', ACCENT)
        frame.text(5, oy + 1, self.m.output or '选择输入后自动建议独立输出目录', MUTED, main_width - 5)
        button(4, oy + 2, 20, '修改保存位置', 'output', not running)
        sy = 17 if wide else 14
        frame.text(4, sy, '03  处理方案', ACCENT)
        scheme = '沿用项目' if self.m.kind == 'project' and self.m.config == {'schema_version': 2} else self.scheme
        editable = not running and bool(self.m.inputs)
        button(4, sy + 1, 22, scheme + '  ▾', 'scheme', editable)
        button(27, sy + 1, 13, '常用设置', 'common', editable)
        button(41, sy + 1, 13, '全部设置', 'advanced', editable)
        if wide:
            frame.text(5, sy + 3, '先预览少量页面，再开始整批处理。', MUTED, main_width - 5)
            x = main_width + 3
            for row in range(6, height - 7):
                frame.text(main_width, row, '│', MUTED)
            frame.rule(x, 6, width - x - 4, '任务概览')
            current = self.m.running or (self.m.last and self.m.last.get('revision') == self.m.revision)
            status = STATES.get(self.m.status, self.m.status) if current else ('任务已就绪' if ready else '等待创建任务')
            frame.text(x + 1, 8, status, ACCENT, width - x - 4)
            frame.text(x + 1, 10, f'输入分辨率   {self.m.options["dpi"]} DPI', FG)
            frame.text(x + 1, 12, f'同时处理     {self.m.options["jobs"]} 页', FG)
            frame.text(x + 1, 14, '疑难页       ' + ('保留原页' if self.m.options['review_policy'] == 'preserve' else '标记复核'), FG)
            encoding = image_encoding.resolve(self.m.config.get('image_encoding', {}))
            compression = next(v for k, v in encoding.items() if k != 'format')
            frame.text(x + 1, 16, f'中间图片     {encoding["format"].upper()} · {compression}', FG, width - x - 4)
            frame.text(x + 1, 17, '地址输入支持', ACCENT)
            frame.text(x + 1, 19, 'Ctrl+V / Shift+Insert / 右键', MUTED)
            frame.text(x + 1, 20, '多行地址 · 中文路径 · 引号', MUTED)
        by = height - 5
        frame.rule(3, by - 1, width - 7)
        button(4, by, 18, '查看进度' if running else '预览几页', 'progress' if running else 'preview', running or bool(self.m.inputs))
        button(23, by, 18, '正在处理中' if running else '开始处理', 'start', ready and not running)
        button(42, by, 12, '退出', 'exit')
        if not ready and not running:
            frame.text(4, by + 1, '先选择输入文件和保存位置，即可开始处理。', MUTED)
        frame.text(3, height - 2, 'Tab/↑↓ 切换 · Enter/单击 打开 · Ctrl+V 在输入框粘贴', MUTED)
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
                    self.ui.message('暂未完成，请检查', error)
                self.c.flush()

    def dispatch(self, key):
        if key == 'paste':
            self.import_paths()
        elif key == 'browse':
            choice = self.c.choose('选择文件类型', ['PDF 文档', '扫描图片', '已有 .scan 项目'])
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
            self.m.start('preview', sample=True)
            self.ui.monitor()
        elif key == 'start':
            self.m.start()
            self.ui.monitor()
        elif key == 'progress':
            self.ui.monitor()
        elif key == 'project':
            self.ui.project()
        elif key == 'history':
            jobs = self.m.history()
            index = self.c.choose('任务记录', [f'{STATES.get(j.get("status"), j.get("status"))} · {j.get("output")}' for j in jobs], '恢复使用该任务的原始快照')
            if index is not None:
                self.m.last = jobs[index]
                self.ui.results()
        elif key == 'help':
            self.ui.message('使用帮助', '1. 粘贴路径或选择文件。\n2. 确认保存位置与处理方案。\n3. 先预览，再开始整批处理。\n\n输入框：Ctrl+V / Shift+Insert / 右键粘贴；Ctrl+A 全选。\n多行地址：Enter 换行，Ctrl+Enter 确认，也可单击按钮。\n任务运行时可查看进度、请求取消；请等待检查点保存完成。\n\n完整参数、项目编辑与阶段分析仍在全部设置和项目编辑中。')
