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
