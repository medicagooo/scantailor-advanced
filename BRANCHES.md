{
  "read": "Task state contains effective requirements; events contain operation intent.",
  "records": {
    "0910-cli": ".branch-records/0910-cli/state.json",
    "0910-cli-full": ".branch-records/0910-cli-full/state.json",
    "0911-cli-menu": ".branch-records/0911-cli-menu/state.json",
    "0911-cli-workbench": ".branch-records/0911-cli-workbench/state.json",
    "0912-image-encoding": ".branch-records\\0912-image-encoding/state.json",
    "0913-completion-ui": ".branch-records/0913-completion-ui/state.json",
    "0913-readme": ".branch-records\\0913-readme/state.json",
    "0914-task-reuse": ".branch-records/0914-task-reuse/state.json",
    "0914-cli-languages": ".branch-records\\0914-cli-languages\\state.json",
    "0914-cli-screenshots": ".branch-records/0914-cli-screenshots/state.json"
  },
  "active": [
    "0914-cli-screenshots"
  ],
  "changes": [
    {
      "status": "integrated",
      "businessChange": "Previously GUI-only processing now also supports headless image/project batches and PDF folders through a shared task chain. Physics-safe defaults retain color and disable destructive cleanup; uncertain pages preserve originals for review. Adds JSON logs, cancellation, hash-verified resume and original PDF page count/order/size validation; processed PDF pages are raster images.",
      "id": "cli-001",
      "request": "0910-cli/req-0910-01",
      "evidence": [
        "src/core/CompositeTaskFactory.cpp",
        "src/cli/BatchRunner.cpp",
        "scripts/process_pdf_folder.py",
        "docs/CLI.md",
        "docs/VERIFICATION.md"
      ],
      "date": "2026-09-10",
      "domain": "Scanning / batch document processing",
      "implementedAt": "2026-09-10T23:11:21.3448323+08:00",
      "integratedAt": "2026-09-10",
      "deployedAt": null
    },
    {
      "id": "cli-full-001",
      "date": "2026-09-10",
      "businessChange": "CLI 2 adds project and page editing, stable IDs, all six-stage settings, manual geometry/zones/curves, staged previews, coordinate conversion, selected output, layered artifact verification and split-aware PDF assembly. GUI and v1 paths are retained. Source-level rules cannot target one split half; uncertain PDF spreads preserve the original once. Local review fixes cover final preview geometry and stale aggregate sizes.",
      "status": "integrated",
      "request": "0910-cli-full/req-full-01",
      "evidence": [
        "docs/CLI-COVERAGE.md",
        "src/core/ProcessingConfiguration.cpp",
        "src/cli/ProjectSession.cpp",
        "src/cli/BatchRunner.cpp",
        "scripts/process_pdf_folder.py",
        "tests/cli_full_integration.py",
        "docs/VERIFICATION.md",
        ".branch-records/0910-cli-full/events.jsonl"
      ],
      "domain": "Scanning / project automation and PDF processing",
      "implementedAt": "2026-09-11T00:22:43.7795375+08:00",
      "integratedAt": "2026-09-11",
      "deployedAt": null
    },
    {
      "domain": "Scanning / interactive CLI",
      "date": "2026-09-11",
      "implementedAt": "2026-09-11T01:04:41.9034643+08:00",
      "status": "integrated",
      "evidence": [
        "docs/MENU.md",
        "tests/menu_integration.py",
        "scripts/scantailor_menu/model.py",
        "scripts/scantailor_menu/console.py",
        "scripts/scantailor_menu/ui.py",
        "src/cli/MenuLauncher.cpp",
        "docs/VERIFICATION.md"
      ],
      "integratedAt": "2026-09-11T01:07:08.5300391+08:00",
      "deployedAt": null,
      "request": "0911-cli-menu/req-menu-execute",
      "id": "cli-menu-001",
      "businessChange": "CLI 3 adds a keyboard/mouse console menu for exact PDF/image selections, output browsing, typed schema-2 settings and per-page rules, project/page edits, six-stage PDF/image previews, GUI geometry editing, review and immutable-snapshot recovery. Input changes clear old scopes; running tasks lock edits; cancellation waits for workers. Structural edits retain applied settings and rebase project paths. Existing command interfaces remain available."
    },
    {
      "implementedAt": "2026-09-11T02:32:42.4770047+08:00",
      "domain": "Scanning / interactive CLI",
      "businessChange": "CLI 3.1 replaces the long menu with a responsive Chinese task workbench, native clipboard/selection/path editing, guided input/output, common and advanced settings, first/middle/last logical-page preview, local image comparison and readable stage progress. Text paste never launches actions. Mode/margin/preset changes clear conflicting settings. Existing CLI/project/recovery workflows retained.",
      "deployedAt": null,
      "id": "cli-workbench-001",
      "request": "0911-cli-workbench/req-execute",
      "status": "integrated_local",
      "evidence": [
        "docs/MENU.md",
        "docs/VERIFICATION.md",
        "tests/workbench_integration.py",
        "scripts/scantailor_menu/workbench.py",
        "scripts/scantailor_menu/console.py",
        "src/cli/BatchRunner.cpp"
      ],
      "integratedAt": "2026-09-11T02:33:31.9180568+08:00",
      "date": "2026-09-11"
    },
    {
      "domain": "CLI/PDF image encoding",
      "business_change": "CLI/PDF rendered and processed page images now default to PNG level 6 instead of fixed render PNG plus processed TIFF. PNG 0-9, TIFF none/LZW/Deflate and JPEG quality 1-100 are configurable and saved in presets/snapshots. Encoding changes invalidate resume caches while retaining ownership across format changes. PNG lossless preserve fallback, original PDF fallback and GUI TIFF caches remain; JPEG rejects selected transparent layer output. Schema 1/2 overrides supported.",
      "date": "2026-09-12",
      "status": "integrated",
      "id": "image-encoding",
      "request": "0912-image-encoding/req-execute",
      "evidence": [
        "src/core/ImageEncoding.cpp",
        "src/cli/BatchRunner.cpp",
        "scripts/image_encoding.py",
        "scripts/process_pdf_folder.py",
        "scripts/scantailor_menu/workbench.py",
        "docs/VERIFICATION.md"
      ],
      "implementedAt": "2026-09-12T14:26:22+08:00",
      "integratedAt": "2026-09-13T23:11:09.6072948+08:00"
    },
    {
      "evidence": [
        "scripts/scantailor_menu/model.py",
        "scripts/scantailor_menu/ui.py",
        "tests/completion_ui_integration.py",
        "docs/VERIFICATION.md"
      ],
      "request": "0913-completion-ui/req-bug",
      "domain": "CLI workbench lifecycle",
      "date": "2026-09-13",
      "id": "completion-ui",
      "business_change": "Completed tasks previously stayed on execution page while elapsed timer continued. CLI 3.2.1 freezes/persists duration and automatically opens result actions after worker/preview/checkpoint finalization. Complete, review, failed and cancelled states transition; cancelling still waits for actual exit. Old task records and existing preview outputs remain usable.",
      "status": "integrated_local",
      "implementedAt": "2026-09-13T23:38:08.985529+08:00",
      "integratedAt": "2026-09-14T01:24:43.599271+08:00"
    },
    {
      "domain": "CLI / task lifecycle",
      "id": "task-reuse-001",
      "request": "0914-task-reuse/req-plan",
      "businessChange": "CLI 3.3 persists applied reusable defaults and separates render/input/output DPI. New PDF jobs place final PDFs at output root and auxiliary files under _scantailor; legacy layouts stay readable. Workbench confirms duplicate/partial/overwrite actions, resumes original snapshots, and verifies shared render/stage caches. Quick preview processes only selected source pages (default first/middle/last); exact full-project mode remains for layout and page rules. Supersedes cli-workbench-001 quick-preview behavior.",
      "implementedAt": "2026-09-14T01:22:14.283792+08:00",
      "deployedAt": null,
      "evidence": [
        ".branch-records\\0914-task-reuse\\state.json",
        ".branch-records\\0914-task-reuse\\verification.md",
        "docs/VERIFICATION.md",
        "tests/task_reuse_integration.py"
      ],
      "status": "integrated_local",
      "date": "2026-09-14",
      "integratedAt": "2026-09-14T01:24:43.599271+08:00"
    },
    {
      "id": "cli-languages-001",
      "date": "2026-09-14",
      "domain": "CLI / localization",
      "businessChange": "CLI 3.4 adds English and Traditional Chinese alongside Simplified Chinese. Defaults to Windows user UI languages, falls back to English; All settings saves an immediate manual selection. Launch-only --language overrides do not change saved preferences. Language changes preserve processing configuration, task identity and cached results; preview controls switch locally. Three linked READMEs use locale-specific production-layout illustrations.",
      "status": "integrated_local",
      "request": "0914-cli-languages/req-implement",
      "evidence": [
        "docs/VERIFICATION.md",
        ".branch-records/0914-cli-languages/verification.md",
        "tests/language_integration.py",
        "tests/language_viewer_integration.js"
      ],
      "implementedAt": "2026-09-14T01:56:13.676561+08:00",
      "integratedAt": "2026-09-14T01:57:41.233301+08:00",
      "deployedAt": null
    }
  ],
  "format": 1,
  "pending": [
    "0914-cli-screenshots/op-merge"
  ]
}
