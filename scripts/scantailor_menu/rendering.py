"""Cell-aware terminal drawing with explicit hit regions and diffed frames."""
import unicodedata

BG = '\x1b[48;2;15;23;36m'
FG = '\x1b[38;2;220;228;240m'
MUTED = '\x1b[38;2;139;156;178m'
ACCENT = '\x1b[38;2;91;219;209m'
SELECT = '\x1b[48;2;26;65;77m\x1b[38;2;225;255;253m'
BORDER = '\x1b[38;2;49;69;88m'
DISABLED = '\x1b[38;2;91;107;127m'
WARN = '\x1b[38;2;248;194;105m'


def clean(text):
    return ''.join(c for c in str(text) if c >= ' ' and c != '\x7f' and unicodedata.category(c) not in ('Cc', 'Cs', 'Cf'))


def cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in clean(text))


def fit(text, width):
    result, used = '', 0
    for c in clean(text):
        size = 0 if unicodedata.combining(c) else (2 if unicodedata.east_asian_width(c) in 'WF' else 1)
        if used + size > max(0, width):
            break
        result += c
        used += size
    return result


class Frame:
    def __init__(self, width, height):
        self.width, self.height = max(1, width - 1), max(1, height)
        self.rows = [[] for _ in range(self.height)]
        self.hits = []

    def text(self, x, y, text, style=FG, width=None):
        if not 0 <= y < self.height or x >= self.width:
            return
        width = min(self.width - x, width if width is not None else self.width - x)
        text = fit(text, width)
        self.rows[y].append((max(0, x), style, text))

    def rule(self, x, y, width, title=''):
        self.text(x, y, '─' * max(0, width), BORDER, width)
        if title:
            self.text(x + 2, y, ' ' + title + ' ', ACCENT, width - 4)

    def button(self, x, y, width, title, key, selected=False, enabled=True, detail=''):
        style = SELECT if selected else FG if enabled else DISABLED
        prefix = ' › ' if selected else '   '
        line = fit(prefix + title, width)
        self.text(x, y, line + ' ' * max(0, width - cells(line)), style, width)
        if enabled:
            self.hits.append((x, y, width, 1, key))
        if detail:
            self.text(x + 3, y + 1, detail, MUTED, width - 4)

    def hit(self, position):
        x, y = position
        return next((key for bx, by, bw, bh, key in self.hits if bx <= x < bx + bw and by <= y < by + bh), None)

    def lines(self):
        lines = []
        for spans in self.rows:
            # Explicit cursor positions let panels overlap without losing CJK cell widths.
            line = BG + FG + '\x1b[2K'
            for x, style, text in spans:
                line += f'\x1b[{x + 1}G' + BG + style + text
            lines.append(line)
        return lines
