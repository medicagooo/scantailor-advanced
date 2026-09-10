# Local verification — 2026-09-10, Asia/Singapore

Repository: `D:/proj/scantailor-advanced`; fork: medicagooo/scantailor-advanced.
Base: `master@5eaac1884cdcabb6514bd632114f688631bd8dbc`.
Task branch: `0910-cli`. This repository uses `master`, not `main`.
The implementation is local and unmerged; no push or release publication was authorized.

## Results

- Offline Windows Release build: GUI and CLI succeeded with Qt 6.8.3,
  Qt MinGW 13.1.0, Boost 1.85.0 and Strawberry C image libraries; native CPU
  optimization disabled. `scripts/Build-Windows.ps1 -WithTests` passed.
- Original CTest suites: 5/5 passed. Windows path and indexed-color reference
  assumptions in two existing tests were corrected; production image algorithms
  were not changed for those fixes.
- Final packaged CLI: 7/7 `tests/cli_integration.py` tests passed. Coverage includes
  pixel identity with deskew disabled, saved project replay, known skew, blank
  fallback, invalid arguments, corrupt input, overwrite protection, resume,
  output tampering, changed source content, PDF order/size/TOC, cancellation.
- Packaged PowerShell entry and bundled Python processed pages 6, 152 and 301
  extracted from `物理1.pdf` at 200 DPI with a system-only PATH: 3 completed,
  0 review, 0 failures. Angles: +0.375°, -0.5°, +0.25°. Wrapper validated page
  count, order association, original page dimensions and renderability.
- Three-page before/after contact sheet visually inspected: no obvious content
  clipping. This is limited visual sampling, not proof of formula-level accuracy
  across the nine source books. Source PDFs were not modified.
- Packaged GUI remained running during a 3-second offscreen startup smoke check;
  this does not constitute manual GUI interaction or pixel-equivalence QA.
- Package DLL dependency scan and system-only PATH doctor succeeded; JSON registry
  references and Git whitespace checks passed before commit.

Local build evidence (ignored, not committed): `build-native/final-build.log`,
`integration-final.log`, `package-final.log`, `real-pdf.log`, `gui-smoke.log`, and
`real-sample/comparison.jpg`. Automated tests are committed and reproducible.

## Artifacts and limitations

`bin/ScanTailor-CLI-win64` contains GUI, CLI, required DLLs, Python 3.12.10,
PyMuPDF 1.28.2, Pillow 12.3.0, the PDF wrapper, usage guide and SHA-256 manifest.
The sibling ZIP is the local delivery archive. Both are ignored build outputs.

Normal PDF pages are rasterized; no OCR or cloud calls. Original text layers and
interactive PDF objects are not preserved on processed pages. Heuristic confidence
checks reduce risk but cannot guarantee every character or diagram is unchanged.
Uncertain pages retain their original PDF page and receive a review entry.
Intermediates remain on disk for recovery. Severe memory failures may stop without
an additional report; the previous checkpoint remains usable with `-Resume`.
No full nine-book processing, external publication, deployment or push was performed.

Next use: run `bin/ScanTailor-CLI-win64/Process-PdfFolder.ps1` with `-PdfDir` and
`-ScanTailorDir`, then inspect `batch-report.json` and each generated review page.

# CLI 2 verification — 2026-09-11, Asia/Singapore

This section is the current task result. The preceding CLI 1 section is a historical
pre-publication snapshot; that earlier implementation subsequently reached
`origin/master@f9bf198e2797863c31408b2c1f84acac8c4fdd0d` on 2026-09-10.
CLI 2 is based on that commit, on local branch `0910-cli-full`. No new push,
merge, release or cloud operation is authorized or performed for this task.

## Verified results

- Offline Windows Release build of GUI, CLI and the GUI roundtrip harness passed
  via `scripts/Build-Windows.ps1 -WithTests`. Same Qt 6.8.3 / MinGW 13.1 /
  Boost 1.85.0 / C image library combination as above. CLI doctor reports 2.0.0.
- Existing CTest suites: **5/5 passed**.
- Expanded `tests/cli_full_integration.py`: **20/20 passed**, including all seven
  inherited v1 contracts. No skips in the native build run. Covers all output
  scalar settings, 10 actual binarizers, project edit operations, stable IDs,
  multipage TIFF/anisotropic and repaired DPI, frozen size, zones/curves,
  manual/auto/marginal dewarp with output layers, coordinate roundtrip,
  stale manual geometry rejection, presets and protected destinations,
  final split/layout previews and stale aggregate cleanup, PDF split/TOC/
  stable IDs/source-spread fallback/processed dimensions, resume and cancellation.
- Actual GUI open/edit/save: test target compiles original MainWindow sources,
  opens a CLI project, invokes its reading-order and save slots, and verifies
  all stable IDs and per-page settings survive. Frozen dimensions survive too.
  This is stronger than a startup check, but not manual visual GUI testing.
- Portable runtime: 19 CLI/PDF tests passed with only Windows system directories
  in PATH. The GUI harness case is intentionally skipped in that pass because it
  is not distributed. It then passed separately against the packaged CLI with
  package + Windows directories in PATH, giving coverage of all 20 cases.
- Package PE dependency scan, bundled Python/PyMuPDF/Pillow import check and
  system-only PATH doctor passed. The package includes GUI and CLI executables,
  runtime DLLs, Python 3.12.10, PyMuPDF 1.28.2, Pillow 12.3.0, wrapper and guides.
- Packaged PowerShell wrapper with bundled Python processed the same source
  sample (物理1.pdf pages 6, 152 and 301) at 200 DPI: **3 complete, 0 review,
  0 failures**. It independently verified PDF count, association, dimensions
  and renderability. Before/after contact sheet visually checked: no obvious
  clipping of page furniture, formulas or figures in this limited sample.
- Independent review agent reported **2 P2 findings**, both fixed and covered by
  `test_review_fixes_split_aggregate_and_final_previews`. Dedicated Bugbot tool
  was unavailable; this was an independent generic code review, not a Bugbot
  service result. Details and other debugger/regression repairs are recorded in
  `docs/CLI-COVERAGE.md`.

## Evidence and delivery

Committed, reproducible evidence: `tests/cli_full_integration.py`,
`tests/gui_project_roundtrip.cpp`, `docs/CLI-COVERAGE.md` and build/package scripts.
Local ignored evidence: `build-native/full-final-build.log`, `full-tests.log`,
`full-package.log`, `full-package-tests.log`, `full-package-gui-test.log`,
`full-real-pdf.log`, `full-real-pdf/batch-report.json`,
`full-real-comparison.jpg`, and `full-source-hashes.json`.

Artifacts: `bin/ScanTailor-CLI-2.0-win64/` and its sibling ZIP (local delivery).
The original CLI 1 package remains in place. `manifest.json` records file hashes;
source provenance identifies the base, task branch and staged source tree.
No full nine-book batch or external publication has been performed. The original
PDF files are preserved. As before, image processing/PDF rasterization is not
character-level proof of fidelity; inspect review reports and difficult pages.

## Continuing from this result

Implementation and local validation are complete. Use the new portable package's
`Process-PdfFolder.ps1`, or the project/config/geometry commands in `docs/CLI.md`.
Any later integration/push requires its own explicit request and predeclared Git
operation. Old GUIs may discard new optional metadata on resave; use this package's
GUI for stable IDs, custom spline tensions and frozen dimensions.
