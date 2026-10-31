# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Byte-exact PDF builder for the test suite.

Tests never read PDFs from disk or the network: they build them here.
`PdfBuilder` writes every byte itself, so a test controls exactly what a
reader sees -- offsets, xref layout, and deliberate defects.  Output is
deterministic: the same calls always give the same bytes.

Low level, `PdfBuilder`:

    b = PdfBuilder()
    font = b.obj(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    ...
    b.xref_table(b'/Root 1 0 R')        # or xref_stream() / xref_hybrid()
    data = b.getvalue()

Objects written since the last xref section go into the next one, so
calling an xref method again after writing more objects makes an
incremental update whose trailer has /Prev.  `objstm()` packs objects into
an object stream (needs an xref stream or hybrid section).

High level:

    make_pdf(3)                               # 3 pages saying "Page 1".."Page 3"
    make_pdf(3, xref='stream', objstm=True)   # xref stream + ObjStm
    make_pdf(3, xref='hybrid', objstm=True)   # table + /XRefStm
    make_pdf(3, dangling_kids=1)              # /Kids has a ref to a missing object
    make_pdf(3, untyped_pages=True)           # /Pages node without /Type
    make_updated_pdf(5, keep=[0, 2, 4])       # incremental update rewrites /Pages

Byte-level defects: `truncate`, `strip_eof`, `junk_prefix`, `junk_suffix`.
Encryption (via pikepdf): `encrypt`.
"""

import io
import zlib

__all__ = [
    'PdfBuilder', 'PageTree', 'literal', 'page_content', 'page_label',
    'build_pages', 'make_pdf', 'make_updated_pdf',
    'truncate', 'strip_eof', 'junk_prefix', 'junk_suffix', 'encrypt',
]

DEFAULT_HEADER = b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\n'


def _b(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode('latin-1')
    raise TypeError('expected bytes or str, got %r' % type(value))


def literal(text):
    """Return `text` as a PDF literal string, parentheses included."""
    data = _b(text)
    data = (data.replace(b'\\', b'\\\\').replace(b'(', b'\\(')
            .replace(b')', b'\\)').replace(b'\r', b'\\r')
            .replace(b'\n', b'\\n'))
    return b'(' + data + b')'


class PdfBuilder(object):
    """Writes a PDF file section by section, keeping exact offsets.

    Each xref method closes a section: it writes the cross-reference data
    for the objects written since the previous section, the trailer,
    ``startxref`` and the end-of-file marker.
    """

    def __init__(self, header=DEFAULT_HEADER):
        self.buf = bytearray(_b(header))
        self.size = 1           # one more than the highest object number
        self.prev = None        # offset of the last xref section
        self.sections = 0
        self._next_num = 1
        self._entries = {}      # this section: num -> (type, field2, field3)

    # -- objects -------------------------------------------------------

    def alloc(self):
        """Reserve an object number without writing the object.

        A number reserved and never written is a dangling reference: it
        stays out of every xref section.
        """
        num = self._next_num
        self._next_num += 1
        self.size = max(self.size, num + 1)
        return num

    def _claim(self, num):
        if num is None:
            return self.alloc()
        self._next_num = max(self._next_num, num + 1)
        self.size = max(self.size, num + 1)
        return num

    def tell(self):
        return len(self.buf)

    def raw(self, data):
        """Append bytes as they are (comments, junk, broken objects)."""
        self.buf += _b(data)

    def obj(self, body, num=None, gen=0):
        """Write an indirect object and return its number."""
        num = self._claim(num)
        self._entries[num] = (1, self.tell(), gen)
        self.buf += b'%d %d obj\n' % (num, gen) + _b(body) + b'\nendobj\n'
        return num

    def stream(self, data, extra=b'', num=None, gen=0, compress=False,
               length=None):
        """Write a stream object.

        `extra` holds more dictionary entries, such as b'/Type /XObject'.
        `compress` applies /FlateDecode.  `length` overrides the /Length
        written, to make a stream whose /Length is wrong.
        """
        data = _b(data)
        extra = _b(extra)
        if compress:
            data = zlib.compress(data, 9)
            extra = b'/Filter /FlateDecode ' + extra
        if length is None:
            length = len(data)
        body = (b'<< ' + extra + (b' ' if extra else b'') +
                b'/Length %d >>\nstream\n' % length + data + b'\nendstream')
        return self.obj(body, num=num, gen=gen)

    def objstm(self, members, num=None, compress=True):
        """Write an object stream holding `members`.

        `members` maps object numbers (or None, to allocate one) to
        object bodies, in order.  Returns ``(stream_num, [member_nums])``.
        Members must not be streams, and need an xref stream or hybrid
        section to be found.
        """
        nums = []
        bodies = []
        for member_num, body in members:
            nums.append(self._claim(member_num))
            bodies.append(_b(body))
        offsets = []
        payload = bytearray()
        for body in bodies:
            offsets.append(len(payload))
            payload += body + b'\n'
        index = b' '.join(b'%d %d' % pair for pair in zip(nums, offsets))
        index += b'\n'
        stm_num = self.stream(
            index + payload, num=num, compress=compress,
            extra=b'/Type /ObjStm /N %d /First %d' % (len(nums), len(index)))
        for idx, member_num in enumerate(nums):
            self._entries[member_num] = (2, stm_num, idx)
        return stm_num, nums

    def free(self, num, gen=1):
        """Mark `num` free in the next section (deleting it)."""
        self._entries[num] = (0, 0, gen)
        self.size = max(self.size, num + 1)

    # -- xref sections ---------------------------------------------------

    def _trailer_dict(self, trailer, extra=b''):
        parts = [b'/Size %d' % self.size]
        if self.prev is not None:
            parts.append(b'/Prev %d' % self.prev)
        if extra:
            parts.append(extra)
        trailer = _b(trailer)
        if trailer:
            parts.append(trailer)
        return b' '.join(parts)

    def _all_entries(self):
        entries = dict(self._entries)
        if self.sections == 0:
            entries[0] = (0, 0, 65535)
        return entries

    @staticmethod
    def _subsections(nums):
        """Group sorted object numbers into (first, count) runs."""
        runs = []
        for num in sorted(nums):
            if runs and runs[-1][0] + runs[-1][1] == num:
                runs[-1][1] += 1
            else:
                runs.append([num, 1])
        return runs

    def _table_bytes(self, entries):
        out = bytearray(b'xref\n')
        for first, count in self._subsections(entries):
            out += b'%d %d\n' % (first, count)
            for num in range(first, first + count):
                kind, field2, field3 = entries[num]
                letter = b'n' if kind == 1 else b'f'
                out += b'%010d %05d %s\r\n' % (field2, field3, letter)
        return bytes(out)

    def _finish(self, xref_offset, eof):
        self.buf += b'startxref\n%d\n' % xref_offset + _b(eof)
        self.prev = xref_offset
        self.sections += 1
        self._entries = {}

    def xref_table(self, trailer=b'', eof=b'%%EOF\n', extra=b''):
        """Close the section with a classic xref table.  Returns its offset."""
        entries = self._all_entries()
        if any(kind == 2 for kind, _, _ in entries.values()):
            raise ValueError('an xref table cannot point into an object '
                             'stream: use xref_stream() or xref_hybrid()')
        offset = self.tell()
        self.buf += self._table_bytes(entries)
        self.buf += (b'trailer\n<< ' + self._trailer_dict(trailer, extra) +
                     b' >>\n')
        self._finish(offset, eof)
        return offset

    def _xref_stream_obj(self, entries, extra_dict, num, compress):
        """Write an xref stream holding `entries` plus its own entry."""
        num = self._claim(num)
        offset = self.tell()
        entries = dict(entries)
        entries[num] = (1, offset, 0)
        runs = self._subsections(entries)
        rows = bytearray()
        for first, count in runs:
            for n in range(first, first + count):
                kind, field2, field3 = entries[n]
                rows += bytes([kind]) + field2.to_bytes(4, 'big') + \
                    (field3 & 0xffff).to_bytes(2, 'big')
        index = b' '.join(b'%d %d' % (first, count) for first, count in runs)
        data = bytes(rows)
        extra = b'/Type /XRef /W [1 4 2] /Index [' + index + b'] ' + \
            _b(extra_dict)
        if compress:
            data = zlib.compress(data, 9)
            extra = b'/Filter /FlateDecode ' + extra
        body = (b'<< ' + extra + b' /Length %d >>\nstream\n' % len(data) +
                data + b'\nendstream')
        # Written by hand, not with obj(), so its own entry is not added
        # to the next section.
        self.buf += b'%d 0 obj\n' % num + body + b'\nendobj\n'
        return num, offset

    def xref_stream(self, trailer=b'', eof=b'%%EOF\n', num=None,
                    compress=True):
        """Close the section with an xref stream.  Returns its offset."""
        entries = self._all_entries()
        num = self._claim(num)
        _, offset = self._xref_stream_obj(
            entries, self._trailer_dict(trailer), num, compress)
        self._finish(offset, eof)
        return offset

    def xref_hybrid(self, trailer=b'', eof=b'%%EOF\n', num=None,
                    compress=True):
        """Close the section as a hybrid-reference file section.

        The classic table lists the ordinary objects; an xref stream,
        found only through the trailer's /XRefStm, lists the objects in
        object streams.  Returns the offset of the table.
        """
        entries = self._all_entries()
        compressed = dict((n, e) for n, e in entries.items() if e[0] == 2)
        plain = dict((n, e) for n, e in entries.items() if e[0] != 2)
        num = self._claim(num)
        # The stream's /Size must not undercut the trailer's.
        stm_num, stm_offset = self._xref_stream_obj(
            compressed, b'/Size %d' % self.size, num, compress)
        plain[stm_num] = (1, stm_offset, 0)
        offset = self.tell()
        self.buf += self._table_bytes(plain)
        self.buf += (b'trailer\n<< ' +
                     self._trailer_dict(trailer, b'/XRefStm %d' % stm_offset)
                     + b' >>\n')
        self._finish(offset, eof)
        return offset

    def getvalue(self):
        return bytes(self.buf)


# -- page trees ----------------------------------------------------------

def page_label(index):
    """The text on page `index` (0-based) of a generated file."""
    return 'Page %d' % (index + 1)


def page_content(text):
    """A content stream drawing `text` in 24pt Helvetica."""
    return b'BT /F1 24 Tf 72 720 Td ' + literal(text) + b' Tj ET'


class PageTree(object):
    """Object numbers of what `build_pages` wrote."""

    def __init__(self, catalog, pages, font, page_nums, content_nums,
                 dangling):
        self.catalog = catalog
        self.pages = pages
        self.font = font
        self.page_nums = page_nums
        self.content_nums = content_nums
        self.dangling = dangling

    @property
    def root_ref(self):
        return b'/Root %d 0 R' % self.catalog


def build_pages(builder, npages, labels=None, objstm=False,
                untyped_pages=False, dangling_kids=0, compress=False):
    """Write a catalog, a flat page tree and `npages` text pages.

    Page `i` shows `labels[i]`, by default "Page i+1".  With `objstm`, the
    catalog, page tree and page dictionaries go into one object stream.
    `untyped_pages` leaves /Type out of the /Pages node.  `dangling_kids`
    appends that many references to objects that are never written to
    /Kids (and /Count still counts only the real pages).
    """
    if labels is None:
        labels = [page_label(i) for i in range(npages)]
    if len(labels) != npages:
        raise ValueError('need one label per page')

    catalog = builder.alloc()
    pages = builder.alloc()
    font = builder.alloc()
    page_nums = [builder.alloc() for _ in range(npages)]
    dangling = [builder.alloc() for _ in range(dangling_kids)]

    content_nums = [builder.stream(page_content(label), compress=compress)
                    for label in labels]

    kids = b' '.join(b'%d 0 R' % n for n in page_nums + dangling)
    pages_type = b'' if untyped_pages else b'/Type /Pages '
    dicts = [
        (catalog, b'<< /Type /Catalog /Pages %d 0 R >>' % pages),
        (pages, b'<< ' + pages_type + b'/Kids [' + kids + b'] /Count %d >>'
         % npages),
        (font, b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica '
               b'/Encoding /WinAnsiEncoding >>'),
    ]
    for page_num, content_num in zip(page_nums, content_nums):
        dicts.append((page_num, (
            b'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] '
            b'/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>'
            % (pages, font, content_num))))
    if objstm:
        builder.objstm(dicts)
    else:
        for num, body in dicts:
            builder.obj(body, num=num)
    return PageTree(catalog, pages, font, page_nums, content_nums, dangling)


def _close(builder, xref, trailer):
    if xref == 'table':
        builder.xref_table(trailer)
    elif xref == 'stream':
        builder.xref_stream(trailer)
    elif xref == 'hybrid':
        builder.xref_hybrid(trailer)
    else:
        raise ValueError('xref must be table, stream or hybrid: %r' % xref)


def make_pdf(npages=3, xref='table', objstm=False, labels=None,
             untyped_pages=False, dangling_kids=0, compress=False,
             header=DEFAULT_HEADER):
    """Build a whole PDF with `npages` numbered text pages; return bytes.

    `xref` is 'table', 'stream' or 'hybrid'.  `objstm` needs 'stream' or
    'hybrid'.  See `build_pages` for the other options.
    """
    if objstm and xref == 'table':
        raise ValueError("objstm needs xref='stream' or 'hybrid'")
    builder = PdfBuilder(header)
    tree = build_pages(builder, npages, labels=labels, objstm=objstm,
                       untyped_pages=untyped_pages,
                       dangling_kids=dangling_kids, compress=compress)
    _close(builder, xref, tree.root_ref)
    return builder.getvalue()


def make_updated_pdf(npages, keep, xref='table', objstm=False,
                     update_xref=None, update_objstm=False):
    """Build a PDF, then append an incremental update rewriting /Pages.

    The original revision has `npages` pages; the update's /Pages node
    lists only the pages at the 0-based indexes in `keep`, in that order.
    A correct reader shows ``len(keep)`` pages.  `xref`/`objstm` shape the
    original revision and `update_xref`/`update_objstm` the update
    (`update_xref` defaults to `xref`).
    """
    if update_xref is None:
        update_xref = xref
    if objstm and xref == 'table':
        raise ValueError("objstm needs xref='stream' or 'hybrid'")
    if update_objstm and update_xref == 'table':
        raise ValueError("update_objstm needs update_xref='stream' or "
                         "'hybrid'")
    builder = PdfBuilder()
    tree = build_pages(builder, npages, objstm=objstm)
    _close(builder, xref, tree.root_ref)

    kids = b' '.join(b'%d 0 R' % tree.page_nums[i] for i in keep)
    body = b'<< /Type /Pages /Kids [' + kids + b'] /Count %d >>' % len(keep)
    if update_objstm:
        builder.objstm([(tree.pages, body)])
    else:
        builder.obj(body, num=tree.pages)
    _close(builder, update_xref, tree.root_ref)
    return builder.getvalue()


# -- byte-level defects --------------------------------------------------

def truncate(data, length):
    """The first `length` bytes of `data`; a negative length cuts that
    many bytes off the end."""
    return bytes(data[:length])


def strip_eof(data):
    """`data` without its final %%EOF marker (and what follows it)."""
    index = data.rfind(b'%%EOF')
    if index < 0:
        raise ValueError('no %%EOF marker')
    return bytes(data[:index])


def junk_prefix(data, junk=b'garbage before the header\n'):
    """`data` with bytes before %PDF-, which shifts every real offset."""
    return _b(junk) + bytes(data)


def junk_suffix(data, junk=b'\ngarbage after the end\n'):
    """`data` with bytes after the last %%EOF."""
    return bytes(data) + _b(junk)


# -- encryption ----------------------------------------------------------

def encrypt(data, user='', owner='owner', R=4, aes=True, metadata=None,
            object_streams=False):
    """Encrypt `data` with pikepdf (qpdf) and return the new bytes.

    R=2 is RC4 40-bit, R=3 RC4 128-bit, R=4 RC4 or AES-128 (`aes`), R=6
    AES-256.  An empty `user` password opens without a password.
    `metadata` (whether to encrypt the XMP metadata) defaults to what qpdf
    allows: only AES at R >= 4.  `object_streams` makes qpdf pack objects
    into object streams.  Output is not byte-stable: encryption salts are
    random.
    """
    import pikepdf
    mode = (pikepdf.ObjectStreamMode.generate if object_streams
            else pikepdf.ObjectStreamMode.disable)
    if R < 4:
        aes = False
    if metadata is None:
        metadata = aes
    with pikepdf.open(io.BytesIO(data)) as pdf:
        out = io.BytesIO()
        pdf.save(out, object_stream_mode=mode, static_id=True,
                 encryption=pikepdf.Encryption(user=user, owner=owner, R=R,
                                               aes=aes, metadata=metadata))
    return out.getvalue()
