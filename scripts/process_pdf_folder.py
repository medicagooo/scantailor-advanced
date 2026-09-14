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
import signal
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Embedded Python uses an isolated search path; include this packaged sibling.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pymupdf
from PIL import Image
import image_encoding

VERSION = 5


def request_cancel(signum, frame):
    raise KeyboardInterrupt


if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, request_cancel)


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
    """Exclusive output ownership; OS releases the lock after interruption/crash.

    Windows retains its byte-range lock; POSIX uses advisory flock on the same
    persistent lock file. Never unlink the file: waiters must share one inode.
    """
    if os.name == "nt":
        import msvcrt
    else:
        import fcntl
    with (folder / ".pdf-batch.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError(f"Another PDF job owns {folder}") from error
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def run_cli(command: list[str], log: Path) -> int:
    # Inherit the console so Ctrl+C reaches the CLI's cancellation handler.
    # stdout goes to JSONL on disk, avoiding pipe buffering deadlocks.
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, encoding="utf-8", errors="replace")
        try:
            # Stream native progress to the workbench while retaining JSONL.
            with process.stdout:
                for line in process.stdout:
                    stream.write(line)
                    stream.flush()
                    print(line, end="", flush=True)
            return process.wait()
        except KeyboardInterrupt:
            # Allow the native process to checkpoint after the console event.
            # Ctrl+Break reaches both this wrapper and the native worker in
            # the same console process group. Do not kill a checkpoint write.
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


def metadata_root(root):
    # Read legacy outputs in place; new runs keep auxiliary files one level down.
    return root if (root / '.work').exists() or (root / 'batch-report.json').exists() else root / '_scantailor'


def sample_indexes(expression, count):
    if expression == 'sample': return sorted({0, count // 2, count - 1})
    indexes = sorted({int(part.strip()) - 1 for part in expression.split(',')})
    if not indexes or indexes[0] < 0 or indexes[-1] >= count:
        raise ValueError('Source pages must be within the document')
    return indexes


def process_pdf(source: Path, relative: Path, root: Path, args, config_hash: str) -> dict:
    # Include the relative pathname to distinguish equal stems in subdirectories.
    book_id = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:12]
    meta = metadata_root(root)
    suffix = '' if relative.parent == Path('.') else '-' + book_id
    destination = root / f"{source.stem}{suffix}.deskew.pdf"
    if meta == root: destination = root / relative.parent / f"{source.stem}.deskew.pdf"
    work = meta / '.work' / book_id
    work.mkdir(parents=True, exist_ok=True)
    state_path = work / "state.json"
    previous = load_json(state_path)
    signature = {"version": VERSION, "source": str(source), "source_sha256": sha256(source),
                 "cli_sha256": sha256(args.cli), "dpi": args.dpi, "page_size": args.page_size, "config_sha256": config_hash,
                 "wrapper_sha256": sha256(Path(__file__)), "encoding_sha256": sha256(Path(image_encoding.__file__)), "pymupdf_version": pymupdf.VersionBind,
                 "command": args.command, "stage": args.stage, "sample": args.sample, "source_pages": args.source_pages, "review_policy": args.review_policy,
                 "max_angle": args.max_angle, "min_page_ratio": args.min_page_ratio,
                 "image_encoding": args.image_encoding}
    fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    if args.command == "process" and destination.exists() and not (args.overwrite or (args.resume and previous.get("destination") == str(destination))):
        raise RuntimeError(f"Output exists: {destination}; use --resume or --overwrite")
    if (args.command == "process" and args.resume and previous.get("fingerprint") == fingerprint and previous.get("status") == "complete"
            and not previous.get("result", {}).get("errors")
            and destination.exists() and previous.get("output_sha256") == sha256(destination)):
        emit("pdf_reused", input=str(source), output=str(destination))
        return previous["result"]
    # Changed inputs/config get a new generation. Old intermediates remain
    # available for recovery; never sweep or delete unknown files.
    generation = work / fingerprint[:16]
    # Rendering depends on source pixels, DPI and encoder, not analysis stage or
    # output settings. Shared cache survives preview/process/config changes.
    render_signature = {k: signature[k] for k in ('source_sha256','dpi','pymupdf_version','encoding_sha256')}
    render_signature['encoding'] = args.image_encoding
    render_id = hashlib.sha256(json.dumps(render_signature, sort_keys=True).encode()).hexdigest()
    render_root = (args.cache_dir or meta / 'cache') / render_id
    images = render_root / "input"
    processed = generation / "processed"
    images.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    render_state_path = render_root / "render-state.json"
    render_state = load_json(render_state_path)
    rendered = render_state.get("pages", {})
    state = {"schema_version": 1, "fingerprint": fingerprint, "signature": signature,
             "destination": str(destination), "status": "active"}
    save_json(state_path, state)
    extension = image_encoding.suffix(args.image_encoding)
    with pymupdf.open(source) as original:
        if original.needs_pass:
            raise RuntimeError("Encrypted PDF requires a decrypted input copy")
        if original.page_count == 0:
            raise RuntimeError("PDF has no pages")
        dimensions = []
        selected_sources = sample_indexes(args.source_pages or 'sample', original.page_count) if args.sample else list(range(original.page_count))
        if args.sample:
            configured = load_json(args.config) if args.config else {}
            if configured.get('rules'): raise ValueError('快速抽样不支持按页规则，请使用精确预览')
            emit('source_sample', selected_sources=[i + 1 for i in selected_sources], total_sources=original.page_count)
        for ordinal, index in enumerate(selected_sources):
            page = original[index]
            image_path = images / f"{index+1:05d}{extension}"
            dimensions.append((page.rect.width, page.rect.height))
            old = rendered.get(str(index), {})
            reused = image_path.exists() and old.get("sha256") == sha256(image_path)
            if not reused:
                pix = page.get_pixmap(dpi=args.dpi, colorspace=pymupdf.csRGB, alpha=False)
                temp = image_path.with_suffix(".tmp" + extension)
                # Encode the rendered RGB page once, with explicit DPI and codec.
                with Image.frombytes("RGB", (pix.width, pix.height), pix.samples) as image:
                    image_encoding.save(image, temp, args.image_encoding, args.dpi)
                os.replace(temp, image_path)
                rendered[str(index)] = {"sha256": sha256(image_path)}
                save_json(render_state_path, {"pages": rendered})
            emit("page_render_reused" if reused else "page_rendered", input=str(source), page=ordinal+1, source_page=index+1, total=len(selected_sources))
        # Stable image identities derive from the source PDF and source page,
        # not the generation folder (which changes when configuration changes).
        manifest = generation / "inputs.json"
        source_hash = sha256(source)
        save_json(manifest, {"schema_version": 1, "files": [
            {"path": str(images / f"{i+1:05d}{extension}"),
             "stable_id": hashlib.sha256(f"{source_hash}:{i+1}".encode()).hexdigest()}
            for i in selected_sources]})
        command = [str(args.cli), args.command, "--manifest", str(manifest), "--output", str(processed),
                   "--analysis-cache", str((args.cache_dir or meta / "cache").parent / "analysis-cache"),
                   "--jobs", str(args.jobs), *image_encoding.arguments(args.image_encoding)]
        for key in ("review_policy", "max_angle", "min_page_ratio"):
            if getattr(args, key) is not None:
                command += ["--" + key.replace("_", "-"), str(getattr(args, key))]
        if args.command != "process":
            command += ["--stage" if args.command == "preview" else "--through", args.stage, "--html"]
        if args.sample:
            command += ["--pages", "all"]
        if args.config:
            command += ["--config", str(args.config)]
        if (processed / "state.json").exists():
            command += ["--overwrite"] if args.overwrite else ["--resume"]
        code = run_cli(command, generation / "events.jsonl")
        if code == 130:
            raise KeyboardInterrupt
        if code not in (0, 1):
            raise RuntimeError(f"CLI failed with code {code}; see {generation / 'events.jsonl'}")
        if args.command != "process":
            native_report = load_json(processed / "report.json")
            return {"errors": native_report.get("errors", 0), "input": str(source), "output": str(processed), "review_pages": int(code == 1),
                    "project": str(processed / "project.scan"), "command": args.command}
        native = load_json(processed / "report.json")
        if native.get("schema_version") not in (1, 2):
            raise RuntimeError("Missing or incompatible CLI report")
        by_input = {}
        for record in native["pages"]:
            key = str(Path(record["input"]).resolve()).casefold()
            by_input.setdefault(key, []).append(record)
        reports = []
        output_dimensions = []
        source_to_output = {}
        result_pdf = pymupdf.open()
        try:
            for index, (width, height) in enumerate(dimensions):
                image_path = images / f"{index+1:05d}{extension}"
                records = by_input.get(str(image_path.resolve()).casefold(), [])
                source_to_output[index+1] = result_pdf.page_count + 1
                sides = [r.get("subpage", "single") for r in records]
                valid_structure = (len(records) == 1 and sides == ["single"]) or (
                    len(records) == 2 and set(sides) == {"left", "right"})
                # A source spread is the recovery unit. Never duplicate its
                # whole original for both failed halves or silently lose one.
                if not valid_structure or any(r.get("status") != "complete" for r in records):
                    result_pdf.insert_pdf(original, from_page=index, to_page=index)
                    output_dimensions.append((width, height))
                    reports.append({"page": result_pdf.page_count, "source_page": index+1,
                        "status": "review", "rendered_input": str(image_path), "output_image": None,
                        "fallback_original_pdf": True, "metrics": {}, "warnings": ["source_page_preserved"],
                        "message": "One or more logical pages require review; preserved the source PDF page once.",
                        "logical_pages": records})
                    continue
                for record in records:
                    image_out = Path(record.get("output", ""))
                    if not image_out.is_file() or record.get("sha256") != sha256(image_out):
                        raise RuntimeError(f"Unverified output for page {index+1}")
                    with Image.open(image_out) as image:
                        buffer = io.BytesIO()
                        image.convert("RGB").save(buffer, format="PNG")
                        if args.page_size == "processed":
                            output_dpi = record.get("settings", {}).get("output", {}).get("dpi", [args.dpi, args.dpi])
                            target_width, target_height = image.width * 72 / output_dpi[0], image.height * 72 / output_dpi[1]
                        elif len(records) == 2:
                            rotation = record.get("settings", {}).get("orientation", {}).get("rotation", 0)
                            rotated_width, rotated_height = (height, width) if rotation % 180 else (width, height)
                            target_width, target_height = rotated_width / 2, rotated_height
                        else:
                            target_width, target_height = width, height
                    target = result_pdf.new_page(width=target_width, height=target_height)
                    target.insert_image(target.rect, stream=buffer.getvalue(), keep_proportion=True)
                    output_dimensions.append((target_width, target_height))
                    reports.append({"page": result_pdf.page_count, "source_page": index+1,
                        "logical_id": record.get("id"), "subpage": record.get("subpage", "single"), "status": "complete",
                        "rendered_input": str(image_path), "output_image": str(image_out),
                        "fallback_original_pdf": False, "metrics": record.get("metrics", {}),
                        "warnings": record.get("warnings", []), "message": record.get("message", "")})
            # Keep document-level navigation and descriptive metadata when possible.
            result_pdf.set_metadata(original.metadata)
            toc = original.get_toc()
            if toc:
                result_pdf.set_toc([[level, title, source_to_output.get(page, page)] for level, title, page in toc])
            destination.parent.mkdir(parents=True, exist_ok=True)
            pending = generation / "pending.pdf"
            result_pdf.save(pending, garbage=3, deflate=True)
        finally:
            result_pdf.close()
        with pymupdf.open(pending) as check:
            if check.page_count != len(output_dimensions):
                raise RuntimeError("Output page count mismatch")
            for index, page in enumerate(check):
                expected = output_dimensions[index]
                if abs(page.rect.width - expected[0]) > 0.1 or abs(page.rect.height - expected[1]) > 0.1:
                    raise RuntimeError(f"Page size mismatch at {index+1}")
                page.get_pixmap(matrix=pymupdf.Matrix(0.2, 0.2), alpha=False)
        os.replace(pending, destination)
    review = write_review(generation, reports)
    result = {"errors": native.get("errors", 0), "input": str(source), "output": str(destination), "page_count": len(reports),
              "complete_pages": sum(p["status"] == "complete" for p in reports),
              "review_pages": sum(p["status"] != "complete" for p in reports), "review": str(review), "pages": reports,
              "source_to_output": source_to_output}
    save_json(generation / "report.json", result)
    state.update(status="complete", output_sha256=sha256(destination), result=result)
    save_json(state_path, state)
    emit("pdf_finished", input=str(source), output=str(destination), pages=len(reports), review=result["review_pages"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--pdf-dir", type=Path)
    inputs.add_argument("--pdf-manifest", type=Path, help="schema_version=1, files: ordered PDF paths")
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--image-format", choices=("png", "tiff", "jpeg"))
    parser.add_argument("--png-compression", type=int)
    parser.add_argument("--tiff-compression", choices=("none", "lzw", "deflate"))
    parser.add_argument("--jpeg-quality", type=int)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--page-size", choices=("original", "processed"), default="original")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--command", choices=("process", "analyze", "preview"), default="process")
    parser.add_argument("--stage", choices=("orientation", "split", "deskew", "content", "layout", "output"), default="output")
    parser.add_argument("--review-policy", choices=("preserve", "report"))
    parser.add_argument("--max-angle", type=float)
    parser.add_argument("--min-page-ratio", type=float)
    parser.add_argument("--sample", action="store_true", help="Render only first/middle/last source pages for quick preview")
    parser.add_argument("--source-pages", help="Quick preview source pages: sample or comma-separated 1-based numbers")
    parser.add_argument("--cache-dir", type=Path, help="Shared PDF render cache; exclusively owned by this batch")
    args = parser.parse_args()
    if args.source_pages and not args.sample: parser.error("--source-pages requires --sample")
    if args.sample and args.command != "preview":
        parser.error("--sample only applies to preview")
    args.cli = args.cli.resolve()
    if not args.cli.is_file(): parser.error("CLI executable must exist")
    explicit_files = None
    if args.pdf_dir:
        args.pdf_dir = args.pdf_dir.resolve()
        if not args.pdf_dir.is_dir(): parser.error("PDF directory must exist")
    else:
        manifest_path = args.pdf_manifest.resolve()
        manifest = load_json(manifest_path)
        if set(manifest) != {"schema_version", "files"} or manifest["schema_version"] != 1 or not isinstance(manifest["files"], list) or not manifest["files"]:
            parser.error("PDF manifest requires schema_version=1 and a nonempty files array")
        explicit_files = []
        for value in manifest["files"]:
            if not isinstance(value, str) or not value: parser.error("Manifest paths must be nonempty strings")
            path = (manifest_path.parent / value).resolve()
            if not path.is_file() or path.suffix.lower() != ".pdf": parser.error(f"Not a readable PDF path: {path}")
            if path in explicit_files: parser.error(f"Duplicate PDF path: {path}")
            explicit_files.append(path)
    if not 72 <= args.dpi <= 1200 or not 1 <= args.jobs <= 16:
        parser.error("DPI must be 72..1200; jobs must be 1..16")
    if ((args.max_angle is not None and not 0 <= args.max_angle <= 45)
            or (args.min_page_ratio is not None and not .1 <= args.min_page_ratio <= 1)):
        parser.error("Review thresholds must be 0..45 degrees and 0.1..1 area ratio")
    default_parent = args.pdf_dir if args.pdf_dir else explicit_files[0].parent
    root = (args.output_dir or default_parent / "scantailor-output").resolve()
    if args.pdf_dir and (root == args.pdf_dir or args.pdf_dir.is_relative_to(root)):
        parser.error("Output must not be the input directory or its ancestor")
    if explicit_files and any(p.is_relative_to(root) for p in explicit_files):
        parser.error("Output must not contain an input PDF")
    root.mkdir(parents=True, exist_ok=True)
    config_hash = ""
    config = {}
    if args.config:
        args.config = args.config.resolve()
        config = load_json(args.config)
        # The PDF wrapper owns all paths and job-lifecycle controls. Only image
        # processing options may be supplied through its config file.
        reserved = {"input", "output", "project", "save-project", "resume", "overwrite", "jobs", "dpi", "manifest", "save", "operations", "through", "stage", "pages"}
        if reserved.intersection(config):
            parser.error("PDF config must not override paths, dpi, jobs or resume/overwrite")
        config_hash = sha256(args.config)
    try:
        configured = config.get('image_encoding', {}) if config.get('schema_version') == 2 else {
            k: config[flag] for k, flag in (('format', 'image-format'), ('png_compression', 'png-compression'),
                                           ('tiff_compression', 'tiff-compression'), ('jpeg_quality', 'jpeg-quality')) if flag in config}
        image_encoding.resolve(configured)  # Reject invalid saved policies before overlaying flags.
        args.image_encoding = image_encoding.resolve(configured, {
            'format': args.image_format, 'png_compression': args.png_compression,
            'tiff_compression': args.tiff_compression, 'jpeg_quality': args.jpeg_quality})
    except (ValueError, TypeError) as error:
        parser.error(str(error))
    if explicit_files is not None:
        if args.recursive: parser.error("--recursive only applies to --pdf-dir")
        files = explicit_files
    else:
        candidates = args.pdf_dir.rglob("*") if args.recursive else args.pdf_dir.iterdir()
        files = sorted((p for p in candidates if p.is_file() and p.suffix.lower() == ".pdf"
                        and not p.resolve().is_relative_to(root)), key=lambda p: p.as_posix().casefold())
    if not files:
        parser.error("No input PDFs found")
    results, failures = [], []
    meta = metadata_root(root)
    meta.mkdir(parents=True, exist_ok=True)
    if args.cache_dir:
        args.cache_dir = args.cache_dir.resolve()
        args.cache_dir.mkdir(parents=True, exist_ok=True)
    # One shared-cache lock serializes preview/process writers using the same root.
    from contextlib import ExitStack
    with ExitStack() as locks:
        locks.enter_context(directory_lock(meta))
        if args.cache_dir and args.cache_dir != meta:
            locks.enter_context(directory_lock(args.cache_dir))
        for source in files:
            emit("pdf_started", input=str(source))
            try:
                # Explicit selections have stable per-source subdirectories, so
                # equal file names and changing selections cannot collide.
                relative = source.relative_to(args.pdf_dir) if args.pdf_dir else Path(hashlib.sha256(str(source).casefold().encode()).hexdigest()[:12]) / source.name
                results.append(process_pdf(source, relative, root, args, config_hash))
            except KeyboardInterrupt:
                emit("cancelled", output_dir=str(root))
                return 130
            except Exception as error:
                failures.append({"input": str(source), "message": str(error)})
                emit("pdf_error", **failures[-1])
            save_json(meta / "batch-report.json", {"schema_version": 1, "results": results, "failures": failures})
    return 1 if failures or any(r["review_pages"] for r in results) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        emit("error", message=str(exc))
        sys.exit(3)
