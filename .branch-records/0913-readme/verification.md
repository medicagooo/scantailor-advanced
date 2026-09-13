# README verification

Verified on 2026-09-14 (Asia/Singapore), on `0913-readme`, based on
`a085c0896220ede7763ae6f3b666b6306c54f6d7` (the preceding local completion-UI fix).
Documentation and illustration tooling only; no processing behavior changed.

- English default README and linked Simplified Chinese version emphasize CLI,
  guided terminal setup, image processing, PDF batches, encoding, review and resume.
- The former README is preserved as `docs/UPSTREAM-README.md`; relative file links
  were adjusted and historical upstream distribution claims are explicitly scoped.
- 118 local links and all new README anchors resolve. Code fences are balanced;
  both language versions have identical PowerShell and JSON examples.
- `scripts/render_readme_images.py` successfully exported the production workbench
  and encoding dialog layouts. Both PNGs were visually inspected and decoded:
  1320×840 / 1100×420. No private paths or PDF contents are included in the images.
- Native image processing completed all 3 authored demo pages; sample output-stage
  preview with `--pages sample --html` completed 3/3, exit 0.
- User-supplied nine-page PDF processed with CLI 3.2.1, PNG level 6, 150 DPI,
  2 workers: 9 complete, 0 review, 0 errors. The same command with `-Resume`
  reported `pdf_reused`. All 9 output pages have the original visible dimensions
  and can be rendered. This validates the sample workflow, not all scan quality.
- Local test result: `build-native/readme-pdf-test/test file.deskew.pdf` and its
  `batch-report.json`; test documents, scratch scripts and binaries remain ignored.
- Desktop capture was attempted using the computer-use skill. After interruption
  and a user-authorized restart, the helper still reported
  `foreground window did not report a process id`. Illustrations are therefore
  clearly labelled production-layout renders, not desktop screenshots.
- GitHub release inventory was read with `gh release list` and returned no releases
  for this fork. No release download link or publication is claimed.

Publication: local branch only; no remote push authorized for this documentation
request. Registry validation and staged whitespace checks must pass before commit.
