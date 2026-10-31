# Changelog

The code was imported, without its git history, from
[pmaupin/pdfrw](https://github.com/pmaupin/pdfrw) at commit 6c89216
(2018-02-16), the last upstream commit. That is pdfrw 0.4 plus two fixes
that were never released (#113 PNG Paeth/Avg filters, #228).

Upstream issue numbers (#NNN) refer to
https://github.com/pmaupin/pdfrw/issues. Each fix that has an upstream
issue cites it, and each fix has a regression test that builds its own
PDF and checks the result with independent tools (qpdf via pikepdf,
pypdf, PDFium). Before/after screenshots of the main visible fixes are
in [docs/shots/](docs/shots/).

## 0.5.0 (unreleased)

The distribution is named `pdfrw-ng`; the import name is still `pdfrw`.

### Reader

- After an incremental update, pdfrw could show pages from an older
  revision: objects in object streams were loaded before newer xref
  sections were merged, so an old member overrode its newer version.
  All xref sections are now merged, newest first, before any object
  stream is read (#121, #177, #188, #223, #237, #181).
  [Screenshot](docs/shots/stale-page-tree.png).
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
- A damaged page tree no longer loses every page. One dangling `/Kids`
  reference, or a `/Pages` node without `/Type`, used to give 0 pages,
  and a copy written from the reader had none. Now only the bad node is
  skipped, with a warning, as PDFium and pypdf do. Kids that are not
  dictionaries are skipped. A node with `/Kids` but no `/Type` is read
  as `/Pages`, and a kid with neither as `/Page`. Leaves with any other
  `/Type` are skipped, and so is a `/Pages` node that loops back to its
  own ancestor. The tree is repaired to match, so written copies show
  the same pages. [Screenshot](docs/shots/dangling-kids.png).
- Damaged files are read instead of raising. When the cross-reference
  data cannot be used, it is rebuilt by scanning the file for objects,
  trailers and object streams, and the catalog is found by its /Type
  if no trailer names it. Specifically:
  - A missing `%%EOF` is a warning, not fatal (#168). NUL padding
    after it is accepted (#136).
  - Junk before the `%PDF-` header is skipped, and offsets count from
    the header (#242).
  - `startxref` glued to its number no longer trips an assert (#211).
    A huge or out-of-range `startxref` no longer raises
    OverflowError (#210), and a bad `/Prev` no longer raises either.
  - An object cut off by the end of the file is logged and reads as
    null, instead of failing the whole read (#145).
  - A stream `/Length` past the end of the file, negative,
    non-numeric or missing ends the stream at `endstream` (#199).
  - The tokenizer no longer raises RuntimeError at the end of data
    on Python 3.7+ (it used `raise StopIteration` in a generator).
- Ctrl-C (KeyboardInterrupt) and SystemExit while a cross-reference
  table is parsed now reach the caller instead of being taken for a
  badly formatted table (upstream PR #256 by @koteshyelamati).
- A stream whose `/DecodeParms` is `null`, or an array holding
  `null`, is decompressed with the filter's defaults instead of
  raising (upstream PR #110 by @erezarnon).

### Encryption

- Encrypted files are read on Python 3. `pdfrw.crypt` was written for
  Python 2 strings, and `decrypt=True` raised TypeError for RC4 and
  AES-128 (#48). Supported: RC4 40 to 128 bit (built in, so no extra
  package is needed), AES-128, and AES-256 (revisions 5 and 6, new).
  AES needs the `crypto` extra (pycryptodome); without it the error
  says what to install.
- Encrypted files are always decrypted as they are read, not only with
  `decrypt=True`. Before, reading one without it kept the ciphertext:
  a copy had blank pages and gave no warning, and files with object
  streams crashed (#116, #249, #200). A file with an empty user
  password opens without one. Otherwise pass the user or owner
  password as `password=`. A wrong or missing password, or an
  unsupported security handler, raises the new `PdfDecryptionError`
  (a `PdfParseError`) instead of returning ciphertext. `decrypt=True`
  now only reads every object up front.
  [Screenshot](docs/shots/encrypted-copy.png).
- Strings are decrypted as well as streams (#123). Cross-reference
  streams, signature `/Contents`, and the XMP metadata stream when
  `/EncryptMetadata` is false are left as stored. A stream's own
  `/Crypt` filter is honoured and then removed.
- A copy written from an encrypted file is a complete unencrypted PDF:
  its trailer has no `/Encrypt`, unless the writer is asked to encrypt.
- `PdfWriter(..., encrypt=Encryption(user_password, owner_password,
  method, permissions, encrypt_metadata))` writes encrypted files:
  AES-256 (revision 6, the default), AES-128 or RC4 128-bit. Output
  is still unencrypted by default. AES needs the `crypto` extra; without
  it the error says what to install. qpdf, pypdf, PDFium and pdfrw open
  the output with the user and the owner password.
- A damaged encrypted file whose cross-reference data has to be
  rebuilt now reads the objects in its object streams. Before, it had
  no pages.
- In AES-256 files, `/Perms` is checked against `/P` and
  `/EncryptMetadata` (Algorithm 13 of PDF 32000-2). A mismatch means
  the permissions may have been altered: it is logged as a warning and
  the file is still read. `reader.crypt_handler.perms_ok` gives the
  result.
- AES-256 passwords are prepared with SASLprep (RFC 4013) before
  they are hashed, as the spec requires, so a password typed in
  another Unicode form, such as with decomposed accents, still opens
  the file. The password as given is also tried, for writers that skip
  SASLprep.

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
  [Screenshot](docs/shots/cr-in-strings.png).
- `PdfDict.update` and `PdfDict.setdefault` check that every key is a
  PdfName, as item assignment does, and raise `PdfParseError` before
  changing anything. A str key used to fail only when the file was
  written (#135). `update` treats keyword arguments as the constructor
  does, and a value of None deletes the key.
  [Screenshot](docs/shots/str-key-write.png).
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
- `PdfDict.pop` accepts a default, as `dict.pop` does, and
  `PdfDict.popitem` returns a `(key, value)` pair; it used to raise
  TypeError on every call. Both resolve indirect objects, and an entry
  that resolves to null counts as missing.
- Writing a str that holds characters outside latin-1 (for example in a
  stream) raises `PdfOutputEncodingError`, which names the object
  number or the trailer, says whether the stream or a name or value is
  at fault, and shows the character. It subclasses both
  `PdfOutputError` and `UnicodeEncodeError`, so existing handlers still
  catch it, and it is raised when compressing or encrypting too (#160).
  `PdfOutputError` and `PdfOutputEncodingError` are now exported from
  `pdfrw`.

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
- `pagexobj` keeps a page's content compressed when the page's
  `/Contents` is an array of compressed streams. Before, the joined
  Form XObject was written uncompressed even with
  `allow_compressed=True`.
- A fractional `viewrect` whose four numbers are all equal, such as
  `0.5,0.5,0.5,0.5` for the bottom-right quarter of the page, is read as
  fractions, as documented. Before, it was read as points and gave a
  box half a point wide.
- `page_per_xobj` no longer swallows KeyboardInterrupt or SystemExit
  raised while it checks its `margin` argument, and no longer changes
  a short `margin` list passed to it. Padding it to four sides used to
  grow the caller's own list in place.

### Examples

- `rl2/copy.py` is renamed `rl2/copy_pdf.py`. Its name shadowed the
  standard library's `copy` module, so reportlab failed to import
  (#218). `rl2/decodegraphics.py` now uses `inspect.getfullargspec`
  (`getargspec` was removed in Python 3.11), and it decodes text
  without the `PdfString.decode(remap, twobyte)` API, which no longer
  exists.
- `booklet.py` no longer crashes on a 1-page file. With `-p`, a blank
  half sheet no longer moves the page beside it to the wrong half.
  [Screenshot](docs/shots/booklet-padding.png).
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
- New `make_sample.py` writes `build/sample.pdf`, a numbered sample to
  try the other examples on, using the test suite's PDF builder (needs a
  source checkout).
- Page-range parsing and two-up layout shared by `booklet.py`,
  `rotate.py`, `subset.py` and `subset_booklets.py` moved into a new
  helper module, `examples/pagetools.py`. The scripts' command lines and
  output are unchanged.
- `examples/rl2/decodegraphics.py` no longer fails with "dictionary
  changed size during iteration" when a module global is added while it
  builds its operator dispatch table (upstream PR #215 by @Lucas-C).
- New `6up.py` and `9up.py` put six (two across, three down) or nine
  (three by three) pages on each output page, using a new `grid()`
  helper in `examples/pagetools.py`; a partly filled last sheet is the
  same size as the others (upstream PR #248 by @mjbright).
- `4up.py` now uses the same `grid()` helper, so a last sheet holding
  one page is no longer half as wide, and it prints its usage instead
  of a traceback when given the wrong arguments.

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
- The suite has 483 tests and covers 87% of `pdfrw/` with branch
  coverage (90% of lines), up from 28% of lines with upstream's offline
  tests ([coverage by module](docs/shots/coverage.png)). CI fails below
  85% branch coverage.
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
  reportlab link (#225). Its "Missing features" and "File reading"
  sections now say what works: FlateDecode is the only decompression
  filter, the standard security handler is read with RC4, AES-128 and
  AES-256, and damaged and incrementally updated files are read. A
  "Before and after" section links the screenshots in docs/shots/.
- Fixed typos in README.rst (upstream PR #167 by @jwilk and PR #260 by
  @haimingZZ).
- The README's "Reading PDFs" example shows decoding an Info string with
  `PdfString.decode()` (upstream PR #163 by @jamy015).
- Listed every author named in LICENSE.txt in the `pyproject.toml`
  `authors`.
