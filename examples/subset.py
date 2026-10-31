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

from pagetools import parse_ranges

inpfn = sys.argv[1]
ranges = sys.argv[2:]
if not ranges:
    raise SystemExit(__doc__)

outfn = 'subset.%s' % os.path.basename(inpfn)
pages = PdfReader(inpfn).pages
ranges = parse_ranges(ranges, len(pages))
outdata = PdfWriter(outfn)

for onerange in ranges:
    for pagenum in onerange:
        outdata.addpage(pages[pagenum-1])
outdata.write()
