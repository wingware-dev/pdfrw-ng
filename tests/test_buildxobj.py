# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Form XObjects built from pages (pdfrw/buildxobj.py).

Each XObject is drawn on a new page, written with PdfWriter, and
rendered with PDFium, so the checks are on what a viewer shows: which
parts of the source page appear, and where.
"""

import io
import logging

import pytest

from pdfrw import PdfReader, PdfName
from pdfrw.buildxobj import (CacheXObj, ViewInfo, docxobj, get_rotation,
                             getrects, pagexobj, rotate_point, rotate_rect)
from pdfrw.errors import PdfNotImplementedError
from pdfrw.uncompress import uncompress

from .pdfgen import make_pdf, page_label
from .render import drawing_pdf, inked, render, write_pages, xobj_page
from .validate import assert_valid, pdfium_page_texts, pikepdf_problems

WIDTH, HEIGHT = 612, 792
TOP_LEFT = (0, 396, 306, 396)          # x, y, w, h
BOTTOM_RIGHT = (306, 0, 306, 396)
QUADRANTS = [TOP_LEFT, BOTTOM_RIGHT]


def reader(data):
    return PdfReader(io.BytesIO(data))


def quadrant_page(**kw):
    """A page inked in its top-left and bottom-right quadrants."""
    return reader(drawing_pdf([QUADRANTS], **kw)).pages[0]


def draw(xobj, mediabox=(0, 0, WIDTH, HEIGHT), ops=b'/X Do'):
    """Render `xobj` on a new page; also check qpdf accepts the file."""
    data = write_pages([xobj_page(xobj, mediabox, ops)])
    assert not pikepdf_problems(data)
    return render(data)


def ink_map(image, points):
    return [inked(image, x, y) for x, y in points]


# Centres of the four quadrants of a 612 x 792 page.
TL, TR, BL, BR = (153, 594), (459, 594), (153, 198), (459, 198)


# -- ViewInfo ------------------------------------------------------------

def test_viewinfo_parses_uri():
    info = ViewInfo('doc.pdf#page=2&viewrect=10,20,30.5,40&rotate=90')
    assert info.docname == 'doc.pdf'
    assert info.page == 2
    assert info.viewrect == [10.0, 20.0, 30.5, 40.0]
    assert info.rotate == 90


def test_viewinfo_without_docname():
    info = ViewInfo('page=3')
    assert info.docname is None
    assert info.page == 3
    assert ViewInfo('viewrect=0 0 1 1').viewrect == [0, 0, 1, 1]


def test_viewinfo_keywords():
    info = ViewInfo(page=4, cacheable=False)
    assert (info.page, info.cacheable) == (4, False)
    with pytest.raises(AssertionError):
        ViewInfo(nosuchoption=1)


def test_viewinfo_logs_unknown_option(caplog):
    with caplog.at_level(logging.ERROR, logger='pdfrw'):
        info = ViewInfo('doc.pdf#zoom=200')
    assert 'Unknown option: zoom' in caplog.text
    assert info.docname == 'doc.pdf'


# -- geometry ------------------------------------------------------------

@pytest.mark.parametrize('rotate, expected', [
    (0, 0), (90, 1), ('180', 2), (270, 3), (45, 0), (None, 0),
    ('bogus', 0)])
def test_get_rotation(rotate, expected):
    assert get_rotation(rotate) == expected


def test_rotate_point_clockwise():
    assert rotate_point((1, 2), 0) == (1, 2)
    assert rotate_point((1, 2), 1) == (2, -1)
    assert rotate_point((1, 2), 2) == (-1, -2)
    assert rotate_point((1, 2), 3) == (-2, 1)


def test_rotate_rect_normalizes():
    assert rotate_rect((0, 0, 612, 792), 1) == (0, -612, 792, 0)
    assert rotate_rect((0, 0, 612, 792), 2) == (-612, -792, 0, 0)


def test_getrects_uses_cropbox():
    page = quadrant_page(cropbox=(10, 20, 300, 400))
    mbox, cbox = getrects(page.inheritable, ViewInfo(), 0)
    assert mbox == (0, 0, WIDTH, HEIGHT)
    assert cbox == (10, 20, 300, 400)


def test_getrects_viewrect_is_from_top_left():
    page = quadrant_page()
    _, cbox = getrects(page.inheritable, ViewInfo(viewrect=[0, 0, 306, 396]),
                       0)
    assert cbox == (0, 396, 306, 792)


def test_getrects_fractional_viewrect():
    page = quadrant_page()
    info = ViewInfo(viewrect=[0, 0, 0.5, 0.25])
    _, cbox = getrects(page.inheritable, info, 0)
    assert cbox == (0, 594, 306, 792)


def test_getrects_fractional_viewrect_all_equal():
    # The bottom-right quadrant as fractions was taken as a box half a
    # point wide, because all four numbers are equal.
    page = quadrant_page()
    info = ViewInfo(viewrect=[0.5, 0.5, 0.5, 0.5])
    _, cbox = getrects(page.inheritable, info, 0)
    assert cbox == (306, 0, 612, 396)


def test_getrects_viewrect_clipped_to_page():
    page = quadrant_page()
    info = ViewInfo(viewrect=[500, -50, 400, 100])
    _, cbox = getrects(page.inheritable, info, 0)
    assert cbox == (500, 742, 612, 792)


# -- pagexobj ------------------------------------------------------------

def test_full_page_xobject_renders_like_the_page():
    xobj = pagexobj(quadrant_page())
    assert xobj.Type == PdfName.XObject and xobj.Subtype == PdfName.Form
    assert list(xobj.BBox) == [0, 0, WIDTH, HEIGHT]
    assert (xobj.x, xobj.y, xobj.w, xobj.h) == (0, 0, WIDTH, HEIGHT)
    image = draw(xobj)
    assert ink_map(image, [TL, TR, BL, BR]) == [True, False, False, True]


def test_text_page_xobject_keeps_its_text():
    page = reader(make_pdf(2, compress=True)).pages[1]
    data = write_pages([xobj_page(pagexobj(page))])
    assert_valid(data, texts=[page_label(1)])


def test_viewrect_clips_to_the_view():
    xobj = pagexobj(quadrant_page(), ViewInfo('viewrect=0,0,612,396'))
    assert list(xobj.BBox) == [0, 396, WIDTH, HEIGHT]
    assert (xobj.w, xobj.h) == (WIDTH, 396)
    # The subpage draws the full page through a nested XObject.
    assert xobj.stream.strip() == '/FullPage Do'
    assert xobj.Resources.XObject.FullPage.BBox == [0, 0, WIDTH, HEIGHT]
    image = draw(xobj)
    # Top half kept, bottom-right quadrant clipped away.
    assert ink_map(image, [TL, TR, BL, BR]) == [True, False, False, False]


def test_viewrect_moved_into_place():
    # Show only the bottom-right quadrant, moved to the page's origin.
    xobj = pagexobj(quadrant_page(), ViewInfo(viewrect=[0.5, 0.5, 0.5, 0.5]))
    ops = b'1 0 0 1 %g %g cm /X Do' % (-xobj.x, -xobj.y)
    image = draw(xobj, mediabox=(0, 0, xobj.w, xobj.h), ops=ops)
    assert image.size == (306, 396)
    assert inked(image, 153, 198)


@pytest.mark.parametrize('rotate', [90, 180, 270])
def test_rotated_page_renders_as_viewers_show_it(rotate):
    data = drawing_pdf([QUADRANTS], rotate=rotate)
    original = render(data)
    xobj = pagexobj(reader(data).pages[0])
    assert xobj.Matrix is not None
    assert (xobj.w, xobj.h) == original.size
    ops = b'1 0 0 1 %g %g cm /X Do' % (-xobj.x, -xobj.y)
    image = draw(xobj, mediabox=(0, 0, xobj.w, xobj.h), ops=ops)
    w, h = image.size
    points = [(w / 4, h / 4), (3 * w / 4, h / 4),
              (w / 4, 3 * h / 4), (3 * w / 4, 3 * h / 4)]
    assert ink_map(image, points) == ink_map(original, points)
    assert ink_map(image, points).count(True) == 2


def test_viewinfo_rotate_adds_to_page_rotation():
    page = reader(drawing_pdf([QUADRANTS], rotate=90)).pages[0]
    xobj = pagexobj(page, ViewInfo(rotate=90, cacheable=False))
    # 90 + 90 degrees: drawn upside down.
    assert list(xobj.Matrix) == [-1, 0, 0, -1, 0, 0]


def test_cacheable_xobjects_are_shared():
    page = quadrant_page()
    assert pagexobj(page) is pagexobj(page)
    assert pagexobj(page, ViewInfo(cacheable=False)) is not pagexobj(page)


def test_uncacheable_view_shares_the_full_page():
    page = quadrant_page()
    one = pagexobj(page, ViewInfo(cacheable=False))
    two = pagexobj(page, ViewInfo(cacheable=False))
    assert one is not two
    assert one.Resources.XObject.FullPage is two.Resources.XObject.FullPage


# -- content arrays and compression -----------------------------------------

def test_content_array_is_joined():
    page = reader(drawing_pdf([QUADRANTS], split=True)).pages[0]
    assert len(page.Contents) == 2
    xobj = pagexobj(page)
    assert xobj.Filter is None
    image = draw(xobj)
    assert ink_map(image, [TL, TR, BL, BR]) == [True, False, False, True]


def test_compressed_content_array_stays_compressed():
    # The joined stream was passed to compress() as a dict, not in a
    # list, so compress() iterated its keys and never compressed it.
    page = reader(drawing_pdf([QUADRANTS], split=True,
                              compress=True)).pages[0]
    xobj = pagexobj(page)
    assert xobj.Filter == PdfName.FlateDecode
    image = draw(xobj)
    assert ink_map(image, [TL, TR, BL, BR]) == [True, False, False, True]
    copy = type(xobj)(xobj)
    assert uncompress([copy])
    assert copy.stream.count(' re f') == 2


def test_compressed_content_array_without_compression():
    page = reader(drawing_pdf([QUADRANTS], split=True,
                              compress=True)).pages[0]
    xobj = pagexobj(page, allow_compressed=False)
    assert xobj.Filter is None
    assert xobj.stream.count(' re f') == 2
    # The source page's own streams are left compressed.
    assert all(c.Filter == PdfName.FlateDecode for c in page.Contents)


def test_single_compressed_stream_decompressed_on_request():
    page = reader(drawing_pdf([QUADRANTS], compress=True)).pages[0]
    assert pagexobj(page).Filter == PdfName.FlateDecode
    page = reader(drawing_pdf([QUADRANTS], compress=True)).pages[0]
    xobj = pagexobj(page, allow_compressed=False)
    assert xobj.Filter is None
    assert page.Contents.Filter == PdfName.FlateDecode
    assert ink_map(draw(xobj), [TL, BR]) == [True, True]


def test_unsupported_filter_refused():
    page = quadrant_page()
    page.Contents.Filter = PdfName.LZWDecode
    with pytest.raises(PdfNotImplementedError):
        pagexobj(page, allow_compressed=False)


# -- docxobj and CacheXObj --------------------------------------------------

@pytest.fixture
def three_pages(pdf_path):
    return str(pdf_path(make_pdf(3, compress=True), 'three.pdf'))


def text_of(xobj):
    data = write_pages([xobj_page(xobj)])
    assert_valid(data, pages=1)
    return pdfium_page_texts(data)[0]


def test_docxobj_reads_named_page(three_pages):
    assert text_of(docxobj(three_pages + '#page=2')) == page_label(1)


def test_docxobj_defaults_to_first_page(three_pages):
    assert text_of(docxobj(three_pages)) == page_label(0)


def test_docxobj_with_doc(three_pages):
    doc = PdfReader(three_pages)
    xobj = docxobj('page=3', doc=doc)
    assert text_of(xobj) == page_label(2)


def test_docxobj_viewinfo_with_doc(three_pages):
    info = ViewInfo(page=2, doc=PdfReader(three_pages))
    assert text_of(docxobj(info)) == page_label(1)


def test_docxobj_uncompressed(three_pages):
    xobj = docxobj(three_pages + '#page=1', allow_compressed=False)
    assert xobj.Filter is None
    assert page_label(0) in xobj.stream


def test_cachexobj_reads_each_file_once(three_pages):
    cache = CacheXObj()
    first = cache.load(three_pages + '#page=1')
    third = cache.load(three_pages + '#page=3')
    assert list(cache.cached_pdfs) == [three_pages]
    assert first.Filter == PdfName.FlateDecode
    data = write_pages([xobj_page(first), xobj_page(third)])
    assert_valid(data, texts=[page_label(0), page_label(2)])


def test_cachexobj_decompress(three_pages):
    xobj = CacheXObj(decompress=True).load(three_pages + '#page=2')
    assert xobj.Filter is None
    assert page_label(1) in xobj.stream
