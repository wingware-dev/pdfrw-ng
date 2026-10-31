# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""How PdfReader merges cross-reference sections.

Incremental updates (#121, #177, #188, #223, #237, #181), hybrid-reference
files with /XRefStm, linearized files, and /Encrypt from the newest
trailer (#179).  Every input is generated, checked with qpdf, pypdf and
PDFium first, and pdfrw must then see the same pages those tools do.
"""

import io
import logging

import pytest

from pdfrw import PdfReader, PdfWriter
from pdfrw import pdfreader

from . import pdfgen
from .pdfgen import PdfBuilder, build_pages, make_pdf, make_updated_pdf
from .pdfgen import page_label
from .validate import assert_valid, pdfium_page_texts, require


def labels_of(reader):
    """The text each page draws, from its (uncompressed) content stream."""
    labels = []
    for page in reader.pages:
        contents = page.Contents
        if contents is None:
            labels.append('')
            continue
        stream = contents.stream
        labels.append(stream[stream.index('(') + 1:stream.index(')')])
    return labels


def read(data, **kw):
    return PdfReader(fdata=data, decompress=True, **kw)


def written(reader):
    out = io.BytesIO()
    PdfWriter(out, trailer=reader).write()
    return out.getvalue()


# -- incremental updates ---------------------------------------------------

UPDATE_LAYOUTS = [
    # (original xref, original objstm, update xref, update objstm)
    ('table', False, 'table', False),
    ('stream', False, 'stream', False),
    ('stream', True, 'stream', False),      # #121: ObjStm then plain update
    ('stream', True, 'table', False),
    ('stream', True, 'stream', True),
    ('stream', False, 'stream', True),
    ('table', False, 'stream', True),
    ('hybrid', True, 'hybrid', False),
    ('hybrid', True, 'hybrid', True),
    ('hybrid', False, 'stream', True),
]


@pytest.mark.parametrize('xref, objstm, update_xref, update_objstm',
                         UPDATE_LAYOUTS)
def test_update_rewriting_pages(xref, objstm, update_xref, update_objstm):
    """An update keeps pages 1, 3 and 5 of 5: pdfrw must show 3 pages,
    as qpdf, pypdf and PDFium do, whatever the xref layout (#121)."""
    keep = [0, 2, 4]
    expected = [page_label(i) for i in keep]
    data = make_updated_pdf(5, keep, xref=xref, objstm=objstm,
                            update_xref=update_xref,
                            update_objstm=update_objstm)
    assert_valid(data, texts=expected)
    reader = read(data)
    assert len(reader.pages) == 3
    assert reader.numPages == 3
    assert labels_of(reader) == expected


def test_update_reorders_pages():
    keep = [3, 0, 2]
    expected = [page_label(i) for i in keep]
    data = make_updated_pdf(4, keep, xref='stream', objstm=True)
    assert_valid(data, texts=expected)
    assert labels_of(read(data)) == expected


def test_several_updates_newest_wins():
    """Three revisions, each moving /Pages: only the newest counts."""
    builder = PdfBuilder()
    tree = build_pages(builder, 4, objstm=True)
    builder.xref_stream(tree.root_ref)
    for keep, objstm in (([0, 1, 2], False), ([2, 1], True)):
        kids = b' '.join(b'%d 0 R' % tree.page_nums[i] for i in keep)
        body = (b'<< /Type /Pages /Kids [' + kids + b'] /Count %d >>'
                % len(keep))
        if objstm:
            builder.objstm([(tree.pages, body)])
        else:
            builder.obj(body, num=tree.pages)
        builder.xref_stream(tree.root_ref)
    data = builder.getvalue()
    expected = [page_label(2), page_label(1)]
    assert_valid(data, texts=expected)
    assert labels_of(read(data)) == expected


def test_written_copy_of_update_is_valid():
    """Copying an updated file writes only the newest revision's pages."""
    keep = [0, 2, 4]
    expected = [page_label(i) for i in keep]
    data = make_updated_pdf(5, keep, xref='stream', objstm=True)
    assert_valid(written(PdfReader(fdata=data)), texts=expected)


def test_update_replaces_objstm_member_with_plain_object():
    """A page that lived in an object stream, rewritten as a plain object
    by an update, is read from the update."""
    builder = PdfBuilder()
    tree = build_pages(builder, 2, objstm=True)
    builder.xref_stream(tree.root_ref)
    content = builder.stream(pdfgen.page_content('Changed'))
    builder.obj(b'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] '
                b'/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>'
                % (tree.pages, tree.font, content), num=tree.page_nums[1])
    builder.xref_table(tree.root_ref)
    data = builder.getvalue()
    expected = [page_label(0), 'Changed']
    assert_valid(data, texts=expected)
    assert labels_of(read(data)) == expected


def test_free_entry_in_update_keeps_older_object():
    """An update that frees an object still referenced: PDFium and pypdf
    keep reading the older revision's copy, and so does pdfrw, so that a
    stray free entry never loses content.  (qpdf reads null instead.)"""
    builder = PdfBuilder()
    tree = build_pages(builder, 3)
    builder.xref_table(tree.root_ref)
    builder.free(tree.content_nums[2])
    builder.xref_table(tree.root_ref)
    data = builder.getvalue()
    expected = [page_label(i) for i in range(3)]
    assert pdfium_page_texts(data) == expected
    assert labels_of(read(data)) == expected


def test_newer_generation_replaces_older():
    """An update that frees object N and reuses it as generation 1: a
    reference to generation 1 finds the new object."""
    builder = PdfBuilder()
    tree = build_pages(builder, 1)
    builder.xref_table(tree.root_ref)
    content = tree.content_nums[0]
    builder.stream(pdfgen.page_content('Reused'), num=content, gen=1)
    builder.obj(b'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] '
                b'/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 1 R >>'
                % (tree.pages, tree.font, content), num=tree.page_nums[0])
    builder.xref_table(tree.root_ref)
    data = builder.getvalue()
    assert_valid(data, texts=['Reused'])
    assert labels_of(read(data)) == ['Reused']


# -- trailers --------------------------------------------------------------

def test_trailer_from_newest_section():
    builder = PdfBuilder()
    tree = build_pages(builder, 1, objstm=True)
    old_info = builder.obj(b'<< /Title (Old) >>')
    builder.xref_stream(tree.root_ref + b' /Info %d 0 R' % old_info)
    new_info = builder.obj(b'<< /Title (New) >>')
    builder.xref_table(tree.root_ref + b' /Info %d 0 R' % new_info)
    data = builder.getvalue()
    assert_valid(data, pages=1)
    reader = PdfReader(fdata=data)
    assert reader.Info.Title == '(New)'
    assert int(reader.Size) == builder.size


def test_older_trailer_fills_missing_entries():
    """An update whose trailer leaves out /Info keeps the older one."""
    builder = PdfBuilder()
    tree = build_pages(builder, 1)
    info = builder.obj(b'<< /Title (Kept) >>')
    builder.xref_table(tree.root_ref + b' /Info %d 0 R' % info)
    builder.obj(b'<< /Type /Catalog /Pages %d 0 R >>' % tree.pages,
                num=tree.catalog)
    builder.xref_table(tree.root_ref)
    reader = PdfReader(fdata=builder.getvalue())
    assert reader.Info.Title == '(Kept)'


@pytest.mark.parametrize('xref', ['stream', 'hybrid'])
def test_section_keys_stay_out_of_trailer(xref):
    """/Prev, /XRefStm and the xref stream's own keys describe one
    section; the reader (and a copy written from it) must not carry
    them."""
    data = make_updated_pdf(3, [0, 1], xref=xref, objstm=True)
    reader = PdfReader(fdata=data)
    assert sorted(reader.keys()) == ['/Root', '/Size']
    assert_valid(written(reader), texts=[page_label(0), page_label(1)])


# -- hybrid-reference files ------------------------------------------------

@pytest.mark.parametrize('compress', [False, True])
def test_hybrid_follows_xrefstm(compress):
    """In a hybrid file the catalog and pages are only in the /XRefStm
    stream; pdfrw used to ignore it and find no pages."""
    expected = [page_label(i) for i in range(3)]
    data = make_pdf(3, xref='hybrid', objstm=True, compress=compress)
    assert_valid(data, texts=expected)
    assert labels_of(read(data)) == expected


def test_hybrid_bad_xrefstm_keeps_table(caplog):
    """A broken /XRefStm offset warns and keeps the table's entries."""
    data = make_pdf(2, xref='hybrid')
    start = data.index(b'/XRefStm ') + len(b'/XRefStm ')
    end = start
    while data[end:end + 1].isdigit():
        end += 1
    bad = b'%0*d' % (end - start, 1)
    data = data[:start] + bad + data[end:]
    with caplog.at_level(logging.WARNING, logger='pdfrw'):
        reader = read(data)
    assert labels_of(reader) == [page_label(0), page_label(1)]
    assert any('XRefStm' in r.getMessage() for r in caplog.records)


# -- linearized files ------------------------------------------------------

def linearized(data, object_streams=False, encryption=None):
    pikepdf = require('pikepdf')
    mode = (pikepdf.ObjectStreamMode.generate if object_streams
            else pikepdf.ObjectStreamMode.disable)
    kw = {'encryption': encryption} if encryption is not None else {}
    with pikepdf.open(io.BytesIO(data)) as pdf:
        out = io.BytesIO()
        pdf.save(out, linearize=True, static_id=True,
                 object_stream_mode=mode, **kw)
    return out.getvalue()


@pytest.mark.parametrize('object_streams', [False, True])
def test_linearized(object_streams):
    """qpdf's linearized output: a first-page section at the front whose
    /Prev is the main section at the end."""
    expected = [page_label(i) for i in range(4)]
    data = linearized(make_pdf(4), object_streams)
    assert_valid(data, texts=expected)
    assert labels_of(read(data)) == expected


def encrypted_linearized(object_streams=False):
    pikepdf = require('pikepdf')
    return linearized(make_pdf(3), object_streams,
                      pikepdf.Encryption(user='', owner='owner', R=4,
                                         aes=True))


def test_encrypt_from_newest_trailer(monkeypatch):
    """In a linearized file the oldest trailer has no /Encrypt; pdfrw
    used to take it from there and never decrypt (#179)."""
    data = encrypted_linearized()
    seen = []

    def record(self, source, password, trailer):
        seen.append(trailer.Encrypt)

    monkeypatch.setattr(pdfreader.crypt, 'HAS_CRYPTO', True)
    monkeypatch.setattr(PdfReader, '_parse_encrypt_info', record)
    PdfReader(fdata=data, decrypt=True)
    assert len(seen) == 1
    assert seen[0].Filter == '/Standard'


@pytest.mark.parametrize('object_streams', [False, True])
def test_encrypted_linearized_decrypts(object_streams):
    pytest.importorskip('Crypto')
    expected = [page_label(i) for i in range(3)]
    data = encrypted_linearized(object_streams)
    assert pdfium_page_texts(data) == expected
    assert labels_of(read(data, decrypt=True)) == expected


# -- damaged section chains ------------------------------------------------

def test_prev_loop_does_not_hang(caplog):
    """A /Prev that points back at its own section is read once."""
    builder = PdfBuilder()
    tree = build_pages(builder, 2)
    builder.prev = builder.tell()       # this section's own offset
    builder.xref_table(tree.root_ref)
    with caplog.at_level(logging.WARNING, logger='pdfrw'):
        reader = read(builder.getvalue())
    assert labels_of(reader) == [page_label(0), page_label(1)]
    assert any('loop' in r.getMessage() for r in caplog.records)


def test_objstm_member_missing_from_stream(caplog):
    """An xref entry naming an object its object stream doesn't hold
    warns and leaves the object unresolved, without failing the read."""
    builder = PdfBuilder()
    tree = build_pages(builder, 1, objstm=True)
    stm_num = builder._entries[tree.catalog][1]
    builder._entries[builder.alloc()] = (2, stm_num, 9)
    builder.xref_stream(tree.root_ref)
    with caplog.at_level(logging.WARNING, logger='pdfrw'):
        reader = read(builder.getvalue())
    assert labels_of(reader) == [page_label(0)]
    assert any('is not in object stream' in r.getMessage()
               for r in caplog.records)


# -- exceptions the xref table parser must not swallow (upstream PR #256) --

class _InterruptedFdata(str):
    """File data whose search is interrupted, as by Ctrl-C."""

    def rindex(self, *args):
        raise KeyboardInterrupt


class _XrefSource(object):
    """Just enough of PdfTokens for parse_xref_table."""

    def __init__(self, tokens, fdata=''):
        self.tokens = iter(tokens)
        self.fdata = fdata
        self.floc = 0

    def next(self):
        tok = next(self.tokens)
        if isinstance(tok, BaseException):
            raise tok
        return tok

    def exception(self, *args):
        raise AssertionError('error path reached: %r' % (args,))


@pytest.mark.parametrize('tokens, fdata', [
    # interrupted while reading the well-formed table
    (['0', '1', KeyboardInterrupt()], ''),
    # table malformed, then interrupted while trying to recover it
    (['0', '1', '0', '65535', 'x'], _InterruptedFdata('')),
])
def test_xref_table_does_not_swallow_keyboard_interrupt(tokens, fdata):
    """KeyboardInterrupt (and SystemExit) reach the caller instead of
    being taken for a badly formatted table."""
    reader = read(make_pdf(1))
    with pytest.raises(KeyboardInterrupt):
        reader.parse_xref_table(_XrefSource(tokens, fdata))
