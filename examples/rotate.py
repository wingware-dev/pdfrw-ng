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

from pagetools import parse_ranges

inpfn = sys.argv[1]
rotate = sys.argv[2]
ranges = sys.argv[3:]

rotate = int(rotate)
if rotate % 90:
    raise SystemExit('Rotation must be a multiple of 90 degrees')

outfn = 'rotate.%s' % os.path.basename(inpfn)
trailer = PdfReader(inpfn)
pages = trailer.pages

if ranges:
    ranges = parse_ranges(ranges, len(pages))
else:
    ranges = [range(1, len(pages) + 1)]

for onerange in ranges:
    for pagenum in onerange:
        page = pages[pagenum - 1]
        page.Rotate = (int(page.inheritable.Rotate or 0) + rotate) % 360

outdata = PdfWriter(outfn)
outdata.trailer = trailer
outdata.write()
