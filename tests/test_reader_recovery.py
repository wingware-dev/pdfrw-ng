# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""PdfReader on damaged files: bad startxref, /Prev and /Length, missing
%%EOF, junk around the file, broken or missing xref data, truncation.

Upstream raised (PdfParseError, AssertionError, OverflowError, or a bare
StopIteration) on all of these.  Now pdfrw warns and recovers, falling
back to scanning the file for ``N G obj`` headers, and reads the pages
PDFium reads where PDFium can read the file at all.
"""

import io
import logging
import re
import zlib

import pytest

from pdfrw import PdfReader, PdfWriter
from pdfrw.tokens import PdfTokens

from .pdfgen import (PdfBuilder, build_pages, junk_prefix, junk_suffix,
                     make_pdf, make_updated_pdf, page_label, strip_eof,
                     truncate)
from .validate import assert_valid, pdfium_page_texts

LABELS = [page_label(i) for i in range(3)]


def labels_of(reader):
    labels = []
    for page in reader.pages:
        stream = page.Contents.stream
        labels.append(stream[stream.index('(') + 1:stream.index(')')])
    return labels


def read(data, caplog):
    """Read `data` (uncompressed); return the reader and its warnings."""
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger='pdfrw'):
        reader = PdfReader(fdata=data, decompress=True)
    return reader, [r.getMessage() for r in caplog.records]


def reconstructed(warnings):
    return any('Reconstructed cross-reference' in w for w in warnings)


def copy_of(reader):
    out = io.BytesIO()
    PdfWriter(out, trailer=reader).write()
    return out.getvalue()


def replace_number(data, before, value):
    """Replace the number after the last `before` with `value`."""
    match = list(re.finditer(re.escape(before) + rb'\s*(\d+)', data))[-1]
    return data[:match.start(1)] + value + data[match.end(1):]


# -- end of file: %%EOF, NULs, junk (#168, #136) -------------------------

@pytest.mark.parametrize('xref', ['table', 'stream'])
def test_missing_eof(xref, caplog):
    """A missing %%EOF used to be fatal (#168)."""
    data = strip_eof(make_pdf(3, xref=xref))
    assert pdfium_page_texts(data) == LABELS
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert any('EOF mark not found' in w for w in warnings)
    assert not reconstructed(warnings)


def test_trailing_nuls_are_padding(caplog):
    """NUL padding after %%EOF is read without complaint (#136)."""
    data = make_pdf(3) + b'\0' * 2000
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert not any('Extra data' in w for w in warnings)


def test_junk_after_eof(caplog):
    data = junk_suffix(make_pdf(3))
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert any('Extra data' in w for w in warnings)


# -- junk before the header (#242) ---------------------------------------

@pytest.mark.parametrize('xref, objstm', [
    ('table', False), ('stream', True), ('hybrid', True)])
def test_junk_before_header(xref, objstm, caplog):
    """Offsets written before the junk was prepended count from the
    header; pdfrw used to fail to find the xref (#242)."""
    data = junk_prefix(make_pdf(3, xref=xref, objstm=objstm))
    assert pdfium_page_texts(data) == LABELS
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert any('header not at beginning' in w for w in warnings)
    assert not reconstructed(warnings)
    assert_valid(copy_of(reader), texts=LABELS)


def test_junk_before_header_counted_in_offsets(caplog):
    """A writer that counts the junk in its offsets: the xref does not
    parse at the header-relative offset, so it is reconstructed."""
    builder = PdfBuilder(header=b'junk line\n%PDF-1.7\n%\xe2\xe3\xcf\xd3\n')
    tree = build_pages(builder, 3)
    builder.xref_table(tree.root_ref)
    data = builder.getvalue()
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert reconstructed(warnings)


# -- startxref (#210, #211) ----------------------------------------------

def test_startxref_glued_to_number(caplog):
    """'startxref869' as one token tripped an assert (#211)."""
    data = make_pdf(3).replace(b'startxref\n', b'startxref')
    assert pdfium_page_texts(data) == LABELS
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert not reconstructed(warnings)


def test_startxref_word_without_number_is_skipped(caplog):
    """A later 'startxref' with no number does not hide the real one."""
    data = make_pdf(3) + b'% startxref\n'
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert not reconstructed(warnings)


@pytest.mark.parametrize('value', [
    b'99999999999999999999',            # OverflowError upstream (#210)
    b'9' * 400,
    b'999999',                          # past the end of the file
    b'0',                               # the header, not an xref
    b'100',                             # inside an object
])
def test_bad_startxref(value, caplog):
    data = replace_number(make_pdf(3), b'startxref', value)
    assert pdfium_page_texts(data) == LABELS
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert reconstructed(warnings)
    assert_valid(copy_of(reader), texts=LABELS)


@pytest.mark.parametrize('xref', ['table', 'stream'])
def test_no_xref_at_all(xref, caplog):
    """Everything after the last object cut off: no xref, trailer,
    startxref or %%EOF.  The catalog is found by scanning."""
    data = make_pdf(3, xref=xref)
    cut = data.rfind(b'endobj') + len(b'endobj\n')
    if xref == 'stream':
        # The last object is the xref stream itself; cut before it.
        cut = data.rfind(b'endobj', 0, data.rfind(b'/Type /XRef'))
        cut += len(b'endobj\n')
    data = data[:cut]
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert any('using the catalog' in w for w in warnings)
    assert_valid(copy_of(reader), texts=LABELS)


# -- /Prev ---------------------------------------------------------------

@pytest.mark.parametrize('value', [
    b'99999999999999999999999', b'999999', b'0'])
def test_bad_prev(value, caplog):
    """The update is read from its xref, and the older revision's
    objects from a scan, so the update's 2 pages survive."""
    data = make_updated_pdf(3, [0, 1])
    data = replace_number(data, b'/Prev', value)
    expected = LABELS[:2]
    assert pdfium_page_texts(data) == expected
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == expected
    assert any('/Prev' in w for w in warnings)
    assert reconstructed(warnings)


def test_prev_not_a_number(caplog):
    data = make_updated_pdf(3, [0, 1])
    match = re.search(rb'/Prev (\d+)', data)
    data = data[:match.start(1)] + b'/X' + data[match.end(1):]
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS[:2]
    assert any('/Prev' in w for w in warnings)


# -- broken xref data ----------------------------------------------------

def test_garbage_xref_table(caplog):
    data = make_pdf(3)
    start = data.index(b'xref\n') + len(b'xref\n')
    end = data.index(b'trailer')
    data = data[:start] + b'#' * (end - start) + data[end:]
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert reconstructed(warnings)


def test_corrupt_xref_stream_with_object_streams(caplog):
    """With the xref stream unreadable, the pages live only in an
    object stream: the scan reads its header to find them."""
    data = make_pdf(3, xref='stream', objstm=True)
    marker = data.rindex(b'/Type /XRef')
    start = data.index(b'stream\n', marker) + len(b'stream\n')
    end = data.index(b'\nendstream', start)
    data = data[:start] + b'\xff' * (end - start) + data[end:]
    with pytest.raises(zlib.error):
        zlib.decompress(data[start:end])
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert reconstructed(warnings)
    assert_valid(copy_of(reader), texts=LABELS)


def test_reconstruction_prefers_newest_copy(caplog):
    """Two revisions, xref broken: the later copy of /Pages wins."""
    data = make_updated_pdf(3, [2, 0])
    data = replace_number(data, b'startxref', b'5')
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == [LABELS[2], LABELS[0]]
    assert reconstructed(warnings)


# -- truncation (#145) ---------------------------------------------------

def test_truncated_after_objects(caplog):
    """Cut inside the xref table: rebuilt from the objects."""
    data = truncate(make_pdf(3), -40)
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert reconstructed(warnings)


def test_truncated_object_costs_only_itself(caplog):
    """The last page's dictionary is cut off by the end of the file: the
    other pages are read, and the error is logged, not raised (#145)."""
    data = make_pdf(3)
    last = data.rindex(b'/Type /Page ')
    data = data[:last + 30]
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS[:2]
    assert any('Could not read PDF object' in r.getMessage()
               for r in caplog.records)


# -- stream /Length (#199) -----------------------------------------------

def file_with_extra_stream(data=b'hello world', **stream_kw):
    builder = PdfBuilder()
    tree = build_pages(builder, 2)
    extra = builder.stream(data, **stream_kw)
    builder.xref_table(tree.root_ref + b' /Extra %d 0 R' % extra)
    return builder.getvalue()


@pytest.mark.parametrize('length', [999999, 10 ** 30])
def test_length_past_eof(length, caplog):
    """A /Length running past the end of the file used to raise (#199);
    the stream ends at its endstream instead."""
    data = file_with_extra_stream(length=length)
    reader, _ = read(data, caplog)
    assert reader.Extra.stream == 'hello world'
    assert int(reader.Extra.Length) == len('hello world')
    assert labels_of(reader) == LABELS[:2]


def test_length_past_eof_on_page_content(caplog):
    builder = PdfBuilder()
    tree = build_pages(builder, 3)
    builder.xref_table(tree.root_ref)
    data = builder.getvalue()
    # Make the last content stream's /Length huge, keeping the offsets.
    content = b'%d 0 obj\n<< /Length ' % tree.content_nums[-1]
    start = data.index(content) + len(content)
    end = data.index(b' >>', start)
    data = data[:start] + b'9' * (end - start) + data[end:]
    reader, _ = read(data, caplog)
    assert labels_of(reader) == LABELS


@pytest.mark.parametrize('length', [b'-5', b'/Name', b'77 0 R'])
def test_unusable_length(length, caplog):
    """A negative, non-numeric, or missing indirect /Length."""
    builder = PdfBuilder()
    tree = build_pages(builder, 1)
    extra = builder.obj(b'<< /Length ' + length +
                        b' >>\nstream\nhello world\nendstream')
    builder.xref_table(tree.root_ref + b' /Extra %d 0 R' % extra)
    reader, _ = read(builder.getvalue(), caplog)
    assert reader.Extra.stream == 'hello world'


def test_stream_without_endstream_at_eof(caplog):
    """A content stream cut off by the end of the file (and with it the
    xref): the page keeps what there is of its stream."""
    builder = PdfBuilder()
    tree = build_pages(builder, 1)
    text = b'BT /F1 24 Tf 72 720 Td (Cut off here) Tj ET'
    content = builder.stream(text, num=tree.content_nums[0])
    data = builder.getvalue()
    data = data[:data.rindex(b'(Cut off') + len(b'(Cut off')]
    reader, _ = read(data, caplog)
    assert reader.pages[0].Contents.indirect == (content, 0)
    assert reader.pages[0].Contents.stream.endswith('(Cut off')


# -- tokenizer -----------------------------------------------------------

def test_tokens_end_without_runtime_error():
    """`raise StopIteration` in the generator became RuntimeError on
    Python 3.7+ when comments were kept (tokens.py)."""
    assert list(PdfTokens('1 2 % note', 0, False)) == ['1', '2', '% note']
    assert list(PdfTokens('1 2', 0, True)) == ['1', '2']


def test_tokens_seek_before_first_token():
    source = PdfTokens('10 20 30')
    source.floc = 3
    assert source.next() == '20'


def test_tokens_seek_after_end():
    source = PdfTokens('10 20 30')
    assert list(source) == ['10', '20', '30']
    source.floc = 0
    assert source.next() == '10'
    assert source.multiple(2) == ['20', '30']
    assert source.next_default() == 'nope'
