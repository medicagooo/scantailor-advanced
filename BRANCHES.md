{
  "read": "Task state contains effective requirements; events contain operation intent.",
  "records": {
    "0910-cli": ".branch-records/0910-cli/state.json",
    "0910-cli-full": ".branch-records/0910-cli-full/state.json"
  },
  "active": [],
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
      "status": "implemented_local_unmerged",
      "request": "0910-cli-full/req-full-01",
      "evidence": [
        "docs/CLI-COVERAGE.md",
        "src/core/ProcessingConfiguration.cpp",
        "src/cli/ProjectSession.cpp",
        "src/cli/BatchRunner.cpp",
        "scripts/process_pdf_folder.py",
        "tests/cli_full_integration.py",
        "docs/VERIFICATION.md"
      ],
      "domain": "Scanning / project automation and PDF processing",
      "implementedAt": "2026-09-11T00:22:43.7795375+08:00",
      "integratedAt": null,
      "deployedAt": null
    }
  ],
  "format": 1,
  "pending": [
    "0910-cli-full/op-master-ff",
    "0910-cli-full/op-push-master"
  ]
}
