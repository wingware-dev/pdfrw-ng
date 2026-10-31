# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""RectXObj positioning and scaling (pdfrw/pagemerge.py)."""

import io

import pytest

from pdfrw import PdfReader, PdfWriter, PageMerge
from pdfrw.pagemerge import RectXObj

from .pdfgen import make_pdf, page_label
from .validate import assert_valid

# tests/pdfgen.py pages are US Letter: 612 x 792 points.
WIDTH, HEIGHT = 612, 792


@pytest.fixture
def page():
    return PdfReader(io.BytesIO(make_pdf(1))).pages[0]


def test_initial_size(page):
    rect = RectXObj(page)
    assert (rect.x, rect.y, rect.w, rect.h) == (0, 0, WIDTH, HEIGHT)


def test_set_h_scales_by_height(page):
    # #219: setting h scaled by the width, so h ended up 792 * 396 / 612.
    rect = RectXObj(page)
    rect.h = HEIGHT / 2
    assert rect.h == pytest.approx(HEIGHT / 2)
    assert rect.w == pytest.approx(WIDTH / 2)   # aspect ratio stays locked
    a, b, c, d, e, f = rect.Matrix
    assert (a, d) == (pytest.approx(0.5), pytest.approx(0.5))


def test_set_w_scales_by_width(page):
    rect = RectXObj(page)
    rect.w = WIDTH * 2
    assert rect.w == pytest.approx(WIDTH * 2)
    assert rect.h == pytest.approx(HEIGHT * 2)


def test_set_h_after_move_keeps_position(page):
    rect = RectXObj(page)
    rect.x, rect.y = 10, 20
    rect.h = 100
    assert (rect.x, rect.y) == (10, 20)
    assert rect.h == pytest.approx(100)
    assert rect.box == [10, 20, pytest.approx(10 + WIDTH * 100.0 / HEIGHT),
                        pytest.approx(120)]


def test_resized_rect_survives_a_write(page):
    merge = PageMerge() + page
    merge[0].h = 396
    out = io.BytesIO()
    PdfWriter(out).addpage(merge.render()).write()
    data = out.getvalue()
    assert_valid(data, texts=[page_label(0)])
    reread = PdfReader(io.BytesIO(data)).pages[0]
    assert [float(v) for v in reread.MediaBox] == pytest.approx(
        [0, 0, 306, 396])
