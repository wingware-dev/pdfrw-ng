# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""PdfName encoding tests: a '#' in a name must be written as #23."""

import copy
import io
import pickle

import pytest

from pdfrw import PdfReader, PdfWriter, PdfName, PdfObject

from .pdfgen import make_pdf, page_label
from .validate import assert_valid, require


@pytest.mark.parametrize('name, encoded', [
    ('A#41', '/A#2341'),
    ('#', '/#23'),
    ('A #B', '/A#20#23B'),
    ('C#', '/C#23'),
])
def test_hash_is_escaped(name, encoded):
    n = PdfName(name)
    assert n == '/' + name
    assert n.encoded == encoded


@pytest.mark.parametrize('encoded, name', [
    ('/A#2341', '/A#41'),
    ('/A#23B', '/A#B'),
    ('/A#20B', '/A B'),
])
def test_names_from_files_decode(encoded, name):
    n = type(PdfName.X)(encoded)          # pre_encoded, as the reader does
    assert n == name
    assert n.encoded == encoded


def test_plain_names_unchanged():
    assert PdfName.Type.encoded is None
    assert PdfName('A B').encoded == '/A#20B'


@pytest.mark.parametrize('name', ['A#41', 'A #B'])
def test_copy_and_pickle_keep_hash_names(name):
    n = PdfName(name)
    for other in (copy.deepcopy(n), pickle.loads(pickle.dumps(n))):
        assert other == n
        assert other.encoded == n.encoded


NAMES = ['A#41', 'Odd#Name', '#23']


def test_hash_names_survive_writing():
    reader = PdfReader(fdata=make_pdf(1))
    page = reader.pages[0]
    for index, name in enumerate(NAMES):
        page[PdfName(name)] = PdfObject(str(index))
    out = io.BytesIO()
    PdfWriter(out, trailer=reader).write()
    data = out.getvalue()
    assert b'/A#2341 0' in data
    assert_valid(data, texts=[page_label(0)])

    pikepdf = require('pikepdf')
    with pikepdf.open(io.BytesIO(data)) as pdf:
        obj = pdf.pages[0].obj
        for index, name in enumerate(NAMES):
            assert int(obj['/' + name]) == index
        assert '/AA' not in obj

    back = PdfReader(fdata=data).pages[0]
    for index, name in enumerate(NAMES):
        assert back[PdfName(name)] == str(index)
