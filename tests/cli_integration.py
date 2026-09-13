"""End-to-end CLI/PDF contract tests; run with --cli path/to/scantailor-cli.exe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat
import pymupdf

if os.name == "nt":
    import ctypes
    # A missing DLL must fail the test rather than leave a loader dialog open.
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)

ROOT = Path(__file__).resolve().parents[1]
CLI = None
ARTIFACTS = None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture(path, angle=0, blank=False):
    image = Image.new("RGB", (1000, 1400), "white")
    if not blank:
        draw = ImageDraw.Draw(image)
        font_path = Path("C:/Windows/Fonts/msyh.ttc")
        font = ImageFont.truetype(str(font_path), 23) if font_path.exists() else ImageFont.load_default(size=23)
        for row in range(18):
            draw.text((80, 85 + row*52), f"{row+1}. 物理试题 F = ma   U = IR   v = s/t   0.05 N", fill="black", font=font)
        draw.line([(120, 1200), (700, 1200), (700, 1100), (120, 1100), (120, 1200)], fill="black", width=2)
        draw.ellipse((310, 1080, 350, 1120), outline="black", width=2)
        draw.line((780, 1000, 900, 1230), fill="black", width=2)
    if angle:
        image = image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor="white")
    image.save(path, dpi=(150, 150))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cli-中文-", dir=ARTIFACTS)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "输入 图片"
        self.inputs.mkdir()

    def tearDown(self):
        intended_parent = Path(ARTIFACTS or tempfile.gettempdir()).resolve()
        self.assertEqual(self.root.resolve().parent, intended_parent)
        self.temp.cleanup()

    def invoke(self, *args, accepted=(0,), timeout=120):
        result = subprocess.run([str(CLI), *map(str, args)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
        self.assertIn(result.returncode, accepted, result.stdout + result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        return events

    def process(self, output, *extra, accepted=(0,)):
        return self.invoke("process", "--input", self.inputs, "--output", output, *extra, accepted=accepted)

    def test_help_doctor_validation(self):
        self.assertEqual(subprocess.run([str(CLI), "--help"], capture_output=True).returncode, 0)
        self.assertEqual(self.invoke("doctor")[-1]["status"], "ok")
        self.invoke("process", "--bogus", accepted=(2,))
        self.invoke("process", "--input", self.inputs, "--output", self.root / "out", "--jobs", "0", accepted=(2,))

    def test_identity_pixels_and_project_replay(self):
        fixture(self.inputs / "001.png")
        output = self.root / "out"
        self.process(output, "--deskew", "off", "--page-detection", "off")
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        result = Path(report["pages"][0]["output"])
        with Image.open(self.inputs / "001.png") as source, Image.open(result) as processed:
            self.assertEqual(source.size, processed.size)
            self.assertLess(max(ImageStat.Stat(ImageChops.difference(source.convert("RGB"), processed.convert("RGB"))).mean), 0.5)
        replay = self.root / "replay"
        self.invoke("process", "--project", output / "project.scan", "--output", replay)
        replay_report = json.loads((replay / "report.json").read_text(encoding="utf-8"))
        with Image.open(result) as a, Image.open(replay_report["pages"][0]["output"]) as b:
            self.assertIsNone(ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox())

    def test_auto_deskew_and_fallback(self):
        fixture(self.inputs / "001.png", angle=2)
        fixture(self.inputs / "002.png", blank=True)
        output = self.root / "out"
        self.process(output, "--jobs", "2", accepted=(0, 1))
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["pages"]), 2)
        metric = report["pages"][0]["metrics"]["deskew_angle"]
        self.assertAlmostEqual(abs(metric), 2, delta=0.5)
        for page in report["pages"]:
            self.assertIn(page["status"], ("complete", "review"))
            with Image.open(page["output"]) as image:
                self.assertTrue(all(v >= 245 for v in image.convert("RGB").getpixel((0, 0))))

    def test_resume_tamper_and_changed_input(self):
        fixture(self.inputs / "001.png")
        output = self.root / "out"
        flags = ("--deskew", "off", "--page-detection", "off")
        self.process(output, *flags)
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        image = Path(report["pages"][0]["output"])
        stamp = image.stat().st_mtime_ns
        events = self.process(output, *flags, "--resume")
        self.assertTrue(any(e["event"] == "page_reused" for e in events))
        self.assertEqual(stamp, image.stat().st_mtime_ns)
        image.write_bytes(b"broken output")
        self.process(output, *flags, "--resume")
        with Image.open(image) as check:
            check.load()
        source = self.inputs / "001.png"
        stat = source.stat()
        with Image.open(source) as changed:
            changed.putpixel((100, 100), (255, 0, 0)); changed.save(source, dpi=(150, 150))
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        events = self.process(output, *flags, "--resume")
        self.assertTrue(any(e["event"] == "invalidated" for e in events))
        self.assertFalse(any(e["event"] == "page_reused" for e in events))

    def test_corrupt_input_and_no_overwrite(self):
        fixture(self.inputs / "001.png")
        (self.inputs / "002.png").write_bytes(b"broken input")
        output = self.root / "out"
        self.process(output, "--deskew", "off", "--page-detection", "off", accepted=(1,))
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["complete"], 1)
        sha = digest(output / "001.png")
        self.process(output, accepted=(3,))
        self.assertEqual(sha, digest(output / "001.png"))

    def test_pdf_page_order_size_and_resume(self):
        fixture(self.inputs / "001.png")
        folder = self.root / "PDF"
        folder.mkdir()
        source = folder / "物理 试题.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page(width=480, height=640)
            page.insert_image(page.rect, filename=str(self.inputs / "001.png"))
            page = doc.new_page(width=600, height=800)
            page.insert_image(page.rect, filename=str(self.inputs / "001.png"))
            doc.set_toc([[1, "第一章", 1], [1, "第二章", 2]])
            doc.save(source)
        before = digest(source)
        command = [sys.executable, str(ROOT / "scripts/process_pdf_folder.py"), "--pdf-dir", str(folder), "--cli", str(CLI), "--dpi", "150"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
        report = json.loads((folder / "scantailor-output/_scantailor/batch-report.json").read_text(encoding="utf-8"))
        self.assertFalse(report["failures"], report)
        final = Path(report["results"][0]["output"])
        with pymupdf.open(final) as doc:
            self.assertEqual(doc.page_count, 2)
            self.assertEqual([(p.rect.width, p.rect.height) for p in doc], [(480, 640), (600, 800)])
            self.assertEqual(len(doc.get_toc()), 2)
        self.assertEqual(before, digest(source))
        stamp = final.stat().st_mtime_ns
        resumed = subprocess.run(command + ["--resume"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertIn(resumed.returncode, (0, 1), resumed.stdout + resumed.stderr)
        self.assertEqual(stamp, final.stat().st_mtime_ns)

    @unittest.skipUnless(os.name == "nt", "Windows console cancellation")
    def test_cancel_and_resume(self):
        for index in range(8):
            fixture(self.inputs / f"{index:03d}.png", angle=2)
        output = self.root / "out"
        log = self.root / "events.jsonl"
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen([str(CLI), "process", "--input", str(self.inputs), "--output", str(output)],
                                       stdout=stream, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if 'page_started' in log.read_text(encoding="utf-8"):
                    break
                self.assertIsNone(process.poll())
                time.sleep(0.05)
            process.send_signal(signal.CTRL_BREAK_EVENT)
            self.assertEqual(process.wait(timeout=30), 130)
        self.process(output, "--resume", accepted=(0, 1))
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["pages"]), 8)
        self.assertEqual(report["errors"], 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path)
    options, rest = parser.parse_known_args()
    CLI = options.cli.resolve()
    ARTIFACTS = options.artifacts
    if ARTIFACTS:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
    unittest.main(argv=[sys.argv[0], *rest])
