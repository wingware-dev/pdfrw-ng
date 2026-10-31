# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Flate compression of streams (pdfrw/compress.py).

Round trips are checked with pikepdf (qpdf), which decodes each stream
independently of pdfrw.
"""

import io
import random

import pytest

from pdfrw import PdfArray, PdfDict, PdfName, PdfReader, PdfWriter
from pdfrw.compress import compress
from pdfrw.uncompress import uncompress

from .pdfgen import make_pdf, page_content, page_label
from .validate import assert_valid, require

TEXT = 'BT /F1 12 Tf 72 720 Td (repeated text) Tj ET\n' * 40


def stream(data, **kw):
    return PdfDict(stream=data, **kw)


def pikepdf_streams(data):
    """Each page's content stream as (Filter, decoded bytes), via qpdf."""
    pikepdf = require('pikepdf')
    with pikepdf.open(io.BytesIO(data)) as pdf:
        result = []
        for page in pdf.pages:
            contents = page.obj.Contents
            result.append((str(contents.get('/Filter')),
                           contents.read_bytes()))
        return result


def test_compresses_plain_stream():
    obj = stream(TEXT)
    compress([obj])
    assert obj.Filter == PdfName.FlateDecode
    assert int(obj.Length) == len(obj.stream) < len(TEXT)
    assert uncompress([obj])
    assert obj.stream == TEXT


def test_clears_decodeparms():
    obj = stream(TEXT, DecodeParms=PdfDict(Predictor=1))
    compress([obj])
    assert obj.Filter == PdfName.FlateDecode
    assert obj.DecodeParms is None


def test_leaves_filtered_streams_alone():
    obj = stream('not really hex', Filter=PdfName.ASCIIHexDecode)
    compress([obj])
    assert obj.Filter == PdfName.ASCIIHexDecode
    assert obj.stream == 'not really hex'


def test_skips_objects_without_streams():
    plain = PdfDict(Type=PdfName.Font)
    array = PdfArray([1, 2])
    obj = stream(TEXT)
    compress([plain, array, 5, obj])
    assert plain == PdfDict(Type=PdfName.Font)
    assert obj.Filter == PdfName.FlateDecode


def test_keeps_binary_bytes():
    data = ''.join(chr(i) for i in range(256)) * 8
    obj = stream(data)
    compress([obj])
    assert obj.Filter == PdfName.FlateDecode
    assert uncompress([obj])
    assert obj.stream == data


def test_incompressible_stream_left_uncompressed():
    # Random data grows under zlib; past the 30-byte allowance it is
    # better left as it is.
    data = random.Random(0).randbytes(200000).decode('latin-1')
    obj = stream(data)
    compress([obj])
    assert obj.Filter is None
    assert obj.stream == data


def test_small_growth_is_allowed():
    # A short stream compresses to slightly more bytes; up to 30 more
    # are accepted.
    obj = stream('q Q')
    compress([obj])
    assert obj.Filter == PdfName.FlateDecode


@pytest.mark.parametrize('xref', ['table', 'stream'])
def test_writer_compress_round_trip(xref):
    source = make_pdf(3, xref=xref)
    pages = PdfReader(io.BytesIO(source)).pages
    writer = PdfWriter(compress=True)
    writer.addpages(pages)
    out = io.BytesIO()
    writer.write(out)
    data = out.getvalue()

    assert_valid(data, texts=[page_label(i) for i in range(3)])
    found = pikepdf_streams(data)
    assert [f for f, _ in found] == ['/FlateDecode'] * 3
    assert [d for _, d in found] == [page_content(page_label(i))
                                     for i in range(3)]


def test_writer_without_compress_leaves_streams():
    pages = PdfReader(io.BytesIO(make_pdf(1))).pages
    writer = PdfWriter()
    writer.addpages(pages)
    out = io.BytesIO()
    writer.write(out)
    (filt, data), = pikepdf_streams(out.getvalue())
    assert filt == 'None'
    assert data == page_content(page_label(0))


def test_reader_reads_back_compressed_output():
    pages = PdfReader(io.BytesIO(make_pdf(2))).pages
    writer = PdfWriter(compress=True)
    writer.addpages(pages)
    out = io.BytesIO()
    writer.write(out)
    again = PdfReader(io.BytesIO(out.getvalue()), decompress=True)
    assert [p.Contents.stream for p in again.pages] == [
        page_content(page_label(i)).decode('latin-1') for i in range(2)]
