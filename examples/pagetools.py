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
