"""Menu adapters for schema-2 settings and CLI project/page commands.

All edits are local drafts until Apply. Project mutations save a new project
inside the menu job store and adopt it only after the native validator succeeds.
"""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from .console import Console
from .model import Controller, seed, validate, write_json

LABELS = {'defaults': '全局页面设置', 'project': '项目设置', 'rules': '按页 / 源图规则', 'preset': '预设',
          'input': '输入 DPI', 'orientation': '方向与初裁切', 'split': '拆分页面', 'deskew': '纠偏 / 斜切',
          'content': '页面与内容框', 'layout': '页边距与布局', 'output': '输出 / 二值化 / 展平',
          'picture_zones': '图片区域', 'fill_zones': '填色区域', 'select': '作用范围', 'settings': '参数',
          'reading_direction': '阅读顺序', 'dpi': 'DPI', 'jobs': '并发数', 'pages': '输出页范围',
          'stage': '分析 / 预览阶段', 'page_size': 'PDF 页面尺寸', 'review_policy': '疑难页策略'}
IMAGE = {'.png', '.tif', '.tiff', '.jpg', '.jpeg', '.bmp'}


def label(key):
    return LABELS.get(key, key)


def summary(value):
    if isinstance(value, dict):
        return ', '.join(value) or '(沿用已有值)'
    if isinstance(value, list):
        return f'{len(value)} 项 ' + str(value)[:70]
    return str(value)


class UI:
    def __init__(self, console, controller):
        self.c, self.m = console, controller
        self.folder = Path.home()

    def message(self, title, text):
        self.c.choose(title, str(text).splitlines() + ['[返回]'])

    def browse(self, suffixes=None, multi=False, directory=False):
        folder, chosen = self.folder, []
        while True:
            try:
                entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
                entries = [p for p in entries if p.is_dir() or (not directory and p.suffix.lower() in suffixes)]
            except OSError as error:
                self.message('无法打开目录', error)
                folder = Path.home()
                continue
            rows = ['[确认当前目录]' if directory else f'[确认已选 {len(chosen)} 项，顺序为选择顺序]',
                    '[输入路径 / 跳转]', '[驱动器]', '[上一级]', '[新建文件夹]', '[选择本目录全部文件]', '[清空已选文件]']
            rows += [('📁 ' if p.is_dir() else ('[x] ' if p in chosen else '[ ] ')) + p.name for p in entries]
            index = self.c.choose(str(folder), rows, '文件单击/Space 勾选；目录单击进入；Esc 取消整个选择')
            if index is None:
                return None
            if index == 0:
                if directory or chosen:
                    self.folder = folder
                    return [folder] if directory else chosen
            elif index == 1:
                text = self.c.text('输入绝对路径', str(folder))
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
                        self.message('路径无效', '请选择存在的目录或支持的文件')
            elif index == 2:
                drives = [Path(f'{c}:/') for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' if Path(f'{c}:/').exists()]
                choice = self.c.choose('驱动器', [str(p) for p in drives])
                if choice is not None:
                    folder = drives[choice]
            elif index == 3:
                folder = folder.parent
            elif index == 4:
                name = self.c.text('新建子文件夹名称')
                if name:
                    if name in ('.', '..') or any(c in name for c in '<>:"/\\|?*'):
                        self.message('名称无效', '请输入单个文件夹名称')
                    else:
                        try:
                            (folder / name).mkdir()
                            folder /= name
                        except OSError as error:
                            self.message('创建失败', error)
            elif index == 5:
                if not directory:
                    if multi:
                        chosen += [p for p in entries if p.is_file() and p not in chosen]
                    else:
                        self.message('单文件选择', '请单击要打开的文件')
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
            choice = self.c.choose(title, list(map(str, options)), 'Esc 放弃此字段')
            return (False, original) if choice is None else (True, options[choice])
        kind = schema['type']
        if kind == 'boolean':
            choice = self.c.choose(title, ['true / 开启', 'false / 关闭'])
            return (False, original) if choice is None else (True, choice == 0)
        if kind in ('number', 'integer', 'string'):
            while True:
                text = self.c.text(title, value, f'类型 {kind}  范围 {schema.get("minimum", "")}..{schema.get("maximum", "")}', kind != 'string')
                if text is None:
                    return False, original
                try:
                    candidate = int(text) if kind == 'integer' else float(text) if kind == 'number' else text
                    validate(schema, candidate, title)
                    return True, candidate
                except ValueError as error:
                    self.message('输入无效', error)
        selected = 0
        while True:
            if kind == 'object':
                keys = [k for k in schema['properties'] if k != 'schema_version']
                rows = [f'{label(k)} = {summary(value[k]) if k in value else "[未设置 / 沿用]"}' for k in keys]
            else:
                keys = list(range(len(value)))
                rows = [f'{i + 1}: {summary(v)}' for i, v in enumerate(value)]
            actions = ['[应用此表单]', '[放弃此表单]', '[删除字段 / 数组项]']
            if kind == 'array':
                actions += ['[新增项]', '[调整顺序]']
            index = self.c.choose(title, actions + rows, '参数单位和几何空间见 MENU.md；未设置值保留项目现状', selected=selected)
            if index is None or index == 1:
                return False, original
            selected = index
            if index == 0:
                try:
                    validate(schema, value, title)
                    return True, value
                except ValueError as error:
                    self.message('表单未通过校验', error)
            elif index == 2:
                choice = self.c.choose('删除（不影响源文件）', rows)
                if choice is not None:
                    key = keys[choice]
                    if kind == 'object' and key in schema.get('required', []):
                        self.message('必填字段', key)
                    elif kind == 'object':
                        value.pop(key, None)
                    else:
                        value.pop(key)
            elif kind == 'array' and index == 3:
                if len(value) >= schema.get('maxItems', 100000):
                    self.message('已达上限', len(value))
                    continue
                ok, item = self.edit(title + f'[{len(value) + 1}]', schema['items'], seed(schema['items']))
                if ok:
                    value.append(item)
            elif kind == 'array' and index == 4:
                source = self.c.choose('移动哪一项', rows)
                if source is not None:
                    target = self.c.choose('移动到位置', [str(i + 1) for i in keys])
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
        def tick():
            with self.m.lock:
                lines = self.m.lines[-8:]
            return ('任务: ' + self.m.status, ['[请求取消并等待]' if self.m.running else '[查看结果]', '[返回主菜单]'] + lines,
                    '运行期间设置锁定；取消会等待处理进程退出并保存可用检查点')
        while True:
            choice = self.c.choose('', [], tick=tick)
            if choice is None or choice == 1:
                return
            if choice == 0:
                if self.m.running:
                    self.m.cancel()
                else:
                    self.results()
                    return

    def results(self):
        if not self.m.last:
            self.message('暂无任务', '先选择输入和输出，再运行任务')
            return
        root = Path(self.m.last['output'])
        while True:
            rows = ['[打开结果目录]', '[查看任务日志]', '[打开生成的项目]', '[打开复核 / 预览报告]', '[恢复此任务快照]']
            choice = self.c.choose('结果: ' + str(root), rows, self.m.last.get('status', 'unknown'))
            if choice is None:
                return
            if choice == 0:
                os.startfile(root)
            elif choice == 1:
                self.message('任务日志', (Path(self.m.last['folder']) / 'events.log').read_text(encoding='utf-8')[-20000:])
            elif choice in (2, 3):
                files = sorted(root.rglob('*.scan' if choice == 2 else '*.html')) if root.exists() else []
                index = self.c.choose('选择文件', [str(p.relative_to(root)) for p in files])
                if index is not None:
                    if choice == 2:
                        self.m.select('project', [files[index]])
                        self.message('项目已载入', '页面规则已重置，可进入项目操作或预览')
                    else:
                        os.startfile(files[index])
            elif choice == 4:
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
        self.message('已保存并载入新项目', str(target))

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
            choice = self.c.choose('项目与页面操作', ['检查页面 / 添加页规则', '应用当前配置并另存项目', '插入图片', '移除逻辑页',
                                    '调整源图顺序', '重新关联图片', '恢复半页', '几何坐标转换', '导出当前配置', '同包 GUI 图形编辑'])
            if choice is None:
                return
            project = self.m.inputs[0]
            report = self.m.query(['project', 'inspect', '--project', project])[-1]
            pages = report['pages']
            images = list(dict.fromkeys(p['image_id'] for p in pages))
            page_labels = [f'{p["number"]} {p["id"]} {Path(p["input"]).name}' for p in pages]
            if choice == 0:
                index = self.c.choose('逻辑页', page_labels)
                if index is not None:
                    page = pages[index]
                    action = self.c.choose('页面 ' + page['id'], ['查看参数 / 几何', '添加逻辑页规则', '添加源图规则'])
                    if action == 0:
                        self.message('页面详情', json.dumps(page, ensure_ascii=False, indent=2))
                    elif action in (1, 2):
                        schema = copy.deepcopy(self.m.schema['properties']['defaults'])
                        allowed = {'input', 'orientation', 'split'}
                        schema['properties'] = {k: v for k, v in schema['properties'].items() if (k in allowed) == (action == 2)}
                        ok, settings = self.edit('页面参数', schema, {})
                        if ok and settings:
                            if 'content' in settings and any(k in settings['content'] for k in ('page_rect', 'content_rect')):
                                basis = page['settings'].get('_geometry', {}).get('basis')
                                if not basis:
                                    raise ValueError('先分析到 deskew，再载入分析项目以编辑手动框')
                                settings['content']['basis'] = basis
                            draft = copy.deepcopy(self.m.config)
                            draft.setdefault('rules', []).append({'select': {'ids' if action == 1 else 'image_ids': [page['id'] if action == 1 else page['image_id']]}, 'settings': settings})
                            self.m.apply(draft)
            elif choice == 1:
                self.save_management('project apply')
            elif choice == 2:
                files = self.browse(IMAGE, multi=True)
                if files:
                    anchor = self.c.choose('插入位置', ['末尾'] + ['在前: ' + i for i in images])
                    if anchor is not None:
                        op = {'type': 'insert', 'files': list(map(str, files)), 'dpi': self.m.options['dpi']}
                        if anchor:
                            op['before_image'] = images[anchor - 1]
                        self.save_management('project edit', {'schema_version': 1, 'operations': [op]})
            elif choice == 3:
                index = self.c.choose('移除项目中的逻辑页（保留源文件）', page_labels)
                if index is not None:
                    self.save_management('project edit', {'schema_version': 1, 'operations': [{'type': 'remove', 'ids': [pages[index]['id']]}]})
            elif choice == 4:
                ordered = images[:]
                while True:
                    index = self.c.choose('源图排序', ['[保存顺序]'] + ordered)
                    if index is None:
                        break
                    if index == 0:
                        self.save_management('project edit', {'schema_version': 1, 'operations': [{'type': 'reorder', 'image_ids': ordered}]})
                        break
                    target = self.c.choose('移动到位置', [str(i + 1) for i in range(len(ordered))])
                    if target is not None:
                        ordered.insert(target, ordered.pop(index - 1))
            elif choice == 5:
                paths = list(dict.fromkeys(p['input'] for p in pages))
                index = self.c.choose('重新关联源图', paths)
                files = self.browse(IMAGE) if index is not None else None
                if files:
                    self.save_management('project edit', {'schema_version': 1, 'operations': [{'type': 'relink', 'from': paths[index], 'to': str(files[0])}]})
            elif choice == 6:
                index = self.c.choose('恢复半页：源图', images)
                side = self.c.choose('恢复哪一半', ['left', 'right']) if index is not None else None
                if side is not None:
                    self.save_management('project edit', {'schema_version': 1, 'operations': [{'type': 'restore-half', 'image_id': images[index], 'side': ['left', 'right'][side]}]})
            elif choice == 7:
                self.geometry(pages)
            elif choice == 8:
                folder = self.m.new_folder()
                target = folder / 'export.json'
                self.m.query(['config', 'export', '--project', project, '--save', target])
                self.message('已导出配置', target)
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
        index = self.c.choose('坐标转换：逻辑页', [p['id'] for p in pages])
        if index is None:
            return
        spaces = ['source', 'oriented', 'split', 'deskew', 'content', 'layout', 'output']
        point = {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {'type': 'number', 'minimum': -10000000, 'maximum': 10000000}}
        schema = {'type': 'object', 'properties': {'from': {'type': 'string', 'enum': spaces}, 'to': {'type': 'string', 'enum': spaces},
                  'points': {'type': 'array', 'minItems': 1, 'items': point}}, 'required': ['from', 'to', 'points']}
        ok, data = self.edit('几何坐标（像素）', schema, seed(schema))
        if ok:
            folder = self.m.new_folder()
            data.update(schema_version=1, id=pages[index]['id'])
            write_json(folder / 'geometry.json', data)
            mapped = self.m.query(['geometry', 'map', '--project', self.m.inputs[0], '--geometry', folder / 'geometry.json', '--save', folder / 'mapped.json'])
            self.message('转换结果', json.dumps(mapped, indent=2, ensure_ascii=False))

    def run(self):
        while True:
            hint = f'输入 {self.m.kind or "未选择"} {len(self.m.inputs)} 项 | 输出 {self.m.output or "未选择"} | 状态 {self.m.status}'
            rows = ['选择 PDF（单个 / 多个）', '选择图片（单个 / 多个）', '打开 .scan 项目', '选择输出目录',
                    '参数设置（全局 / 按页规则 / 高级几何）', '运行选项（DPI / 并发 / 选页 / 阶段）',
                    '项目与页面操作', '开始处理', '阶段分析', '阶段预览', '当前任务 / 取消', '任务结果 / 复核',
                    '历史任务 / 恢复', '预设保存 / 载入', '环境诊断', '帮助', '退出']
            choice = self.c.choose('ScanTailor CLI 3 · 键盘 / 鼠标菜单', rows, hint)
            try:
                if choice is None or choice == 16:
                    if self.m.running:
                        self.message('任务仍在运行', '请先请求取消并等待完成，再退出。')
                        self.monitor()
                    else:
                        return 0
                elif self.m.running and choice not in (10, 15):
                    self.message('任务运行中', '设置和项目已锁定；可查看进度或请求取消。')
                elif choice in (0, 1, 2):
                    files = self.browse([{'.pdf'}, IMAGE, {'.scan'}][choice], multi=choice != 2)
                    if files:
                        self.m.select(['pdf', 'images', 'project'][choice], files)
                elif choice == 3:
                    folders = self.browse(directory=True)
                    if folders:
                        self.m.invalidate()
                        self.m.output = str(folders[0])
                elif choice == 4:
                    ok, config = self.edit('处理配置草稿', self.m.schema, self.m.config)
                    if ok:
                        self.m.apply(config)
                elif choice == 5:
                    self.options()
                elif choice == 6:
                    self.project()
                elif choice in (7, 8, 9):
                    self.m.start(['process', 'analyze', 'preview'][choice - 7])
                    self.monitor()
                elif choice == 10:
                    self.monitor()
                elif choice == 11:
                    self.results()
                elif choice == 12:
                    jobs = self.m.history()
                    index = self.c.choose('历史任务', [f'{j.get("status")} | {j.get("command")} | {j.get("output")}' for j in jobs])
                    if index is not None:
                        self.m.last = jobs[index]
                        self.results()
                elif choice == 13:
                    self.presets()
                elif choice == 14:
                    self.message('环境诊断', json.dumps(self.m.query(['doctor']), ensure_ascii=False, indent=2))
                elif choice == 15:
                    self.message('帮助', '方向键 / Tab 移动，Enter / 单击执行，Esc 放弃当前表单。\n多文件按勾选顺序处理；文件浏览器可手输路径。\n设置先在草稿中修改，应用后生效。\n几何单位：像素；margins_mm / frozen_size_mm：毫米。\n先分析并打开生成项目，再编辑该页内容框。\nPDF 先处理并从结果打开 .scan，再预览和逐页修正。\n输出需专用目录；已有任务从历史恢复。\nWindows 系统快捷键由终端控制。详细说明见 MENU.md。')
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                self.message('操作未完成', error)

    def options(self):
        props = {'dpi': {'type': 'integer', 'minimum': 72, 'maximum': 1200}, 'jobs': {'type': 'integer', 'minimum': 1, 'maximum': 16},
                 'page_size': {'type': 'string', 'enum': ['original', 'processed']}, 'pages': {'type': 'string', 'minLength': 1},
                 'stage': {'type': 'string', 'enum': ['orientation', 'split', 'deskew', 'content', 'layout', 'output']},
                 'review_policy': {'type': 'string', 'enum': ['preserve', 'report']},
                 'max_angle': {'type': 'number', 'minimum': 0, 'maximum': 45},
                 'min_page_ratio': {'type': 'number', 'minimum': .1, 'maximum': 1},
                 'existing_output': {'type': 'string', 'enum': ['reject', 'overwrite']}}
        if self.m.kind == 'pdf':
            props = {k: v for k, v in props.items() if k != 'pages'}
        current = {k: v for k, v in self.m.options.items() if k in props}
        ok, value = self.edit('运行选项', {'type': 'object', 'properties': props, 'required': list(props)}, current)
        if ok:
            self.m.invalidate()
            self.m.options.update(value)

    def presets(self):
        choice = self.c.choose('预设', ['保存当前设置', '载入 schema 2 配置', 'physics-safe', '清除覆盖 / 沿用项目'])
        if choice == 0:
            folder = self.m.new_folder()
            write_json(folder / 'preset.json', self.m.config)
            self.message('已保存', folder / 'preset.json')
        elif choice == 1:
            files = self.browse({'.json'})
            if files:
                self.m.apply(json.loads(files[0].read_text(encoding='utf-8-sig')))
        elif choice in (2, 3):
            self.m.apply({'schema_version': 2, **({'preset': 'physics-safe'} if choice == 2 else {})})


def main():
    parser = argparse.ArgumentParser(description='ScanTailor Windows console menu')
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--state-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ScanTailorCLI' / 'menu')
    args = parser.parse_args()
    try:
        with Console() as console:
            model = Controller(args.cli, args.state_dir)
            return UI(console, model).run()
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 3
