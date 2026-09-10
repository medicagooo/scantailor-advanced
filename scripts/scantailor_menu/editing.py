"""Text editing and path parsing shared by native clipboard and terminal paste.

Pasted text is data only. Multiline fields require an explicit apply button or
Ctrl+Enter; embedded newlines can never activate the next screen's action.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re


def paste_text(value, multiline=False):
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    value = ''.join(c for c in value if c >= ' ' or c in '\n\t')
    return value.replace('\t', ' ').replace('\n', '\n' if multiline else ' ')


@dataclass
class Editor:
    value: str = ''
    cursor: int = 0
    anchor: int | None = None
    multiline: bool = False
    numeric: bool = False

    def __post_init__(self):
        self.cursor = len(self.value)

    @property
    def selection(self):
        return sorted((self.cursor, self.anchor if self.anchor is not None else self.cursor))

    def insert(self, value):
        value = paste_text(value, self.multiline)
        if not value:
            return True
        if self.numeric and any(c not in '0123456789.-+' for c in value):
            return False
        begin, end = self.selection
        if len(self.value) - (end - begin) + len(value) > 32767:
            return False
        self.value = self.value[:begin] + value + self.value[end:]
        self.cursor, self.anchor = begin + len(value), None
        return True

    def move(self, direction, selecting=False):
        if selecting and self.anchor is None:
            self.anchor = self.cursor
        if not selecting:
            self.anchor = None
        if direction == 'home':
            self.cursor = self.value.rfind('\n', 0, self.cursor) + 1
        elif direction == 'end':
            end = self.value.find('\n', self.cursor)
            self.cursor = len(self.value) if end < 0 else end
        else:
            self.cursor = max(0, min(len(self.value), self.cursor + direction))

    def delete(self, backwards=False):
        begin, end = self.selection
        if begin == end:
            if backwards:
                begin = max(0, begin - 1)
            else:
                end = min(len(self.value), end + 1)
        self.value = self.value[:begin] + self.value[end:]
        self.cursor, self.anchor = begin, None

    def select_all(self):
        self.anchor, self.cursor = 0, len(self.value)


def parse_paths(text):
    """Accept Explorer Copy as path, one path per line, or quoted path lists."""
    paths = []
    for line in paste_text(text, True).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.findall(r'"([^"\r\n]+)"', line)
        if parts and not re.sub(r'"[^"\r\n]+"', '', line).strip():
            candidates = parts
        else:
            candidates = [line.strip('"')]
        for item in candidates:
            path = Path(os.path.expandvars(item)).expanduser()
            key = str(path).casefold()
            if key not in {str(p).casefold() for p in paths}:
                paths.append(path)
    return paths
