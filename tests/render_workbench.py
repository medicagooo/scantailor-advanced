"""Render the actual cell layout as PNGs for repeatable visual inspection."""
import argparse
from pathlib import Path
import re
import sys
import unicodedata
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scantailor_menu.model import Controller
from scantailor_menu.ui import UI
from scantailor_menu.workbench import Workbench
from scantailor_menu.rendering import cells


def render(frame, target):
    cw, ch = 11, 28
    image = Image.new('RGB', ((frame.width + 1) * cw, frame.height * ch), '#0f1724')
    draw = ImageDraw.Draw(image)
    mono = ImageFont.truetype('C:/Windows/Fonts/consola.ttf', 20)
    chinese = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 19)
    for y, spans in enumerate(frame.rows):
        for x, style, text in spans:
            background = re.findall(r'48;2;(\d+);(\d+);(\d+)m', style)
            foreground = re.findall(r'38;2;(\d+);(\d+);(\d+)m', style)
            bg = tuple(map(int, background[-1])) if background else (15, 23, 36)
            fg = tuple(map(int, foreground[-1])) if foreground else (220, 228, 240)
            draw.rectangle((x*cw, y*ch, (x+cells(text))*cw, (y+1)*ch-1), fill=bg)
            offset = 0
            for c in text:
                draw.text(((x+offset)*cw, y*ch+2), c, font=chinese if ord(c) >= 0x2e80 else mono, fill=fg)
                offset += 0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1
    image.save(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    model = Controller(args.cli, args.output / 'state')
    bench = Workbench(UI(None, model))
    for width, height in [(120, 34), (80, 25), (60, 22)]:
        frame, controls = bench.frame(width, height)
        render(frame, args.output / f'workbench-{width}.png')
