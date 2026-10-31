# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Tests of the test harness: tests/pdfgen.py checked by tests/validate.py.

A generated "valid" file must satisfy qpdf, pypdf and PDFium; each
deliberate defect must be one that at least one of them notices.  The
last test writes a generated file back out with pdfrw and validates the
result, the pattern later regression tests follow.
"""

import io
import re
import zlib

import pytest

from . import pdfgen
from .pdfgen import PdfBuilder, make_pdf, make_updated_pdf, page_label
from .validate import (assert_valid, pikepdf_problems, pypdf_page_count,
                       pdfium_page_texts, require)


def labels(n):
    return [page_label(i) for i in range(n)]


VALID_LAYOUTS = [
    ('table', False),
    ('stream', False),
    ('stream', True),
    ('hybrid', False),
    ('hybrid', True),
]


@pytest.mark.parametrize('xref, objstm', VALID_LAYOUTS)
@pytest.mark.parametrize('compress', [False, True])
def test_layouts_are_valid(xref, objstm, compress):
    data = make_pdf(4, xref=xref, objstm=objstm, compress=compress)
    assert_valid(data, texts=labels(4))


@pytest.mark.parametrize('xref, objstm', VALID_LAYOUTS)
def test_output_is_deterministic(xref, objstm):
    assert make_pdf(3, xref=xref, objstm=objstm) == \
        make_pdf(3, xref=xref, objstm=objstm)


def test_table_offsets_are_exact():
    data = make_pdf(5)
    table = data[data.rindex(b'\nxref\n') + 1:data.rindex(b'trailer')]
    lines = table.split(b'\n')[1:]
    num = None
    checked = 0
    for line in lines:
        fields = line.split()
        if len(fields) == 2:
            num = int(fields[0])
            continue
        if len(fields) == 3:
            offset, gen, kind = int(fields[0]), int(fields[1]), fields[2]
            assert len(line) == 19 and line.endswith(b'\r'), repr(line)
            if kind == b'n':
                assert data[offset:].startswith(b'%d %d obj\n' % (num, gen))
                checked += 1
            num += 1
    assert checked == 3 + 2 * 5     # catalog, pages, font, 5 x (page+content)
    startxref = int(data.split(b'startxref\n')[-1].split()[0])
    assert data[startxref:].startswith(b'xref\n')


def test_custom_labels_and_escaping():
    texts = ['(paren) \\ back', 'second']
    assert_valid(make_pdf(2, labels=texts), texts=texts)


def test_objstm_needs_xref_stream():
    with pytest.raises(ValueError):
        make_pdf(2, xref='table', objstm=True)
    builder = PdfBuilder()
    builder.objstm([(None, b'<< >>')])
    with pytest.raises(ValueError):
        builder.xref_table()


@pytest.mark.parametrize('xref, objstm, update_xref, update_objstm', [
    ('table', False, 'table', False),
    ('stream', True, 'stream', False),
    ('stream', True, 'stream', True),
    ('hybrid', True, 'table', False),
    ('table', False, 'stream', True),
])
def test_incremental_update(xref, objstm, update_xref, update_objstm):
    data = make_updated_pdf(5, keep=[0, 2, 4], xref=xref, objstm=objstm,
                            update_xref=update_xref,
                            update_objstm=update_objstm)
    assert data.count(b'%%EOF') == 2
    assert b'/Prev ' in data
    assert_valid(data, texts=['Page 1', 'Page 3', 'Page 5'])


def test_dangling_kid_is_noticed():
    data = make_pdf(3, dangling_kids=1)
    assert pikepdf_problems(data), 'qpdf should complain about the kid'
    # PDFium skips the missing kid and shows the three real pages.
    assert pdfium_page_texts(data) == labels(3)


def test_untyped_pages_node_is_noticed():
    data = make_pdf(3, untyped_pages=True)
    assert b'/Type /Pages' not in data
    assert any('/Type' in p for p in pikepdf_problems(data))
    assert pdfium_page_texts(data) == labels(3)


def test_truncation_is_noticed():
    data = make_pdf(3)
    assert pikepdf_problems(pdfgen.truncate(data, -60))
    assert pdfgen.truncate(data, 100) == data[:100]


def test_missing_eof_is_noticed():
    data = pdfgen.strip_eof(make_pdf(3))
    assert not data.rstrip().endswith(b'%%EOF')
    pypdf = require('pypdf')
    with pytest.raises(pypdf.errors.PdfReadError):
        pypdf_page_count(data)


def test_junk_prefix_is_noticed():
    data = pdfgen.junk_prefix(make_pdf(3))
    assert not data.startswith(b'%PDF-')
    pypdf = require('pypdf')
    with pytest.raises(pypdf.errors.PdfReadError):
        pypdf_page_count(data)
    assert pdfium_page_texts(data) == labels(3)


def test_junk_suffix():
    data = pdfgen.junk_suffix(make_pdf(3))
    assert not data.rstrip().endswith(b'%%EOF')
    assert pdfium_page_texts(data) == labels(3)


def test_wrong_stream_length_is_noticed():
    builder = PdfBuilder()
    tree = pdfgen.build_pages(builder, 1)
    builder.stream(b'0123456789', length=500)
    builder.xref_table(tree.root_ref)
    assert pikepdf_problems(builder.getvalue())


def test_free_entry_in_update():
    builder = PdfBuilder()
    tree = pdfgen.build_pages(builder, 2)
    extra = builder.obj(b'(scratch)')
    builder.xref_table(tree.root_ref)
    builder.free(extra)
    builder.xref_table(tree.root_ref)
    data = builder.getvalue()
    assert re.search(rb'%d 1\n0000000000 00001 f\r\n' % extra, data)
    assert_valid(data, texts=labels(2))


def test_xref_stream_is_flate_encoded_with_index():
    data = make_pdf(2, xref='stream', objstm=True)
    match = re.search(rb'/Type /XRef /W \[1 4 2\] /Index \[([\d ]+)\]', data)
    assert match
    start = data.index(b'stream\n', match.end()) + len(b'stream\n')
    end = data.index(b'\nendstream', start)
    rows = zlib.decompress(data[start:end])
    assert len(rows) % 7 == 0
    assert 2 in rows[::7]           # some entries point into the ObjStm


@pytest.mark.parametrize('R, aes', [(2, False), (3, False), (4, False),
                                    (4, True), (6, True)])
def test_encrypt_empty_user_password(R, aes):
    data = pdfgen.encrypt(make_pdf(2), R=R, aes=aes)
    assert b'/Encrypt' in data
    assert_valid(data, texts=labels(2))


def test_encrypt_with_user_password_and_object_streams():
    data = pdfgen.encrypt(make_pdf(2), user='secret', object_streams=True)
    assert b'/ObjStm' in data
    assert pikepdf_problems(data, password='secret') == []
    assert pdfium_page_texts(data, password='secret') == labels(2)


@pytest.mark.parametrize('xref, objstm', [('table', False),
                                          ('stream', True)])
def test_pdfrw_write_back_is_valid(xref, objstm):
    from pdfrw import PdfReader, PdfWriter
    reader = PdfReader(fdata=make_pdf(3, xref=xref, objstm=objstm))
    out = io.BytesIO()
    PdfWriter(out, trailer=reader).write()
    assert_valid(out.getvalue(), texts=labels(3))
