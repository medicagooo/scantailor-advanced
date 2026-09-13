# Multilingual CLI illustrations

The `en/`, `zh-Hans/` and `zh-Hant/` directories contain three views each:

- `cli-workbench.png`: production `Workbench.frame`, 120 columns × 30 rows.
- `cli-image-encoding.png`: production `Workbench.encoding` / `Console.paint`, PNG level 6.
- `cli-language.png`: production `UI.choose_language` / `Console.paint`.

These are raster exports of the real CLI cell layout, not desktop screenshots or AI mockups. Generic paths are presentation fixtures; no private document pages are included. Each README uses images in its own language. Native terminal automation is excluded by the available computer-use skill, so these images are explicitly labelled as layout renders.

Reproduce from the repository root with pinned PDF dependencies and Windows fonts:

```powershell
python .\scripts\render_readme_images.py `
  --cli .\build-native\scantailor-cli.exe `
  --output .\docs\images\en `
  --state-dir .\build-native\readme-languages\en `
  --language en
```

Use `zh-Hans` or `zh-Hant` for the other languages. The state directory must be a scratch directory, not a user's task store. Renderers cancel form drafts after capture and do not launch processing jobs. Refresh and inspect these images when controls or translations change. Older root-level illustrations remain historical artifacts.
