# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""PdfReader's ways of taking input, on generated PDFs.

Upstream ran these on a file from the external static_pdfs corpus; they
now build their input with tests/pdfgen.py.
"""

import io

import pytest

from pdfrw import PdfReader

from .pdfgen import make_pdf, page_label

NPAGES = 3


@pytest.fixture
def pdf_bytes():
    return make_pdf(NPAGES)


def page_labels(reader):
    """The text each page draws, read back from its content stream."""
    labels = []
    for page in reader.pages:
        stream = page.Contents.stream
        labels.append(stream[stream.index('(') + 1:stream.index(')')])
    return labels


EXPECTED = [page_label(i) for i in range(NPAGES)]


def test_fname_binary_filelike(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert page_labels(reader) == EXPECTED


def test_fname_real_file(pdf_bytes, pdf_path):
    path = pdf_path(pdf_bytes)
    with open(path, 'rb') as pdf_file:
        reader = PdfReader(pdf_file)
    assert page_labels(reader) == EXPECTED


def test_fname_path_string(pdf_bytes, pdf_path):
    reader = PdfReader(str(pdf_path(pdf_bytes)))
    assert page_labels(reader) == EXPECTED


def test_fdata_binary(pdf_bytes):
    reader = PdfReader(fdata=pdf_bytes)
    assert page_labels(reader) == EXPECTED


@pytest.mark.parametrize('xref, objstm', [
    ('table', False),
    ('stream', False),
    ('stream', True),
])
def test_xref_kinds(xref, objstm):
    reader = PdfReader(fdata=make_pdf(NPAGES, xref=xref, objstm=objstm))
    assert page_labels(reader) == EXPECTED


def test_unreadable_path_raises(tmp_path):
    from pdfrw import PdfParseError
    with pytest.raises(PdfParseError):
        PdfReader(str(tmp_path / 'missing.pdf'))
