# README illustrations

These images are generated from the production CLI layout, not desktop screenshots
and not AI mockups. Generic paths are presentation fixtures, not a recorded job.
The interface currently uses Chinese labels; both READMEs explain the controls.

- `cli-workbench.png`: `Workbench.frame`, 120 columns × 30 rows, PDF input selected,
  PNG compression level 6. Captures the input/output/settings workflow and overview.
- `cli-image-encoding.png`: `Workbench.encoding` calls the production
  `Console.paint` function; the initial PNG settings dialog is rendered and cancelled.

[`scripts/render_readme_images.py`](../../scripts/render_readme_images.py) imports
[`tests/render_workbench.py`](../../tests/render_workbench.py) to rasterize the same
cell layout used by the terminal. It needs the pinned PDF dependencies, Windows
Consolas and Microsoft YaHei fonts, and a built CLI. The state directory is a local
scratch directory and must not be an existing user's task store.

From the repository root, in PowerShell:

```powershell
python .\scripts\render_readme_images.py `
  --cli .\build-native\scantailor-cli.exe `
  --output .\docs\images `
  --state-dir .\build-native\readme-render-state
```

Refresh the illustrations when the corresponding controls or defaults change.
The native desktop capture helper failed to obtain the foreground process during
this documentation task; no unrelated desktop or user-document screenshots are
included. The supplied nine-page PDF was used for local processing validation only.
