#!/usr/bin/env python

'''
usage: subset_booklets.py my.pdf

Creates subset_booklets.my.pdf

Pages organized in a form suitable for booklet printing, e.g.
to print 4 8.5x11 pages using a single 11x17 sheet (double-sided).
Instead of a large booklet, the pdf is divided into several mini
booklets. The reason is: professional printing works this way:
    - Print all of several mini booklets(subsets of booklet);
    - Saw each mini booklet individually;
    - glue them all together;
    - Insert the cover.

    Take a look at http://www.wikihow.com/Bind-a-Book
'''

import sys
import os
import time
from pdfrw import PdfReader, PdfWriter, PageMerge, PdfArray

BOOKLET_SIZE = 20
START = time.time()


def fixpage(left, right, size):
    """ Put two pages side by side on one sheet.  Either may be None
        (a blank half); `size` is the (width, height) of one half.
    """
    result = PageMerge()
    for x, page in ((0, left), (size[0], right)):
        if page is not None:
            result.add(page)
            result[-1].x = x
    result.mbox = PdfArray([0, 0, 2 * size[0], size[1]])
    return result.render()


def page_size(page):
    rect = PageMerge().add(page)[0]
    return rect.w, rect.h


def booklet(ipages, size):
    """ Impose one booklet; return its sheet sides. """
    ipages = list(ipages)
    opages = []
    while len(ipages) > 2:
        opages.append(fixpage(ipages.pop(), ipages.pop(0), size))
        opages.append(fixpage(ipages.pop(0), ipages.pop(), size))
    if ipages:
        # Two pages left: one side of a sheet whose other side is blank
        opages.append(fixpage(ipages.pop(), ipages.pop(0), size))
    return opages


INPFN, = sys.argv[1:]
OUTFN = 'subset_booklets.' + os.path.basename(INPFN)
ALL_IPAGES = PdfReader(INPFN).pages
print('The pdf file %s has %d pages.' % (INPFN, len(ALL_IPAGES)))
if not ALL_IPAGES:
    raise SystemExit('Nothing to do')
SIZE = tuple(max(dims) for dims in zip(*(page_size(x) for x in ALL_IPAGES)))

#Make sure we have an even number
if len(ALL_IPAGES) & 1:
    ALL_IPAGES.append(None)
    print('Inserting one more blank page to make pages number even.')
NUM_OF_ITER, ITERS_LEFT = divmod(len(ALL_IPAGES), BOOKLET_SIZE)

print('Making %d subbooklets of %d pages each.' % (NUM_OF_ITER, BOOKLET_SIZE))
opages = []
for iteration in range(0, NUM_OF_ITER):
    opages += booklet(ALL_IPAGES[iteration*BOOKLET_SIZE:
                                 (iteration+1)*BOOKLET_SIZE], SIZE)

# Making one more subbooklet with the left pages
if ITERS_LEFT:
    opages += booklet(ALL_IPAGES[len(ALL_IPAGES)-ITERS_LEFT:], SIZE)

PdfWriter(OUTFN).addpages(opages).write()
print('It took %.2f seconds to make the pdf subbooklets changes.'
      % (time.time() - START))
