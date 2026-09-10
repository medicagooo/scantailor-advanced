"""PDF orchestration for scantailor-cli. No OCR or content reconstruction.

Each PDF has a private work directory; fingerprints include source bytes, CLI
bytes, wrapper version, render settings and config. Final PDFs are published
only after page count, dimensions and renderability have been checked. Images
are fitted proportionally into the original PDF page rectangle; never cropped.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import html
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import pymupdf
from PIL import Image

VERSION = 1


def emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@contextmanager
def directory_lock(folder: Path):
    """OS file lock, automatically released after interruption/crash (Windows)."""
    import msvcrt
    with (folder / ".pdf-batch.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError(f"Another PDF job owns {folder}") from error
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def run_cli(command: list[str], log: Path) -> int:
    # Inherit the console so Ctrl+C reaches the CLI's cancellation handler.
    # stdout goes to JSONL on disk, avoiding pipe buffering deadlocks.
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, stdout=stream)
        try:
            while True:
                try:
                    return process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    emit("processing", log=str(log))
        except KeyboardInterrupt:
            # Allow the native process to checkpoint after the console event.
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait()
            raise


def write_review(work: Path, pages: list[dict]) -> Path:
    review_dir = work / "review"
    review_dir.mkdir(exist_ok=True)
    rows = []
    for page in pages:
        if page["status"] == "complete":
            continue
        number = page["page"]
        source = Path(page["rendered_input"])
        after = Path(page["output_image"]) if page.get("output_image") else source
        links = []
        for label, image_path in (("before", source), ("after", after)):
            with Image.open(image_path) as image:
                image.thumbnail((900, 1200))
                target = review_dir / f"{number:05d}-{label}.png"
                image.convert("RGB").save(target)
            links.append(f'<figure><img src="{target.name}"><figcaption>{label}</figcaption></figure>')
        message = html.escape(json.dumps(page.get("warnings", page.get("message", "Review required")), ensure_ascii=False))
        rows.append(f'<section><h2>Page {number}</h2><p>{message}</p><div>{"".join(links)}</div></section>')
    target = review_dir / "index.html"
    target.write_text('<!doctype html><meta charset="utf-8"><title>Scan review</title>'
                      '<style>body{font-family:system-ui;margin:24px}div{display:flex}figure{width:48%;margin:1%}'
                      'img{max-width:100%}section{border-bottom:1px solid #ccc}</style>'
                      '<h1>Pages requiring review</h1>' + ("".join(rows) or '<p>No pages flagged by automatic checks.</p>'), encoding="utf-8")
    return target


def process_pdf(source: Path, relative: Path, root: Path, args, config_hash: str) -> dict:
    # Include the relative pathname to distinguish equal stems in subdirectories.
    book_id = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:12]
    destination = root / relative.parent / f"{source.stem}.deskew.pdf"
    work = root / ".work" / book_id
    work.mkdir(parents=True, exist_ok=True)
    state_path = work / "state.json"
    previous = load_json(state_path)
    signature = {"version": VERSION, "source": str(source), "source_sha256": sha256(source),
                 "cli_sha256": sha256(args.cli), "dpi": args.dpi, "config_sha256": config_hash,
                 "wrapper_sha256": sha256(Path(__file__)), "pymupdf_version": pymupdf.VersionBind}
    fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    if destination.exists() and not (args.overwrite or (args.resume and previous.get("destination") == str(destination))):
        raise RuntimeError(f"Output exists: {destination}; use --resume or --overwrite")
    if (args.resume and previous.get("fingerprint") == fingerprint and previous.get("status") == "complete"
            and destination.exists() and previous.get("output_sha256") == sha256(destination)):
        emit("pdf_reused", input=str(source), output=str(destination))
        return previous["result"]
    # Changed inputs/config get a new generation. Old intermediates remain
    # available for recovery; never sweep or delete unknown files.
    generation = work / fingerprint[:16]
    images = generation / "input"
    processed = generation / "processed"
    images.mkdir(parents=True, exist_ok=True)
    processed.mkdir(exist_ok=True)
    render_state_path = generation / "render-state.json"
    render_state = load_json(render_state_path)
    rendered = render_state.get("pages", {})
    state = {"schema_version": 1, "fingerprint": fingerprint, "signature": signature,
             "destination": str(destination), "status": "active"}
    save_json(state_path, state)
    with pymupdf.open(source) as original:
        if original.needs_pass:
            raise RuntimeError("Encrypted PDF requires a decrypted input copy")
        if original.page_count == 0:
            raise RuntimeError("PDF has no pages")
        dimensions = []
        for index, page in enumerate(original):
            image_path = images / f"{index+1:05d}.png"
            dimensions.append((page.rect.width, page.rect.height))
            old = rendered.get(str(index), {})
            if not (args.resume and image_path.exists() and old.get("sha256") == sha256(image_path)):
                pix = page.get_pixmap(dpi=args.dpi, colorspace=pymupdf.csRGB, alpha=False)
                temp = image_path.with_suffix(".tmp.png")
                pix.save(temp)
                os.replace(temp, image_path)
                rendered[str(index)] = {"sha256": sha256(image_path)}
                save_json(render_state_path, {"pages": rendered})
            emit("page_rendered", input=str(source), page=index+1, total=original.page_count)
        command = [str(args.cli), "process", "--input", str(images), "--output", str(processed),
                   "--dpi", str(args.dpi), "--jobs", str(args.jobs)]
        if args.config:
            command += ["--config", str(args.config)]
        if (processed / "state.json").exists():
            command += ["--resume"] if args.resume else ["--overwrite"]
        code = run_cli(command, generation / "events.jsonl")
        if code == 130:
            raise KeyboardInterrupt
        if code not in (0, 1):
            raise RuntimeError(f"CLI failed with code {code}; see {generation / 'events.jsonl'}")
        native = load_json(processed / "report.json")
        if native.get("schema_version") != 1:
            raise RuntimeError("Missing or incompatible CLI report")
        by_input = {str(Path(p["input"]).resolve()).casefold(): p for p in native["pages"]}
        reports = []
        result_pdf = pymupdf.open()
        try:
            for index, (width, height) in enumerate(dimensions):
                image_path = images / f"{index+1:05d}.png"
                record = by_input.get(str(image_path.resolve()).casefold(), {})
                status = record.get("status", "error")
                image_out = Path(record.get("output", ""))
                # Preserve the exact original PDF page on any uncertain/error
                # result; don't replace it with another lossy rasterization.
                if status != "complete":
                    result_pdf.insert_pdf(original, from_page=index, to_page=index)
                else:
                    if not image_out.is_file() or record.get("sha256") != sha256(image_out):
                        raise RuntimeError(f"Unverified output for page {index+1}")
                    with Image.open(image_out) as image:
                        buffer = io.BytesIO()
                        image.convert("RGB").save(buffer, format="PNG")
                    target = result_pdf.new_page(width=width, height=height)
                    target.insert_image(target.rect, stream=buffer.getvalue(), keep_proportion=True)
                reports.append({"page": index+1, "status": status,
                    "rendered_input": str(image_path), "output_image": str(image_out) if image_out.is_file() else None,
                    "fallback_original_pdf": status != "complete", "metrics": record.get("metrics", {}),
                    "warnings": record.get("warnings", []), "message": record.get("message", "")})
            # Keep document-level navigation and descriptive metadata when possible.
            result_pdf.set_metadata(original.metadata)
            toc = original.get_toc()
            if toc:
                result_pdf.set_toc(toc)
            destination.parent.mkdir(parents=True, exist_ok=True)
            pending = destination.with_suffix(".pending.pdf")
            result_pdf.save(pending, garbage=3, deflate=True)
        finally:
            result_pdf.close()
        with pymupdf.open(pending) as check:
            if check.page_count != original.page_count:
                raise RuntimeError("Output page count mismatch")
            for index, page in enumerate(check):
                expected = dimensions[index]
                if abs(page.rect.width - expected[0]) > 0.1 or abs(page.rect.height - expected[1]) > 0.1:
                    raise RuntimeError(f"Page size mismatch at {index+1}")
                page.get_pixmap(matrix=pymupdf.Matrix(0.2, 0.2), alpha=False)
        os.replace(pending, destination)
    review = write_review(generation, reports)
    result = {"input": str(source), "output": str(destination), "page_count": len(reports),
              "complete_pages": sum(p["status"] == "complete" for p in reports),
              "review_pages": sum(p["status"] != "complete" for p in reports), "review": str(review), "pages": reports}
    save_json(generation / "report.json", result)
    state.update(status="complete", output_sha256=sha256(destination), result=result)
    save_json(state_path, state)
    emit("pdf_finished", input=str(source), output=str(destination), pages=len(reports), review=result["review_pages"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args()
    args.pdf_dir = args.pdf_dir.resolve()
    args.cli = args.cli.resolve()
    if not args.pdf_dir.is_dir() or not args.cli.is_file():
        parser.error("PDF directory and CLI executable must exist")
    if not 72 <= args.dpi <= 1200 or not 1 <= args.jobs <= 16:
        parser.error("DPI must be 72..1200; jobs must be 1..16")
    root = (args.output_dir or args.pdf_dir / "scantailor-output").resolve()
    if root == args.pdf_dir or args.pdf_dir.is_relative_to(root):
        parser.error("Output must not be the input directory or its ancestor")
    root.mkdir(parents=True, exist_ok=True)
    config_hash = ""
    if args.config:
        args.config = args.config.resolve()
        config = load_json(args.config)
        # The PDF wrapper owns all paths and job-lifecycle controls. Only image
        # processing options may be supplied through its config file.
        reserved = {"input", "output", "project", "save-project", "resume", "overwrite", "jobs", "dpi"}
        if reserved.intersection(config):
            parser.error("PDF config must not override paths, dpi, jobs or resume/overwrite")
        config_hash = sha256(args.config)
    candidates = args.pdf_dir.rglob("*") if args.recursive else args.pdf_dir.iterdir()
    files = sorted((p for p in candidates if p.is_file() and p.suffix.lower() == ".pdf"
                    and not p.resolve().is_relative_to(root)), key=lambda p: p.as_posix().casefold())
    if not files:
        parser.error("No input PDFs found")
    results, failures = [], []
    with directory_lock(root):
        for source in files:
            emit("pdf_started", input=str(source))
            try:
                results.append(process_pdf(source, source.relative_to(args.pdf_dir), root, args, config_hash))
            except KeyboardInterrupt:
                emit("cancelled", output_dir=str(root))
                return 130
            except Exception as error:
                failures.append({"input": str(source), "message": str(error)})
                emit("pdf_error", **failures[-1])
            save_json(root / "batch-report.json", {"schema_version": 1, "results": results, "failures": failures})
    return 1 if failures or any(r["review_pages"] for r in results) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        emit("error", message=str(exc))
        sys.exit(3)
