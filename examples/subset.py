#!/usr/bin/env python

'''
usage:   subset.py my.pdf page[range] [page[range]] ...
         eg. subset.py my.pdf 1-3 5 7-9

Pages are numbered from 1.

Creates subset.my.pdf

'''

import sys
import os

from pdfrw import PdfReader, PdfWriter

inpfn = sys.argv[1]
ranges = sys.argv[2:]
if not ranges:
    raise SystemExit(__doc__)


def parse_range(text, numpages):
    """ Turn '3', '3-5' or '5-3' into the 1-based page numbers it names,
        in that order.
    """
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


outfn = 'subset.%s' % os.path.basename(inpfn)
pages = PdfReader(inpfn).pages
ranges = [parse_range(x, len(pages)) for x in ranges]
outdata = PdfWriter(outfn)

for onerange in ranges:
    for pagenum in onerange:
        outdata.addpage(pages[pagenum-1])
outdata.write()
