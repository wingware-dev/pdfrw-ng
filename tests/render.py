# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Drawn test pages, and PDFium rendering to check where ink lands.

`drawing_pdf` builds (with tests/pdfgen.py) a one-page-per-entry PDF
whose pages fill rectangles, so a test can render the output with
PDFium and ask whether a point is inked, which tells it where pdfrw or
reportlab placed, clipped or rotated a page.

    data = drawing_pdf([[(0, 396, 306, 396)]])  # top-left quadrant black
    image = render(data)
    assert inked(image, 100, 700) and not inked(image, 500, 100)

Points are PDF user-space coordinates (origin at the bottom left of the
rendered page) at 72 dpi.
"""

import io

from pdfrw import PdfArray, PdfDict, PdfName, PdfWriter

from .pdfgen import PdfBuilder
from .validate import require

__all__ = ['drawing_pdf', 'rect_content', 'write_pages', 'xobj_page',
           'render', 'inked']


def rect_content(rects):
    """Content stream filling each (x, y, w, h) rectangle in black."""
    ops = [b'0 g']
    ops.extend(b'%g %g %g %g re f' % tuple(rect) for rect in rects)
    return b'\n'.join(ops)


def drawing_pdf(pages, mediabox=(0, 0, 612, 792), rotate=None,
                cropbox=None, compress=False, split=False):
    """A PDF whose page `i` fills the rectangles in `pages[i]`.

    `split` writes each page's content as an array of streams, one per
    rectangle, instead of a single stream.  `rotate` and `cropbox` are
    set on every page.
    """
    builder = PdfBuilder()
    catalog = builder.alloc()
    tree = builder.alloc()
    page_nums = [builder.alloc() for _ in pages]
    for page_num, rects in zip(page_nums, pages):
        if split:
            nums = [builder.stream(rect_content([rect]), compress=compress)
                    for rect in rects]
            contents = b'[' + b' '.join(b'%d 0 R' % n for n in nums) + b']'
        else:
            num = builder.stream(rect_content(rects), compress=compress)
            contents = b'%d 0 R' % num
        extra = b''
        if rotate is not None:
            extra += b' /Rotate %d' % rotate
        if cropbox is not None:
            extra += b' /CropBox [%g %g %g %g]' % tuple(cropbox)
        builder.obj(b'<< /Type /Page /Parent %d 0 R /MediaBox [%g %g %g %g]'
                    % ((tree,) + tuple(mediabox)) + extra +
                    b' /Resources << >> /Contents ' + contents + b' >>',
                    num=page_num)
    kids = b' '.join(b'%d 0 R' % n for n in page_nums)
    builder.obj(b'<< /Type /Pages /Kids [' + kids + b'] /Count %d >>'
                % len(pages), num=tree)
    builder.obj(b'<< /Type /Catalog /Pages %d 0 R >>' % tree, num=catalog)
    builder.xref_table(b'/Root %d 0 R' % catalog)
    return builder.getvalue()


def write_pages(pages, compress=False):
    """Write pdfrw page dictionaries to PDF bytes with PdfWriter."""
    writer = PdfWriter(compress=compress)
    writer.addpages(pages)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def xobj_page(xobj, mediabox=(0, 0, 612, 792), ops=b'/X Do'):
    """A new page drawing Form XObject `xobj` (as /X) with `ops`."""
    return PdfDict(
        Type=PdfName.Page,
        MediaBox=PdfArray(mediabox),
        Resources=PdfDict(XObject=PdfDict(X=xobj)),
        Contents=PdfDict(stream=ops.decode('latin-1')),
    )


def render(data, index=0):
    """Page `index` of `data` rendered by PDFium, as a greyscale image."""
    require('PIL')
    pdfium = require('pypdfium2')
    doc = pdfium.PdfDocument(data)
    try:
        page = doc[index]
        try:
            image = page.render(scale=1).to_pil().convert('L')
        finally:
            page.close()
    finally:
        doc.close()
    return image


def inked(image, x, y):
    """Whether point (x, y), in PDF coordinates, rendered dark."""
    return image.getpixel((int(x), image.height - 1 - int(y))) < 128
