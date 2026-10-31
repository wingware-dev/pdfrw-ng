# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

'''
Helpers shared by the example scripts in this directory.

Not an example itself.  The scripts import it as `pagetools`, which works
because Python puts a script's own directory first on sys.path.  (That
is also why no script or helper here may share a name with a standard
library module: see rl2/copy_pdf.py, upstream issue #218.)

    parse_ranges(['1-3', '5'], 9)   -> [range(1, 4), range(5, 6)]
    page_size(page)                 -> (width, height)
    max_page_size(pages)            -> (largest width, largest height)
    side_by_side(left, right, size) -> one two-up page
    grid(pages, columns, rows)      -> one n-up page, e.g. 6-up or 9-up
'''

from pdfrw import PageMerge, PdfArray


def parse_range(text, numpages):
    ''' Turn '3', '3-5' or '5-3' into the 1-based page numbers it names,
        in that order.  Exits with a message for a malformed range or a
        page outside 1..numpages.
    '''
    try:
        bounds = [int(x) for x in text.split('-')]
    except ValueError:
        bounds = []
    if len(bounds) not in (1, 2):
        raise SystemExit('Bad page range %r' % text)
    first, last = bounds[0], bounds[-1]
    for pagenum in (first, last):
        if not 1 <= pagenum <= numpages:
            raise SystemExit('Page %d is out of range: pages are numbered '
                             '1 to %d' % (pagenum, numpages))
    step = 1 if last >= first else -1
    return range(first, last + step, step)


def parse_ranges(texts, numpages):
    ''' parse_range for each of `texts`. '''
    return [parse_range(text, numpages) for text in texts]


def page_size(page):
    ''' The (width, height) a page takes up once placed. '''
    rect = PageMerge().add(page)[0]
    return rect.w, rect.h


def max_page_size(pages):
    ''' The largest width and the largest height among `pages`. '''
    return tuple(max(dims) for dims in zip(*(page_size(x) for x in pages)))


def side_by_side(left, right, size):
    ''' Put two pages side by side on one sheet.  Either may be None
        (a blank half); `size` is the (width, height) of one half.
    '''
    result = PageMerge()
    for x, page in ((0, left), (size[0], right)):
        if page is not None:
            result.add(page)
            result[-1].x = x
    result.mbox = PdfArray([0, 0, 2 * size[0], size[1]])
    return result.render()


def grid(pages, columns, rows):
    ''' Up to columns * rows pages on one sheet, in reading order (left
        to right, then top to bottom).  Each page is shrunk by the same
        factor, 1 / max(columns, rows), so none is distorted.  The sheet
        is sized for a full grid even when fewer pages are given, so the
        last sheet of a document matches the others.
    '''
    scale = 1.0 / max(columns, rows)
    width, height = (scale * x for x in max_page_size(pages))
    result = PageMerge() + pages
    for index, page in enumerate(result):
        page.scale(scale)
        row, column = divmod(index, columns)
        page.x = column * width
        page.y = (rows - 1 - row) * height
    result.mbox = PdfArray([0, 0, columns * width, rows * height])
    return result.render()
