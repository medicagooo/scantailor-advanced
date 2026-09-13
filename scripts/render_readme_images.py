"""Export the real CLI layout for README illustrations without driving a terminal.

Uses Workbench.frame and Workbench.encoding -> Console.paint; only the input /
output labels are replaced by generic examples. No processing results are mocked.
Run with the repository PDF dependencies installed and a built CLI executable.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'scripts')]
from render_workbench import render
from scantailor_menu.console import Console
from scantailor_menu.model import Controller
from scantailor_menu.ui import UI
from scantailor_menu.workbench import Workbench
from scantailor_menu.i18n import NAMES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--language', choices=list(NAMES), default='en')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    model = Controller(args.cli, args.state_dir, language=args.language)
    model.kind = 'pdf'
    model.inputs = [r'D:\Scans\test file.pdf']
    model.output = r'D:\Scans\clean'
    model.config = {'schema_version': 2, 'preset': 'physics-safe',
                    'image_encoding': {'format': 'png', 'png_compression': 6}}
    bench = Workbench(UI(None, model))
    frame, _ = bench.frame(120, 30)
    render(frame, args.output / 'cli-workbench.png')

    class CaptureConsole:
        width, height = 100, 15
        output_name = "cli-image-encoding.png"
        def dimensions(self):
            return self.width, self.height
        def draw(self, frame):
            render(frame, args.output / self.output_name)
        def choose(self, title, rows, hint='', **kwargs):
            Console.paint(self, title, rows, hint=hint, selected=kwargs.get("selected", 0))
            return None  # Capture the initial dialog, then cancel the local draft.

    bench.c = CaptureConsole()
    bench.encoding(model.config['image_encoding'])
    bench.c.output_name = 'cli-language.png'
    UI(bench.c, model).choose_language()
    print('Exported three PNGs from the CLI production layout.')


if __name__ == '__main__':
    main()
