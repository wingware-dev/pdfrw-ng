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

- After an incremental update, pdfrw could show pages from an older
  revision: objects in object streams were loaded before newer xref
  sections were merged, so an old member overrode its newer version.
  All xref sections are now merged, newest first, before any object
  stream is read (#121, #177, #188, #223, #237, #181).
- Hybrid-reference files are read: the `/XRefStm` stream a table
  trailer points to is followed. Before, objects listed only there
  were missing, often leaving 0 pages.
- `/Encrypt` is taken from the newest trailer, after the merge, and
  before object streams are read. In linearized encrypted files the
  oldest trailer has no `/Encrypt`, so pdfrw never decrypted them
  (#179).
- The reader's trailer entries come from the newest trailer that has
  each, and no longer include the per-section keys `/Prev`,
  `/XRefStm`, `/W`, `/Index` and the xref stream's filter keys, which
  a copy wrote into its own trailer.
- A `/Prev` chain that loops back on itself is read once, with a
  warning, instead of hanging.

### Encryption

### Writer and objects

- Fixed invalid escape sequences in `pdfrw.objects.pdfstring`
  docstrings. They raised SyntaxWarning on Python 3.12+, and importing
  pdfrw failed under `-W error` (#170).
- `PdfWriter.write` builds the whole file in memory before opening the
  target, so a failure while writing leaves an existing file untouched
  and writes nothing to a file object, instead of leaving a 0-byte or
  truncated file (#135, #160).
- Booleans are written as `true` and `false`, not `True` and `False`,
  which qpdf read as null (#37, #127). Python `None` in an array is
  written as `null`.
- Carriage returns in literal strings are escaped as `\r`. Readers
  turned a bare CR or CRLF into LF (#147).
- `PdfDict.update` and `PdfDict.setdefault` check that every key is a
  PdfName, as item assignment does, and raise `PdfParseError` before
  changing anything. A str key used to fail only when the file was
  written (#135). `update` treats keyword arguments as the constructor
  does, and a value of None deletes the key.
- `copy.copy`, `copy.deepcopy` and pickle work for `PdfDict`,
  `PdfArray`, `PdfName` and `PdfIndirect`, including pages read from a
  file, without copying the `PdfReader`. Attribute lookups of Python
  special names such as `__deepcopy__` no longer read the dictionary
  (#141).
- Comparing `PdfDict` and `PdfArray` objects no longer raises
  RecursionError on page trees and other cycles, or on long chains
  (#212). Equality resolves indirect references and also compares
  stream data, so different content streams of the same length are no
  longer equal.
- `PdfString.decode_hex` pads an odd-length hex string with a trailing
  0, as the spec says, instead of raising `binascii.Error`.
- A `#` in a name made with `PdfName(...)` is written as `#23`, as the
  spec requires. `PdfName('A#41')` used to be written as `/A#41`, which
  readers decode as `/AA`.

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

- `rl2/copy.py` is renamed `rl2/copy_pdf.py`. Its name shadowed the
  standard library's `copy` module, so reportlab failed to import
  (#218). `rl2/decodegraphics.py` now uses `inspect.getfullargspec`
  (`getargspec` was removed in Python 3.11), and it decodes text
  without the `PdfString.decode(remap, twobyte)` API, which no longer
  exists.
- `booklet.py` no longer crashes on a 1-page file. With `-p`, a blank
  half sheet no longer moves the page beside it to the wrong half.
- `subset.py` and `rotate.py` refuse page 0 and out-of-range pages;
  page 0 used to select the last page. Descending ranges such as `5-3`
  now work.
- `rl1/booklet.py` no longer drops a page whose dictionary equals its
  neighbour's (pages were compared by value, not identity).
- `subset_booklets.py` runs on Python 3 and writes
  `subset_booklets.<name>.pdf`, as its docstring says.
- `extract.py` on a file without XObjects, `rl1/subset.py` with bad page
  numbers and `rotate.py` with a bad angle now exit with a message
  instead of a traceback. `rl1/subset.py`'s last page argument is
  optional.
- `alter.py` no longer crashes on a file without an `/Info` dictionary.
- New `tests/test_examples.py` runs every example on generated PDFs and
  checks the output with qpdf, pypdf and PDFium.

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
