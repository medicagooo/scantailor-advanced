"""Process an actual PNG through the staged CLI without third-party Python libs."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def check(cli):
    with tempfile.TemporaryDirectory(prefix='scantailor-package-') as scratch:
        root = Path(scratch)
        inputs = root / 'inputs'
        inputs.mkdir()
        width, height = 120, 160
        rows = b''.join(b'\0' + b''.join(b'\0\0\0' if 25 < x < 95 and y % 20 < 3 else b'\xff\xff\xff'
                                       for x in range(width)) for y in range(height))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')
        (inputs / 'page.png').write_bytes(png)
        output = root / 'output'
        result = subprocess.run([str(cli), 'process', '--input', str(inputs), '--output', str(output),
                                 '--dpi', '100', '--deskew', 'off', '--page-detection', 'off'],
                                capture_output=True, text=True, encoding='utf-8', timeout=90)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        if len(report['pages']) != 1:
            raise RuntimeError('Packaged CLI did not process exactly one page')
        image = Path(report['pages'][0]['output'])
        if not image.is_absolute():
            image = output / image
        if not image.is_file() or image.stat().st_size == 0:
            raise RuntimeError('Packaged CLI produced no image')
        print('Staged CLI image processing passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', type=Path, required=True)
    args = parser.parse_args()
    check(args.cli.resolve())
