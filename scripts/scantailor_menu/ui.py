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
import time
from .console import Console
from .model import Controller, seed, validate, write_json, elapsed_seconds

LABELS = {'defaults': '全局页面设置', 'project': '项目设置', 'rules': '按页 / 源图规则', 'preset': '预设',
          'input': '输入 DPI', 'orientation': '方向与初裁切', 'split': '拆分页面', 'deskew': '纠偏 / 斜切',
          'content': '页面与内容框', 'layout': '页边距与布局', 'output': '输出 / 二值化 / 展平',
          'picture_zones': '图片区域', 'fill_zones': '填色区域', 'select': '作用范围', 'settings': '参数',
          'reading_direction': '阅读顺序', 'dpi': 'DPI', 'jobs': '并发数', 'pages': '输出页范围',
          'stage': '分析 / 预览阶段', 'page_size': 'PDF 页面尺寸', 'review_policy': '疑难页策略'}
LABELS['sample_pages'] = '快速预览源页（sample 或 1,5,9）'
LABELS.update(dict(image_encoding='中间图片', format='图片格式', png_compression='PNG 压缩等级', tiff_compression='TIFF 压缩方式', jpeg_quality='JPEG 质量'))
LABELS.update(dict(rotation='顺时针旋转（度）', trim='初裁切', enabled='启用', left='左边', right='右边', top='上边', bottom='下边',
                  mode='处理模式', angle='纠偏角度（度）', oblique_mode='斜切模式', oblique_angle='斜切角度（度）',
                  space='坐标空间', cutters='拆分线端点', page_mode='纸张框检测', content_mode='正文框检测', page_rect='纸张框 [横坐标,纵坐标,宽,高]',
                  content_rect='正文框 [横坐标,纵坐标,宽,高]', basis='几何版本标识', fine_tune='精细调整', margins_mm='四边页边距（毫米）',
                  match_size='统一页面尺寸', auto_margins='自动页边距', horizontal='水平对齐', vertical='垂直对齐',
                  points='多边形顶点（像素）', color='填充颜色 #RRGGBB', layer='区域作用', category='区域来源',
                  threshold_method='二值化算法', threshold='阈值调整', threshold_window='阈值窗口（像素）', despeckle='去斑点强度',
                  dewarp='曲面展平', distortion_model='手动展平曲线', depth='展平深度', top_spline='上边界样条', bottom_spline='下边界样条',
                  point='控制点坐标', tension='曲线张力', fill_color='边缘填充颜色', fill_margins='填充页边距', fill_offcut='填充裁切边缘',
                  fill_outside_page='填充纸张外部', normalize_bw='黑白亮度归一', normalize_color='彩色亮度归一',
                  black_on_white='黑字白底', morphological_smoothing='形态平滑', savitzky_golay='曲线平滑滤波',
                  wiener_window='维纳滤波窗口', wiener_coefficient='维纳滤波系数', posterize='减少色阶', posterize_level='色阶数量',
                  posterize_normalize='色阶亮度归一', posterize_force_bw='强制黑白色阶', color_segmentation='颜色分割',
                  segment_noise='颜色分割降噪', segment_red='红色阈值', segment_green='绿色阈值', segment_blue='蓝色阈值',
                  split_output='分别输出图层', foreground='前景模式', original_background='保留原始背景',
                  picture_shape='图片检测形状', picture_sensitivity='图片检测灵敏度', picture_high_sensitivity='高灵敏度检测',
                  sauvola_coefficient='Sauvola 系数', wolf_coefficient='Wolf 系数', wolf_lower='Wolf 灰度下限', wolf_upper='Wolf 灰度上限',
                  post_deskew='输出后纠偏', post_deskew_angle='输出后纠偏角度', deskew_algorithm='纠偏依据',
                  freeze_layout='冻结页面尺寸', frozen_size_mm='冻结尺寸（宽,高，毫米）', guides='布局辅助线', position='辅助线位置',
                  page_detection_size_mm='预期纸张尺寸（毫米）', page_detection_tolerance='纸张检测容差', show_middle_rect='显示中间区域',
                  images='源图序号', ids='逻辑页稳定标识', image_ids='源图稳定标识', parity='奇偶页', side='拆分位置',
                  max_angle='疑难角度阈值（度）', min_page_ratio='最小保留面积比例', existing_output='已有结果处理方式'))
VALUES = dict(auto='自动', off='关闭', manual='手动', single='不拆分', two='左右双页', cut='裁掉边缘页',
              colorOrGray='保留颜色与灰度', bw='黑白', mixed='混合', source='源图坐标', oriented='旋转后的坐标',
              deskew='纠偏后的坐标', ltr='从左到右', rtl='从右到左', preserve='保留原页并标记复核', report='生成结果并标记复核',
              original='保留原始', processed='按处理后尺寸', reject='保留已有结果，不覆盖', overwrite='重新生成并覆盖此任务已有结果',
              odd='奇数页', even='偶数页', left='左侧', right='右侧', center='居中', top='顶部', bottom='底部',
              horizontal='水平', vertical='垂直', white='白色', black='黑色', background='背景', foreground='前景',
              rectangular='矩形', free='自由形状', noop='不改变', picture='图片区域', marginal='边缘展平', color='彩色')
IMAGE = {'.png', '.tif', '.tiff', '.jpg', '.jpeg', '.bmp'}


def label(key):
    return LABELS.get(key, key)


def summary(value):
    if isinstance(value, dict):
        return '、'.join(label(k) for k in value) or '(沿用已有值)'
    if isinstance(value, list):
        return f'{len(value)} 项 ' + str(value)[:70]
    if type(value) is bool:
        return '开启' if value else '关闭'
    return VALUES.get(value, str(value))


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
            rows += [('▸ ' if p.is_dir() else ('[✓] ' if p in chosen else '[ ] ')) + p.name for p in entries]
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
            choice = self.c.choose(title, [VALUES.get(v, str(v)) for v in options], 'Esc 放弃此字段')
            return (False, original) if choice is None else (True, options[choice])
        kind = schema['type']
        if kind == 'boolean':
            choice = self.c.choose(title, ['开启', '关闭'])
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
            count = f'{done} / {total} 页' if total else '正在准备，请稍候'
            seconds = int(elapsed_seconds(progress))
            frame.text(3, 1, STATES.get(status, status), ACCENT)
            frame.text(3, 3, '任务使用固定配置；取消后等待检查点保存完成。', MUTED)
            frame.rule(3, 4, width - 7)
            frame.text(4, 6, label(progress['stage']) + '    ' + count)
            bar_width = max(4, min(50, width - 10))
            frame.text(4, 8, '━' * int(percent * bar_width) + '─' * (bar_width - int(percent * bar_width)), ACCENT)
            frame.text(4, 10, '当前文件  ' + Path(progress['current']).name)
            frame.text(4, 12, '输出位置  ' + (self.m.last or {}).get('output', ''), MUTED)
            frame.text(4, 14, f'已用时间  {seconds // 60:02d}:{seconds % 60:02d}', MUTED)
            labels = ['请求取消' if self.m.running else '查看结果', '返回工作台', '详细日志']
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
                self.message('详细日志', logs)
                self.c.flush()

    def execute(self, command='process', sample=False):
        plan = self.m.plan(command, sample)
        previous = plan['match']
        if previous:
            complete = previous.get('outcome_complete', previous.get('status') == 'complete')
            rows = ['打开已有结果' if complete and plan['valid'] else '继续未完成任务（沿用当时设置）', '覆盖重做', '取消']
            hint = '输入与设置相同。' + ('已有结果校验通过。' if plan['valid'] else '已有结果需要校验，缺失或变化部分会重算。')
            choice = self.c.choose('发现已有任务', rows, hint)
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
            hint = ('仅处理首、中、尾源页（或指定源页）；拆页后数量可增加，不计算整书统一布局。'
                    if sample else '精确任务：需要完整项目的分析和布局。有效 PDF 渲染缓存将自动复用。')
            stage = 'output' if command == 'process' else self.m.options['stage']
            hint = f'共 {plan["source_count"]} 个源页，本次 {plan["selected_count"]} 个；阶段 {stage}。' + hint
            if conflict:
                hint += '\n设置差异：' + '；'.join(plan['changes'][:5])
            hint += '\n复用数需校验缓存后确定；最坏需处理本次全部源页。'
            self.message('执行计划', hint)
            rows = ['确认执行', '取消']
            if occupied:
                rows = ['覆盖此输出目录中的任务结果', '取消']
                hint += ' 输出目录已有文件；只替换本次目标，其他文件保留。'
            if conflict and not conflict.get('outcome_complete', conflict.get('status') == 'complete'):
                choice = self.c.choose('发现未完成的旧任务', ['继续旧任务（沿用当时设置）', '按当前设置重新处理', '取消'], '旧任务不采用本次配置修改。')
                if choice == 0:
                    self.m.last = conflict; self.m.start(resume=True); self.monitor(); return
                if choice != 1: return
            choice = self.c.choose('执行前确认', rows, hint.splitlines()[0])
            if choice != 0: return
            if occupied: decision = 'overwrite'
        if decision == 'overwrite':
            if self.c.choose('确认覆盖重做', ['取消', '确认覆盖本次目标'], '旧 PDF 在新结果验证成功后才替换。') != 1:
                return
        self.m.start(command, sample=sample, decision=decision)
        self.monitor()

    def results(self):
        from .workbench import STATES
        if not self.m.last:
            self.message('暂无任务', '先选择输入和输出，再运行任务')
            return
        root = Path(self.m.last['output'])
        while True:
            viewer = root / 'preview.html'
            rows = ['打开原图 / 结果对比' if viewer.exists() else '打开结果目录', '查看任务日志', '打开生成的项目', '打开复核 / 预览报告', '校验并补齐结果（沿用当时设置）' if self.m.last.get('status') == 'complete' else '继续未完成任务（沿用当时设置）']
            status = self.m.last.get('status', 'unknown')
            seconds = self.m.last.get('elapsed_seconds')
            hint = str(root)
            if isinstance(seconds, (int, float)):
                hint = f'耗时 {int(seconds) // 60:02d}:{int(seconds) % 60:02d} · {hint}'
            choice = self.c.choose(STATES.get(status, status), rows, hint)
            if choice is None:
                return
            if choice == 0:
                os.startfile(viewer if viewer.exists() else root)
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
                if self.c.choose('继续历史任务', ['继续', '取消'], '使用此任务当时的输入、设置和操作；不采用首页新配置，预览不会变成整批处理。') != 0: return
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
        from .workbench import Workbench
        return Workbench(self).run()

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
        ok, value = self.edit('运行选项', {'type': 'object', 'properties': props, 'required': list(props)}, current)
        if ok:
            self.m.update_options(value)

    def presets(self):
        choice = self.c.choose('预设', ['保存当前设置', '载入 schema 2 配置', 'physics-safe', '清除覆盖 / 沿用项目', '恢复默认配置（含 DPI 与并发）'])
        if choice == 0:
            folder = self.m.new_folder()
            write_json(folder / 'preset.json', self.m.config)
            self.message('已保存', folder / 'preset.json')
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
    parser.add_argument('--state-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ScanTailorCLI' / 'menu')
    args = parser.parse_args()
    try:
        with Console() as console:
            model = Controller(args.cli, args.state_dir)
            ui = UI(console, model)
            if model.preference_error: ui.message('设置加载提示', model.preference_error)
            return ui.run()
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 3
