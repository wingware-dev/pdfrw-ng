# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""PdfWriter regression tests.

Each test builds its own PDF and checks what pdfrw writes with
independent tools (qpdf via pikepdf, pypdf, PDFium), not only by reading
it back with pdfrw.
"""

import io
import pickle
import re

import pytest

from pdfrw import PdfReader, PdfWriter, PdfDict, PdfArray, PdfName, \
    PdfString, IndirectPdfDict, PdfObject, Encryption, \
    PdfOutputEncodingError
from pdfrw.errors import PdfParseError, PdfOutputError

from .pdfgen import make_pdf, page_label
from .validate import assert_valid, require

NPAGES = 3
TEXTS = [page_label(i) for i in range(NPAGES)]


def reader():
    return PdfReader(fdata=make_pdf(NPAGES))


def write_bytes(writer=None, trailer=None):
    out = io.BytesIO()
    (writer or PdfWriter()).write(out, trailer=trailer)
    return out.getvalue()


def copied(mutate=None):
    """Copy the generated test file through pdfrw; return the bytes."""
    src = reader()
    if mutate is not None:
        mutate(src)
    return write_bytes(trailer=src)


def test_roundtrip_is_valid():
    data = copied()
    assert_valid(data, texts=TEXTS)


def test_addpages_is_valid(tmp_path):
    path = tmp_path / 'out.pdf'
    PdfWriter(str(path)).addpages(reader().pages).write()
    assert_valid(path.read_bytes(), texts=TEXTS)


# -- #135, #160: a failing write must not damage the target ----------------

def bad_stream(src):
    # Not latin-1, so it cannot be written (#160).
    src.pages[0].Contents.stream = 'BT (☃) Tj ET'


def test_failed_write_keeps_existing_file(tmp_path):
    path = tmp_path / 'out.pdf'
    path.write_bytes(b'original contents')
    src = reader()
    bad_stream(src)
    with pytest.raises(UnicodeEncodeError):
        PdfWriter(str(path), trailer=src).write()
    assert path.read_bytes() == b'original contents'


def test_failed_write_does_not_create_file(tmp_path):
    path = tmp_path / 'out.pdf'
    src = reader()
    bad_stream(src)
    with pytest.raises(UnicodeEncodeError):
        PdfWriter(trailer=src).write(str(path))
    assert not path.exists()


def test_failed_write_leaves_file_object_untouched():
    out = io.BytesIO()
    src = reader()
    bad_stream(src)
    with pytest.raises(UnicodeEncodeError):
        PdfWriter(trailer=src).write(out)
    assert out.getvalue() == b''


# -- #160: a non-latin-1 str names the object it is in ----------------------

def contents_number(src):
    """The object number the writer gives page 1's content stream."""
    src.pages[0].Contents.stream = 'BT (PDFRW-MARKER) Tj ET'
    data = write_bytes(trailer=src).decode('latin-1')
    match = re.search(r'(\d+) 0 obj\n(?:(?!endobj).)*PDFRW-MARKER', data,
                      re.DOTALL)
    return int(match.group(1))


def raises_encoding_error(writer, src):
    with pytest.raises(PdfOutputEncodingError) as info:
        writer.write(io.BytesIO(), trailer=src)
    exc = info.value
    # Old handlers for either exception type still catch it.
    assert isinstance(exc, UnicodeEncodeError)
    assert isinstance(exc, PdfOutputError)
    assert exc.encoding == 'latin-1'
    assert exc.object[exc.start:exc.end] == '☃'
    assert isinstance(exc.__cause__, UnicodeEncodeError)
    message = str(exc)
    assert "'☃' (U+2603)" in message
    assert 'latin-1' in message
    return message


@pytest.mark.parametrize('compress', [False, True])
def test_non_latin1_stream_names_object(compress):
    src = reader()
    num = contents_number(src)
    bad_stream(src)
    message = raises_encoding_error(PdfWriter(compress=compress), src)
    assert message.startswith('Cannot write object %d: its stream ' % num)
    assert "decode('latin-1')" in message


@pytest.mark.parametrize('method', ['rc4-128', 'aes-128', 'aes-256'])
def test_non_latin1_stream_names_object_when_encrypting(method):
    if method != 'rc4-128':
        require('Crypto')
    src = reader()
    bad_stream(src)
    writer = PdfWriter(encrypt=Encryption('user', 'owner', method=method))
    message = raises_encoding_error(writer, src)
    assert re.match(r'Cannot write object \d+: its stream ', message)


def test_non_latin1_name_names_object():
    src = reader()
    src.pages[0][PdfName('Snow☃')] = PdfObject('1')
    message = raises_encoding_error(PdfWriter(), src)
    assert re.match(r'Cannot write object \d+: a name or value in it ',
                    message)


def test_non_latin1_in_trailer():
    src = reader()
    src.Snow = PdfObject('☃')
    message = raises_encoding_error(PdfWriter(), src)
    assert message.startswith('Cannot write the trailer: ')


def test_encoding_error_pickles():
    src = reader()
    bad_stream(src)
    with pytest.raises(PdfOutputEncodingError) as info:
        PdfWriter().write(io.BytesIO(), trailer=src)
    other = pickle.loads(pickle.dumps(info.value))
    assert type(other) is PdfOutputEncodingError
    assert str(other) == str(info.value)
    assert (other.encoding, other.object, other.start, other.end) == \
        (info.value.encoding, info.value.object, info.value.start,
         info.value.end)


def test_bad_key_fails_before_write(tmp_path):
    # #135: a str key added with update() used to make the writer raise
    # mid-write, leaving a 0-byte file.  It now fails at update().
    path = tmp_path / 'out.pdf'
    path.write_bytes(b'original contents')
    src = reader()
    with pytest.raises(PdfParseError):
        src.Info = PdfDict()
        src.Info.update({'Title': PdfString.encode('x')})
    PdfWriter(str(path), trailer=src).write()
    assert_valid(path.read_bytes(), texts=TEXTS)


def test_write_returns_after_success_with_file_object():
    out = io.BytesIO()
    out.write(b'prefix')
    PdfWriter(trailer=reader()).write(out)
    data = out.getvalue()
    assert data.startswith(b'prefix%PDF-')
    assert_valid(data[len(b'prefix'):], texts=TEXTS)


# -- #37, #127: booleans; None as null -------------------------------------

def add_flags(src):
    page = src.pages[0]
    page.PdfrwTrue = True
    page.PdfrwFalse = False
    page.PdfrwArray = PdfArray([True, False, None, 1, 2.5])


def test_booleans_written_as_pdf_booleans():
    data = copied(add_flags)
    assert b'/PdfrwTrue true' in data
    assert b'/PdfrwFalse false' in data
    assert b'[true false null 1 2.5]' in data
    assert_valid(data, texts=TEXTS)

    pikepdf = require('pikepdf')
    with pikepdf.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[0].obj
        # qpdf reads the old 'True' as null (None), so these fail there.
        assert page.PdfrwTrue is True
        assert page.PdfrwFalse is False
        assert list(page.PdfrwArray[:3]) == [True, False, None]

    back = PdfReader(fdata=data).pages[0]
    assert back.PdfrwTrue == 'true'
    assert back.PdfrwFalse == 'false'


# -- #147: CR in literal strings --------------------------------------------

CR_BYTES = b'a\rb\r\nc\n(d)\\e'


def add_cr_title(src):
    src.Info = IndirectPdfDict(
        Title=PdfString.from_bytes(CR_BYTES, bytes_encoding='literal'))


def test_cr_in_literal_string_survives():
    data = copied(add_cr_title)
    assert_valid(data, texts=TEXTS)

    pikepdf = require('pikepdf')
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert bytes(pdf.trailer.Info.Title) == CR_BYTES

    pypdf = require('pypdf')
    info = pypdf.PdfReader(io.BytesIO(data)).trailer['/Info'].get_object()
    assert info['/Title'].get_original_bytes() == CR_BYTES

    assert PdfReader(fdata=data).Info.Title.to_bytes() == CR_BYTES


# -- upstream PR #216: PdfWriter.addpage(page, at_index) ----------------------

def two_writers():
    """A writer holding the 3 generated pages, and a 4th page to add."""
    writer = PdfWriter()
    writer.addpages(reader().pages)
    extra = PdfReader(fdata=make_pdf(1, labels=['Extra'])).pages[0]
    return writer, extra


@pytest.mark.parametrize('at_index, position', [
    (None, 3), (0, 0), (1, 1), (3, 3), (-1, 2), (-3, 0)])
def test_addpage_at_index(at_index, position):
    writer, extra = two_writers()
    assert writer.addpage(extra, at_index=at_index) is writer
    expected = list(TEXTS)
    expected.insert(position, 'Extra')
    assert_valid(write_bytes(writer), texts=expected)


def test_addpage_at_index_after_trailer_built():
    """Inserting after the trailer was built rebuilds it, as appending
    always did."""
    writer, extra = two_writers()
    assert writer.trailer.Root.Pages.Count == '3'
    writer.addpage(extra, at_index=0)
    assert writer.trailer.Root.Pages.Count == '4'
    assert_valid(write_bytes(writer), texts=['Extra'] + TEXTS)


@pytest.mark.parametrize('at_index', [4, -4, 100])
def test_addpage_at_index_out_of_range(at_index):
    writer, extra = two_writers()
    with pytest.raises(IndexError):
        writer.addpage(extra, at_index=at_index)
    assert len(writer.pagearray) == 3
    assert id(extra) not in writer.killobj
    assert_valid(write_bytes(writer), texts=TEXTS)


@pytest.mark.parametrize('at_index', [1.0, '1'])
def test_addpage_at_index_must_be_an_integer(at_index):
    writer, extra = two_writers()
    with pytest.raises(TypeError):
        writer.addpage(extra, at_index=at_index)
    assert len(writer.pagearray) == 3


# -- upstream PR #205: PdfWriter.Pages ----------------------------------------

def bare_page(text):
    """A page with no /MediaBox or /Resources of its own."""
    contents = IndirectPdfDict()
    contents.stream = 'BT /F1 24 Tf 20 100 Td (%s) Tj ET' % text
    return PdfDict(Type=PdfName.Page, Contents=contents)


def shared_pages_node():
    font = IndirectPdfDict(Type=PdfName.Font, Subtype=PdfName.Type1,
                           BaseFont=PdfName.Helvetica)
    return PdfDict(MediaBox=PdfArray([0, 0, 300, 400]),
                   Resources=PdfDict(Font=PdfDict(F1=font)))


def pdfium_sizes(data):
    pdfium = require('pypdfium2')
    doc = pdfium.PdfDocument(data)
    try:
        return [tuple(doc[i].get_size()) for i in range(len(doc))]
    finally:
        doc.close()


@pytest.mark.parametrize('via_constructor', [False, True])
def test_pages_entries_are_inherited(via_constructor):
    """Pages with no /MediaBox or /Resources take them from the /Pages
    node the writer builds from PdfWriter.Pages."""
    node = shared_pages_node()
    if via_constructor:
        writer = PdfWriter(Pages=node)
    else:
        writer = PdfWriter()
        writer.Pages = node
    assert writer.Pages is node
    writer.addpages([bare_page('One'), bare_page('Two')])
    data = write_bytes(writer)
    assert_valid(data, texts=['One', 'Two'])
    assert pdfium_sizes(data) == [(300, 400)] * 2
    root = PdfReader(fdata=data).Root.Pages
    assert root.MediaBox == ['0', '0', '300', '400']
    assert root.Count == '2'


def test_pages_does_not_override_a_page_own_entries():
    writer = PdfWriter(Pages=shared_pages_node())
    writer.addpages(reader().pages)         # 612 x 792, own resources
    writer.addpage(bare_page('Bare'))
    data = write_bytes(writer)
    assert_valid(data, texts=TEXTS + ['Bare'])
    assert pdfium_sizes(data) == [(612, 792)] * 3 + [(300, 400)]


def test_pages_dict_is_copied_not_changed():
    """The writer's own /Type, /Kids and /Count win, any /Parent is
    dropped, and the caller's dictionary is left as it was, so one can
    serve several writers."""
    node = shared_pages_node()
    node.Type = PdfName.Bogus
    node.Kids = PdfArray([bare_page('Stray')])
    node.Count = 7
    node.Parent = PdfDict(Type=PdfName.Pages)
    before = dict(node)
    for texts in (['A'], ['B', 'C']):
        writer = PdfWriter(Pages=node)
        writer.addpages([bare_page(t) for t in texts])
        pages = writer.trailer.Root.Pages
        assert pages is not node and pages.indirect
        assert (pages.Type, pages.Count, pages.Parent) == \
            (PdfName.Pages, str(len(texts)), None)
        assert_valid(write_bytes(writer), texts=texts)
    assert dict(node) == before


def test_pages_set_after_trailer_built_is_used():
    writer = PdfWriter()
    writer.addpage(bare_page('Late'))
    assert writer.trailer.Root.Pages.MediaBox is None
    writer.Pages = shared_pages_node()
    data = write_bytes(writer)
    assert_valid(data, texts=['Late'])
    assert pdfium_sizes(data) == [(300, 400)]


def test_pages_leaves_a_given_trailer_alone():
    src = reader()
    writer = PdfWriter(trailer=src, Pages=shared_pages_node())
    assert writer.trailer is src
    data = write_bytes(writer)
    assert_valid(data, texts=TEXTS)
    assert pdfium_sizes(data) == [(612, 792)] * 3


def test_pages_default_unchanged():
    writer = PdfWriter()
    assert writer.Pages is None
    writer.addpages(reader().pages)
    assert set(writer.trailer.Root.Pages) == {'/Type', '/Count', '/Kids'}


@pytest.mark.parametrize('value', [{'/MediaBox': [0, 0, 1, 1]}, 'x'])
def test_pages_must_be_a_pdfdict(value):
    with pytest.raises(TypeError):
        PdfWriter().Pages = value
