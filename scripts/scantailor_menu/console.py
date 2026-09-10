"""Win32 input records, shared keyboard/mouse selection and isolated modal input.

No global hooks: Windows shortcuts belong to the terminal/OS. Console modes
are restored even when a form or worker fails. Rendering uses an alternate VT
buffer; untrusted filenames/logs are stripped of control characters.
"""
import ctypes as C
from ctypes import wintypes as W
import shutil
import sys
import unicodedata
import time
from .editing import Editor
from .rendering import Frame, BG, FG, MUTED, ACCENT, SELECT, WARN, clean, fit, cells


class Coord(C.Structure):
    _fields_ = [('X', W.SHORT), ('Y', W.SHORT)]
class Key(C.Structure):
    _fields_ = [('down', W.BOOL), ('repeat', W.WORD), ('vk', W.WORD), ('scan', W.WORD), ('char', W.WCHAR), ('mods', W.DWORD)]
class Mouse(C.Structure):
    _fields_ = [('pos', Coord), ('buttons', W.DWORD), ('mods', W.DWORD), ('flags', W.DWORD)]
class Payload(C.Union):
    _fields_ = [('key', Key), ('mouse', Mouse), ('size', Coord), ('padding', C.c_byte * 16)]
class Record(C.Structure):
    _fields_ = [('type', W.WORD), ('event', Payload)]


class Console:
    def __init__(self):
        self.api = C.WinDLL('kernel32', use_last_error=True)
        self.api.GetStdHandle.restype = W.HANDLE
        self.api.GetConsoleMode.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
        self.api.SetConsoleMode.argtypes = [W.HANDLE, W.DWORD]
        self.api.ReadConsoleInputW.argtypes = [W.HANDLE, C.POINTER(Record), W.DWORD, C.POINTER(W.DWORD)]
        self.api.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        self.api.FlushConsoleInputBuffer.argtypes = [W.HANDLE]
        self.input = self.api.GetStdHandle(-10)
        self.output = self.api.GetStdHandle(-11)
        self.imode, self.omode = W.DWORD(), W.DWORD()
        if not self.api.GetConsoleMode(self.input, C.byref(self.imode)) or not self.api.GetConsoleMode(self.output, C.byref(self.omode)):
            raise RuntimeError('Menu requires an interactive Windows console')
        self.held = set()
        self.mouse_down = False
        self.width, self.height = 80, 25
        self.previous = []
        self.frame = None
        self.right_down = False
        self.surrogate = ''
        self.user = C.WinDLL('user32', use_last_error=True)
        self.user.GetClipboardData.argtypes = [W.UINT]
        self.user.GetClipboardData.restype = W.HANDLE
        self.user.OpenClipboard.argtypes = [W.HWND]
        self.api.GlobalLock.argtypes = [W.HGLOBAL]
        self.api.GlobalLock.restype = C.c_void_p
        self.api.GlobalUnlock.argtypes = [W.HGLOBAL]

    def clipboard(self):
        opened = False
        # Clipboard owners may hold it briefly while rendering delayed formats.
        for delay in (0, .025, .05, .1):
            if delay:
                time.sleep(delay)
            if self.user.OpenClipboard(None):
                opened = True
                break
        if not opened:
            raise OSError('剪贴板暂时被其他程序占用，请再粘贴一次。')
        try:
            handle = self.user.GetClipboardData(13)  # CF_UNICODETEXT, read only.
            if not handle:
                return ''
            pointer = self.api.GlobalLock(handle)
            if not pointer:
                raise OSError('无法读取剪贴板文本。')
            try:
                return C.wstring_at(pointer)
            finally:
                self.api.GlobalUnlock(handle)
        finally:
            self.user.CloseClipboard()

    def __enter__(self):
        # EXTENDED_FLAGS disables QuickEdit; no line, echo or processed input.
        if not self.api.SetConsoleMode(self.input, 0x80 | 0x10 | 0x08):
            raise C.WinError(C.get_last_error())
        if not self.api.SetConsoleMode(self.output, self.omode.value | 0x04):
            self.api.SetConsoleMode(self.input, self.imode.value)
            raise RuntimeError('VT output unavailable; use Windows Terminal or a current console host')
        sys.stdout.write('\x1b[?1049h\x1b[?25l')
        sys.stdout.flush()
        return self

    def __exit__(self, *args):
        try:
            sys.stdout.write('\x1b[0m\x1b[?25h\x1b[?1049l')
            sys.stdout.flush()
        finally:
            self.api.SetConsoleMode(self.input, self.imode.value)
            self.api.SetConsoleMode(self.output, self.omode.value)

    def flush(self):
        # Drain through the decoder so queued releases update held state.
        # Discarding them with FlushConsoleInputBuffer leaves phantom keys.
        while self.api.WaitForSingleObject(self.input, 0) == 0:
            self.read(0)

    def read(self, timeout=150, text=False):
        if self.api.WaitForSingleObject(self.input, timeout) != 0:
            return None
        record, count = Record(), W.DWORD()
        if not self.api.ReadConsoleInputW(self.input, C.byref(record), 1, C.byref(count)):
            raise C.WinError(C.get_last_error())
        if record.type == 1:
            k = record.event.key
            if not k.down:
                self.held.discard(k.vk)
                return None
            repeated = k.vk in self.held
            self.held.add(k.vk)
            ctrl, shift = bool(k.mods & 12), bool(k.mods & 16)
            if text and not repeated:
                if (ctrl and k.vk == 86) or (shift and k.vk == 45) or k.char == '\x16':
                    return ('paste', None)
                if ctrl and k.vk == 65:
                    return ('select_all', None)
                if ctrl and k.vk == 13:
                    return ('submit', None)
            if k.mods & 0x0f:
                return None
            names = {13: 'enter', 27: 'escape', 38: 'up', 40: 'down', 33: 'pgup', 34: 'pgdown',
                     36: 'home', 35: 'end', 37: 'left', 39: 'right', 9: 'tab', 32: 'space', 8: 'backspace', 46: 'delete'}
            if text and k.char and k.char >= ' ':
                char = k.char
                if 0xD800 <= ord(char) <= 0xDBFF:
                    self.surrogate = char
                    return None
                if self.surrogate:
                    char = (self.surrogate + char).encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace')
                    self.surrogate = ''
                return ('text', char * max(1, min(k.repeat, 64)))
            if repeated and k.vk not in (38, 40, 33, 34, 8, 46, 37, 39):
                return None
            if k.vk in names:
                return (names[k.vk], shift)
        elif record.type == 2:
            m = record.event.mouse
            down = bool(m.buttons & 1)
            click = down and not self.mouse_down and m.flags == 0
            self.mouse_down = down
            right = bool(m.buttons & 2)
            paste = right and not self.right_down and m.flags == 0
            self.right_down = right
            if paste and text:
                return ('paste', None)
            if click:
                return ('click', (m.pos.X, m.pos.Y))
            if m.flags == 1:
                return ('hover', (m.pos.X, m.pos.Y))
            if m.flags == 4:
                return ('up' if C.c_short(m.buttons >> 16).value > 0 else 'down', None)
        elif record.type == 4:
            return ('resize', None)
        return None

    def dimensions(self):
        size = shutil.get_terminal_size((100, 30))
        self.width, self.height = max(1, size.columns), max(1, size.lines)
        return self.width, self.height

    def draw(self, frame):
        lines = frame.lines()
        if len(lines) != len(self.previous):
            self.previous = []
        updates = ''.join(f'\x1b[{y + 1};1H' + line for y, line in enumerate(lines)
                          if y >= len(self.previous) or line != self.previous[y])
        if updates:
            sys.stdout.write(updates + '\x1b[0m')
            sys.stdout.flush()
        self.previous, self.frame = lines, frame

    def paint(self, title, rows, selected=0, hint='', offset=0):
        self.dimensions()
        frame = Frame(self.width, self.height)
        visible = max(1, self.height - 8)
        offset = max(0, min(offset, max(0, len(rows) - visible)))
        if selected < offset:
            offset = selected
        if selected >= offset + visible:
            offset = selected - visible + 1
        frame.text(2, 1, title, ACCENT, self.width - 5)
        frame.text(2, 2, hint, MUTED, self.width - 5)
        frame.rule(2, 3, self.width - 5)
        for i, row in enumerate(rows[offset:offset + visible], offset):
            frame.button(2, 4 + i - offset, self.width - 5, row, i, selected=i == selected)
        frame.rule(2, self.height - 3, self.width - 5)
        frame.text(2, self.height - 2, f'↑↓/Tab 选择   Enter/单击 打开   Esc 返回    {min(selected + 1, len(rows))}/{len(rows)}', MUTED)
        self.draw(frame)
        return offset

    def choose(self, title, rows, hint='', tick=None, selected=0):
        self.flush()
        offset = 0
        while True:
            if tick:
                title, rows, hint = tick()
            selected = max(0, min(selected, len(rows) - 1))
            offset = self.paint(title, rows, selected, hint, offset)
            event = self.read()
            if not event:
                continue
            action, value = event
            if action == 'escape':
                return None
            if action in ('up', 'down', 'tab', 'pgup', 'pgdown', 'home', 'end'):
                delta = {'up': -1, 'down': 1, 'tab': 1, 'pgup': -10, 'pgdown': 10, 'home': -len(rows), 'end': len(rows)}[action]
                selected = max(0, min(len(rows) - 1, selected + delta))
            if action in ('enter', 'space') and rows:
                return selected
            if action in ('click', 'hover'):
                index = self.frame.hit(value)
                if index is not None:
                    selected = index
                    if action == 'click':
                        return index

    def text(self, title, initial='', hint='', numeric=False, multiline=False, validator=None, apply_label='确定'):
        self.flush()
        editor = Editor(str(initial), multiline=multiline, numeric=numeric)
        if initial:
            editor.select_all()
        focus, error = 0, ''
        while True:
            self.dimensions()
            frame = Frame(self.width, self.height)
            if self.width < 48 or self.height < 18:
                frame.text(2, 2, '请放大窗口以编辑内容', ACCENT)
                frame.text(2, 4, '已输入的内容会保留；Esc 取消。', MUTED)
                self.draw(frame)
                event = self.read()
                if event and event[0] == 'escape':
                    return None
                continue
            width = max(8, self.width - 8)
            frame.text(3, 1, title, ACCENT)
            frame.text(3, 3, hint or '支持中文、空格和带引号的路径', MUTED)
            frame.rule(3, 5, width, '输入内容')
            before = editor.value[:editor.cursor]
            line_number = before.count('\n')
            all_lines = editor.value.split('\n')
            top = max(0, line_number - 2)
            current = all_lines[line_number]
            position = len(before.rsplit('\n', 1)[-1])
            left = 0
            while cells(current[left:position]) >= width - 2 and left < position:
                left += 1
            for n, line in enumerate(all_lines[top:top + (4 if multiline else 1)]):
                active = n + top == line_number
                origin = left if active else 0
                visible = line[origin:]
                display = fit(visible, width - 2)
                frame.text(4, 6 + n, display or ' ', FG, width - 2)
                if editor.anchor is not None and focus == 0:
                    start = sum(len(v) + 1 for v in all_lines[:top + n]) + origin
                    begin, end = editor.selection
                    a, b = max(0, begin - start), min(len(display), end - start)
                    if b > a:
                        frame.text(4 + cells(display[:a]), 6 + n, display[a:b], SELECT, width - 2 - cells(display[:a]))
                if active and focus == 0:
                    caret = position - left
                    frame.text(4 + cells(visible[:caret]), 6 + n, '▏', ACCENT, 1)
            button_y = min(self.height - 5, 12 if multiline else 9)
            frame.rule(3, button_y - 2, width)
            frame.text(3, button_y - 1, error or ('已全选，输入或粘贴将替换内容' if editor.anchor is not None else 'Ctrl+A 全选 · ←→ Home/End 移动 · Shift+方向键选择'), WARN if error else MUTED)
            frame.button(3, button_y, min(22, width // 2), apply_label, 'apply', focus == 1)
            frame.button(3 + min(23, width // 2), button_y, min(20, width // 2), '取消', 'cancel', focus == 2)
            frame.hits.append((3, 6, width, 4 if multiline else 1, 'field'))
            frame.text(3, self.height - 2, 'Ctrl+V / Shift+Insert / 右键粘贴 · ' + ('Ctrl+Enter 确认 · Enter 换行' if multiline else 'Enter 确认') + ' · Esc 取消', MUTED)
            self.draw(frame)
            event = self.read(text=True)
            if not event:
                continue
            action, data = event
            hit = frame.hit(data) if action == 'click' else None
            if action == 'escape' or hit == 'cancel' or (action == 'enter' and focus == 2):
                return None
            if action == 'submit' or hit == 'apply' or (action == 'enter' and (focus == 1 or not multiline)):
                try:
                    if validator:
                        validator(editor.value)
                    return editor.value
                except (ValueError, OSError) as problem:
                    error, focus = str(problem), 0
                continue
            if action == 'tab':
                focus = (focus + (-1 if data else 1)) % 3
            elif hit == 'field':
                focus = 0
                clicked = min(len(all_lines) - 1, top + max(0, data[1] - 6))
                offset = left if clicked == line_number else 0
                column = max(0, data[0] - 4)
                while offset < len(all_lines[clicked]) and cells(all_lines[clicked][left if clicked == line_number else 0:offset + 1]) <= column:
                    offset += 1
                editor.cursor = sum(len(line) + 1 for line in all_lines[:clicked]) + offset
                editor.anchor = None
            elif action == 'paste':
                try:
                    if not editor.insert(self.clipboard()):
                        error = '粘贴内容不符合数字格式或超过长度限制。'
                    else:
                        error, focus = '', 0
                except OSError as problem:
                    error = str(problem)
            elif focus == 0:
                if action == 'select_all':
                    editor.select_all()
                elif action in ('left', 'right', 'home', 'end'):
                    editor.move({'left': -1, 'right': 1}.get(action, action), selecting=bool(data))
                elif action in ('backspace', 'delete'):
                    editor.delete(action == 'backspace')
                elif action == 'text':
                    editor.insert(data)
                elif action == 'enter' and multiline:
                    editor.insert('\n')
