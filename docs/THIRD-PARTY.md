# Portable build provenance

This local build contains ScanTailor Advanced (GPL-3.0; root `LICENSE`) from
`https://github.com/medicagooo/scantailor-advanced`, based on commit
`f9bf198e2797863c31408b2c1f84acac8c4fdd0d`, plus the 0910-cli-full branch's CLI 2 changes.

Build inputs used on 2026-09-10 and 2026-09-11:

- Qt 6.8.3, official MinGW 64-bit archives (Qt open-source licenses).
- Qt Tools MinGW 13.1.0, including GCC runtime and winpthreads (GCC runtime exception and respective runtime licenses).
- Boost 1.85.0 (Boost Software License); headers and static test library.
- Strawberry Perl C libraries: JPEG 9, PNG 1.6.43, TIFF 4.6.0, zlib 1.3.1,
  plus their WebP/SharpYUV dependencies. Binaries are copied from `C:/Strawberry/c/bin`.
- CPython 3.12.10 Windows embeddable distribution (PSF license, included in `python/LICENSE.txt`).
- PyMuPDF 1.28.2 (AGPL/commercial dual licensing; installed distribution metadata and license included).
- Pillow 12.3.0 (HPND and bundled library notices; installed distribution metadata and licenses included).
- Qt deployment also supplies Microsoft's D3D compiler runtime.

`manifest.json` records the exact packaged file hashes. Python package metadata
and bundled license texts remain under `python/Lib/site-packages/*.dist-info`.
This is a locally verified development package, not a published upstream release.
Before redistributing a package, retain the applicable license texts and provide
the corresponding sources required by its components' licenses.
