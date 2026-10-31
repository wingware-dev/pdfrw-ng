# Changelog

The code was imported, without its git history, from
[pmaupin/pdfrw](https://github.com/pmaupin/pdfrw) at commit 6c89216
(2018-02-16), the last upstream commit. That is pdfrw 0.4 plus two fixes
that were never released (#113 PNG Paeth/Avg filters, #228).

Upstream issue numbers (#NNN) refer to
https://github.com/pmaupin/pdfrw/issues. Each fix cites its issue, and
each has a regression test that builds its own PDF and checks the
result with independent tools (qpdf via pikepdf, pypdf, PDFium).

## 0.5.0 (unreleased)

The distribution is named `pdfrw-ng`; the import name is still `pdfrw`.

### Reader

### Encryption

### Writer and objects

- Fixed invalid escape sequences in `pdfrw.objects.pdfstring`
  docstrings. They raised SyntaxWarning on Python 3.12+, and importing
  pdfrw failed under `-W error` (#170).

### PageMerge, findobjs and logging

- Setting `RectXObj.h` scales the object by its height. Before, it
  scaled by the width, so the height ended up wrong (#219).
- `page_per_xobj(..., image_only=True)` finds Image XObjects. A
  `PdfName.IMage` typo meant it never matched anything (#152).
- Importing pdfrw no longer attaches a StreamHandler to the `pdfrw`
  logger or sets the logger's level. The logger gets only a
  `NullHandler`, so the application's logging configuration decides
  where pdfrw warnings go. `pdfrw.errors.handler` and
  `pdfrw.errors.fmt` still exist but are no longer attached by default;
  `log.addHandler(pdfrw.errors.handler)` restores the old output (#230).

### Examples

### Packaging

- Replaced `setup.py`, `setup.cfg`, `MANIFEST.in` and `releasing.txt` with
  a hatchling `pyproject.toml`. The distribution is `pdfrw-ng` 0.5.0. It
  requires Python 3.11 or later and has an optional `crypto` extra
  (pycryptodome).
- Dropped Python 2 and Python 3 versions before 3.11. Supported versions
  are 3.11 to 3.15 and PyPy 3.11.
- The test suite runs offline. Tests build their own PDFs with
  `tests/pdfgen.py` and check output with `tests/validate.py`, and
  network access is blocked during tests. Removed the tests and artifacts
  that needed the external static_pdfs corpus: `test_examples`,
  `test_roundtrip`, the `expected` files, `checkdiffs`,
  `update_expected`, `myprofile` and the notebook.
- Replaced the PngSuite `.png.log` vectors with generated PNG-predictor
  round trips. The flate PNG test no longer writes `.pickle` files into
  `tests/`.
- Replaced Travis CI with GitHub Actions on Linux, macOS and Windows for
  CPython 3.11 to 3.15 and PyPy 3.11, with coverage and warnings as
  errors.
- Rewrote README.rst for the fork. It covers installing `pdfrw-ng` from
  source (it is not on PyPI), uninstalling `pdfrw`/`pdfrw2` first,
  supported Python versions, running the offline tests, and credits for
  Patrick Maupin and the other original authors. Fixed the dead
  reportlab link (#225).
- Listed every author named in LICENSE.txt in the `pyproject.toml`
  `authors`.
