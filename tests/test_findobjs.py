# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""find_objects and page_per_xobj (pdfrw/findobjs.py)."""

from pdfrw import PdfDict, PdfName
from pdfrw.findobjs import find_objects, page_per_xobj


def image(width=40, height=20):
    xobj = PdfDict(Type=PdfName.XObject, Subtype=PdfName.Image,
                   Width=width, Height=height, BitsPerComponent=8,
                   ColorSpace=PdfName.DeviceGray)
    xobj.stream = '\0' * (width * height)
    return xobj


def form():
    xobj = PdfDict(Type=PdfName.XObject, Subtype=PdfName.Form,
                   BBox=[0, 0, 10, 10], Resources=PdfDict())
    xobj.stream = '0 0 10 10 re f'
    return xobj


def page_with(**xobjects):
    return PdfDict(Type=PdfName.Page,
                   Resources=PdfDict(XObject=PdfDict(**xobjects)))


def test_find_objects_finds_forms_and_images():
    img, frm = image(), form()
    found = list(find_objects([page_with(Im1=img, Fm1=frm)]))
    assert sorted(map(id, found)) == sorted([id(img), id(frm)])


def test_image_only_keeps_images():
    # #152: a PdfName.IMage typo meant image_only matched nothing.
    img = image()
    pages = list(page_per_xobj([page_with(Im1=img, Fm1=form())],
                               image_only=True))
    assert len(pages) == 1
    assert pages[0].Resources.XObject.MyImage is img
    assert [float(v) for v in pages[0].MediaBox] == [0, 0, 612, 306]


def test_without_image_only_wraps_both():
    pages = list(page_per_xobj([page_with(Im1=image(), Fm1=form())]))
    assert len(pages) == 2
