# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""pdfrw pages drawn by reportlab (pdfrw/toreportlab.py).

reportlab writes each file; PDFium renders it and qpdf, pypdf and
PDFium check it, so the checks are on what a viewer shows.
"""

import io

import pytest

from pdfrw import PdfArray, PdfDict, PdfName, PdfReader
from pdfrw.buildxobj import ViewInfo, pagexobj
from pdfrw.objects import PdfString

from .pdfgen import PdfBuilder, make_pdf, page_label
from .render import drawing_pdf, inked, rect_content, render
from .validate import assert_valid, require

WIDTH, HEIGHT = 612, 792
TL, TR, BL, BR = (153, 594), (459, 594), (153, 198), (459, 198)


@pytest.fixture
def rl():
    require('reportlab')
    from pdfrw import toreportlab
    return toreportlab


def canvas(pagesize=(WIDTH, HEIGHT)):
    from reportlab.pdfgen.canvas import Canvas
    out = io.BytesIO()
    return Canvas(out, pagesize=pagesize, pageCompression=0), out


def pages_of(data):
    return PdfReader(io.BytesIO(data)).pages


def test_pages_drawn_as_forms(rl):
    xobjs = [pagexobj(p) for p in pages_of(make_pdf(3, compress=True))]
    canv, out = canvas()
    for xobj in xobjs:
        canv.doForm(rl.makerl(canv, xobj))
        canv.showPage()
    canv.save()
    assert_valid(out.getvalue(), texts=[page_label(i) for i in range(3)])


def test_four_up_placement(rl):
    # Page 1 inks its whole page; drawn at half size in the bottom-left
    # quarter, only that quarter of the output is inked.
    data = drawing_pdf([[(0, 0, WIDTH, HEIGHT)]])
    xobj = pagexobj(pages_of(data)[0])
    canv, out = canvas()
    canv.saveState()
    canv.scale(0.5, 0.5)
    canv.doForm(rl.makerl(canv, xobj))
    canv.restoreState()
    canv.showPage()
    canv.save()
    data = out.getvalue()
    assert_valid(data, pages=1)
    image = render(data)
    assert [inked(image, *p) for p in (TL, TR, BL, BR)] == \
        [False, False, True, False]


def test_viewrect_form_clips(rl):
    # A viewrect gives a BBox of floats and a nested FullPage form.
    data = drawing_pdf([[(0, 396, 306, 396), (306, 0, 306, 396)]])
    xobj = pagexobj(pages_of(data)[0], ViewInfo(viewrect=[0, 0, 0.5, 1]))
    canv, out = canvas()
    canv.doForm(rl.makerl(canv, xobj))
    canv.showPage()
    canv.save()
    data = out.getvalue()
    assert_valid(data, pages=1)
    image = render(data)
    assert [inked(image, *p) for p in (TL, TR, BL, BR)] == \
        [True, False, False, False]


def test_same_object_converted_once_per_document(rl):
    xobj = pagexobj(pages_of(make_pdf(1))[0])
    canv, out = canvas()
    name = rl.makerl(canv, xobj)
    assert rl.makerl(canv, xobj) == name
    # Passing the document instead of the canvas finds the same object.
    assert rl.makerl(canv._doc, xobj) == name
    for _ in range(2):
        canv.doForm(name)
        canv.showPage()
    canv.save()
    data = out.getvalue()
    assert_valid(data, texts=[page_label(0)] * 2)
    pikepdf = require('pikepdf')
    with pikepdf.open(io.BytesIO(data)) as pdf:
        forms = [pdf.pages[i].Resources.XObject for i in range(2)]
        objgens = set(f[k].objgen for f in forms for k in f.keys())
    assert len(objgens) == 1


def test_new_document_gets_new_objects(rl):
    # Multipass reportlab documents build a new doc on each pass.
    xobj = pagexobj(pages_of(make_pdf(1))[0])
    results = []
    for _ in range(2):
        canv, out = canvas()
        canv.doForm(rl.makerl(canv, xobj))
        canv.showPage()
        canv.save()
        results.append(out.getvalue())
        assert_valid(results[-1], texts=[page_label(0)])
    assert len(xobj.derived_rl_obj) == 2


def resource_rich_pdf():
    """A page whose resources hold an indirect array, a literal string
    and an untyped Form XObject that inks the top-left quadrant."""
    b = PdfBuilder()
    catalog, tree, page = b.alloc(), b.alloc(), b.alloc()
    procset = b.obj(b'[/PDF /Text]')
    inner = b.stream(rect_content([(0, 396, 306, 396)]),
                     extra=b'/Subtype /Form /BBox [0 0 612 792]')
    content = b.stream(b'/MC0 BDC /Inner Do EMC')
    b.obj(b'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] '
          b'/Resources << /ProcSet %d 0 R /XObject << /Inner %d 0 R >> '
          b'/Properties << /MC0 << /Title (pdfrw \\(rl\\)) >> >> >> '
          b'/Contents %d 0 R >>' % (tree, procset, inner, content),
          num=page)
    b.obj(b'<< /Type /Pages /Kids [%d 0 R] /Count 1 >>' % page, num=tree)
    b.obj(b'<< /Type /Catalog /Pages %d 0 R >>' % tree, num=catalog)
    b.xref_table(b'/Root %d 0 R' % catalog)
    return b.getvalue()


def test_resources_carried_over(rl):
    xobj = pagexobj(pages_of(resource_rich_pdf())[0])
    canv, out = canvas()
    canv.doForm(rl.makerl(canv, xobj))
    canv.showPage()
    canv.save()
    data = out.getvalue()
    assert_valid(data, pages=1)
    image = render(data)
    assert inked(image, *TL) and not inked(image, *BR)

    pikepdf = require('pikepdf')
    with pikepdf.open(io.BytesIO(data)) as pdf:
        xobjects = pdf.pages[0].Resources.XObject
        form, = [xobjects[k] for k in xobjects.keys()]
        resources = form.Resources
        assert list(resources.ProcSet) == [pikepdf.Name.PDF,
                                           pikepdf.Name.Text]
        assert resources.ProcSet.is_indirect
        assert str(resources.Properties.MC0.Title) == 'pdfrw (rl)'
        inner = resources.XObject.Inner
        assert inner.Subtype == pikepdf.Name.Form
        assert b' re f' in inner.read_bytes()


def test_direct_objects_converted(rl):
    from reportlab.pdfbase import pdfdoc
    canv, _ = canvas()
    obj = PdfDict(Kind=PdfName.Thing, Size=1.5,
                  Label=PdfString.from_unicode('caf\xe9'),
                  Items=PdfArray([1, PdfName.Two]))
    result = rl.makerl(canv, obj)
    assert isinstance(result, pdfdoc.PDFDictionary)
    assert result['Kind'] == '/Thing'
    assert result['Size'] == '1.5'
    assert result['Label'] == PdfString.from_unicode('caf\xe9')
    items = result['Items']
    assert isinstance(items, pdfdoc.PDFArray)
    assert items.sequence == ['1', '/Two']
    # Scalars convert to their PDF text.
    assert rl.makerl(canv, 7) == '7'
    assert rl.makerl(canv, PdfName.Three) == '/Three'


def test_indirect_objects_become_references(rl):
    from reportlab.pdfbase import pdfdoc
    canv, _ = canvas()
    array = PdfArray([1, 2])
    array.indirect = True
    obj = PdfDict(A=array)
    obj.indirect = True
    result = rl.makerl(canv, obj)
    assert isinstance(result, pdfdoc.PDFObjectReference)
    # A plain stream (not an XObject) is a reference with no form name.
    plain = PdfDict(stream='q Q')
    assert isinstance(rl.makerl(canv, plain), pdfdoc.PDFObjectReference)
