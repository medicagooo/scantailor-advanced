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


def clean(text):
    return ''.join(c for c in str(text) if c >= ' ' and c != '\x7f' and unicodedata.category(c) not in ('Cc', 'Cs', 'Cf'))


def fit(text, width):
    result, used = '', 0
    for c in clean(text):
        size = 0 if unicodedata.combining(c) else (2 if unicodedata.east_asian_width(c) in 'WF' else 1)
        if used + size > width:
            break
        result += c
        used += size
    return result


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
            # Alt/Ctrl shortcuts are excluded; AltGr text is handled by Windows.
            if k.mods & 0x0f:
                return None
            names = {13: 'enter', 27: 'escape', 38: 'up', 40: 'down', 33: 'pgup', 34: 'pgdown',
                     36: 'home', 35: 'end', 9: 'tab', 32: 'space', 8: 'backspace', 46: 'delete'}
            if repeated and k.vk not in (38, 40, 33, 34, 8):
                return None
            if text and k.char and k.char >= ' ':
                return ('text', k.char)
            if k.vk in names:
                return (names[k.vk], None)
        elif record.type == 2:
            m = record.event.mouse
            down = bool(m.buttons & 1)
            click = down and not self.mouse_down and m.flags == 0
            self.mouse_down = down
            if click:
                return ('click', (m.pos.X, m.pos.Y))
            if m.flags == 4:
                return ('up' if C.c_short(m.buttons >> 16).value > 0 else 'down', None)
        elif record.type == 4:
            return ('resize', None)
        return None

    def paint(self, title, rows, selected=0, hint='', offset=0):
        size = shutil.get_terminal_size((100, 30))
        self.width, self.height = max(20, size.columns), max(8, size.lines)
        visible = self.height - 6
        offset = max(0, min(offset, max(0, len(rows) - visible)))
        if selected < offset:
            offset = selected
        if selected >= offset + visible:
            offset = selected - visible + 1
        lines = ['\x1b[1;36m' + fit(title, self.width - 1) + '\x1b[0m', fit(hint, self.width - 1), '']
        for i, row in enumerate(rows[offset:offset + visible], offset):
            line = fit(('> ' if i == selected else '  ') + row, self.width - 1)
            lines.append(('\x1b[7m' + line + '\x1b[0m') if i == selected else line)
        lines += [''] * (self.height - 2 - len(lines))
        lines += [fit('↑↓/Tab 选择 · Enter/单击确认 · Esc 返回 · PgUp/PgDn 翻页', self.width - 1)]
        sys.stdout.write('\x1b[H' + '\r\n'.join(line + '\x1b[K' for line in lines) + '\x1b[J')
        sys.stdout.flush()
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
            if action == 'click':
                x, y = value
                index = y - 3 + offset
                if 0 <= x < self.width and 3 <= y < self.height - 3 and 0 <= index < len(rows):
                    return index

    def text(self, title, initial='', hint='', numeric=False):
        self.flush()
        value = str(initial)
        while True:
            self.paint(title, [fit(value[-(self.width - 5):], self.width - 5), '[确定 / Enter]', '[取消 / Esc]'], 0,
                       hint + ' · Backspace 删除 · Delete 清空')
            event = self.read(text=True)
            if not event:
                continue
            action, data = event
            if action == 'escape' or (action == 'click' and data[1] == 5):
                return None
            if action == 'enter' or (action == 'click' and data[1] == 4):
                return value
            if action == 'backspace':
                value = value[:-1]
            elif action == 'delete':
                value = ''
            elif action == 'text' and (not numeric or data in '0123456789.-+'):
                if len(value) < 32767:
                    value += clean(data)
