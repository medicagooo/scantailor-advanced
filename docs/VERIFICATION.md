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
CLI 2 was subsequently pushed to origin/master at 02631a73be1dead864ac2961ed5a609c9b100b02 on 2026-09-11 under an explicit request.
Old GUIs may discard new optional metadata on resave; use this package's
GUI for stable IDs, custom spline tensions and frozen dimensions.

## CLI 3 menu validation — 2026-09-11

Windows native Qt 6.8.3 / MinGW 13.1 offline build passed, including 5 CTest groups.
All 20 complete CLI workflow tests passed, retaining v1 command contracts and the actual GUI roundtrip harness.
Eight menu tests passed: schema bounds and source scope; draft copies and source invalidation; process/resume/preview snapshots;
exact PDF selections with colliding names; preservation of settings through structural edits; GUI project path rebasing;
cancellation/completion synchronization; console sanitization and real Win32 input records.

The hidden classic-console test injects actual keyboard and mouse INPUT_RECORD values, validates numeric text input,
release-event draining and console mode restoration, and launches/exits the native `menu` command.
This is automated Win32 console evidence, not a manual Windows Terminal interaction test.

Independent review via a generic review subagent (dedicated Bugbot service unavailable) found four P2 issues:
GUI relative paths, applied configuration loss on page edits, dropped release events and cancellation status races.
All four were repaired and covered by the menu regressions. No further review invocation was required.

Reproducible evidence: `tests/menu_integration.py`, `docs/MENU.md`, and the build/package scripts.
Local logs: `build-native/menu-build.log`, `menu-tests.log`, `menu-full-tests.log`.

Portable validation uses the packaged menu modules and embedded Python with only Windows system directories in PATH.
All 8 menu tests passed, including real Ctrl+Break cancellation and completion; 19 CLI/PDF workflow tests passed
(the non-distributed GUI harness is intentionally skipped there; its test passed in the native 20-test run).
Evidence: `build-native/menu-package-tests.log`, `menu-package-full.log`, `menu-package.log`.
The first embedded-Python full-suite invocation needed the tests directory explicitly added to sys.path because
the isolated embedded runtime omits it; the corrected invocation passed. This did not require changing application code.

Artifacts: `bin/ScanTailor-CLI-3.0-win64/` and `bin/ScanTailor-CLI-3.0-win64.zip`.
CLI 1 and CLI 2 packages remain in place. The CLI 3 package includes MENU.md and its exact file manifest.

## CLI 3.1 workbench redesign — 2026-09-11

The long action list is replaced by a guided Chinese workbench with responsive layout, native clipboard text editing, common/advanced settings, sampled preview and readable progress. The native build and five CTest groups passed. All 20 full workflow regressions passed. Workbench tests cover editing/selection, quoted Unicode/multiline paths, recursive collection and output suggestions, enabled actions/hitboxes at 120/80/60 columns, review fixes, whole-project sampling, and keyboard paste-to-process execution. Existing eight menu tests remain applicable.

Actual hidden classic-console and Windows Terminal runs read the native clipboard without modifying it and verified Ctrl+V routing. Known Chinese/multiline fixtures use an injected clipboard provider for deterministic Ctrl+V/Shift+Insert/right-click tests; terminal-injected text is tested separately. Both hosts verified visible workbench text through ReadConsoleOutputCharacterW. Evidence: `build-native/workbench-terminal-final.json`, `workbench-tests.log`, `workbench-menu-regression.log`. Visual layouts at 120x34, 80x25 and 60x22 were rendered and inspected under `build-native/workbench-visuals/`.

An independent generic review agent (dedicated Bugbot unavailable) found three P2 issues: conflicting manual angle after mode switch, automatic margins overriding explicit margins, and preserve preset retaining report policy. All were fixed and covered by `test_common_mode_margins_and_scheme_review_fixes`.

Real textbook sample preview: `build-native/workbench-real-preview/result.json`, complete; source SHA-256 unchanged at 1086c47c4e7cc13659b5545aaac0f933036f7c0dbb7653fd1721ebd7eea1841f. The local comparison HTML was generated. Automated browser navigation to its file URL was rejected by browser security policy; no browser workaround was used. HTML structure/data tests are separate from browser interaction, which is not claimed as verified.

Final CLI 3.1 portable validation: 9 workbench tests, 8 menu regressions and 19 CLI/PDF workflow tests passed using packaged modules and embedded Python with only Windows system paths. GUI harness is not distributed and remains covered by the native 20-test run. Logs: `workbench-package-tests.log`, `workbench-package-menu.log`, `workbench-package-full.log`. Artifact: `bin/ScanTailor-CLI-3.1-win64/` and sibling ZIP; earlier packages are preserved. A temporary clipboard access-denied condition during browser automation cleared after that browser session ended; native clipboard tests then passed. Clipboard retry is bounded and never writes clipboard data.
