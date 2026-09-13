{
  "read": "Task state contains effective requirements; events contain operation intent.",
  "records": {
    "0910-cli": ".branch-records/0910-cli/state.json",
    "0910-cli-full": ".branch-records/0910-cli-full/state.json",
    "0911-cli-menu": ".branch-records/0911-cli-menu/state.json",
    "0911-cli-workbench": ".branch-records/0911-cli-workbench/state.json",
    "0912-image-encoding": ".branch-records\\0912-image-encoding/state.json"
  },
  "active": [
    "0912-image-encoding"
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
      "status": "implemented_unmerged",
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
      "implementedAt": "2026-09-12T14:26:22+08:00"
    }
  ],
  "format": 1,
  "pending": [
    "0912-image-encoding/op-merge"
  ]
}
