#!/usr/bin/env python

'''
usage:   rotate.py my.pdf rotation [page[range] ...]
         eg. rotate.py my.pdf 270 1-3 5 7-9

        Rotation must be multiple of 90 degrees, clockwise.

Creates rotate.my.pdf with selected pages rotated.  Rotates all by default.
Pages are numbered from 1.

'''

import sys
import os

from pdfrw import PdfReader, PdfWriter

inpfn = sys.argv[1]
rotate = sys.argv[2]
ranges = sys.argv[3:]

rotate = int(rotate)
if rotate % 90:
    raise SystemExit('Rotation must be a multiple of 90 degrees')


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


outfn = 'rotate.%s' % os.path.basename(inpfn)
trailer = PdfReader(inpfn)
pages = trailer.pages

if ranges:
    ranges = [parse_range(x, len(pages)) for x in ranges]
else:
    ranges = [range(1, len(pages) + 1)]

for onerange in ranges:
    for pagenum in onerange:
        page = pages[pagenum - 1]
        page.Rotate = (int(page.inheritable.Rotate or 0) + rotate) % 360

outdata = PdfWriter(outfn)
outdata.trailer = trailer
outdata.write()
