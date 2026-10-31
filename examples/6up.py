#!/usr/bin/env python

'''
usage:   6up.py my.pdf

Creates 6up.my.pdf with a single output page for every
6 input pages: two across and three down.
'''

import sys
import os

from pdfrw import PdfReader, PdfWriter

from pagetools import grid

if len(sys.argv) != 2:
    raise SystemExit(__doc__)
inpfn = sys.argv[1]
outfn = '6up.' + os.path.basename(inpfn)
pages = PdfReader(inpfn).pages
writer = PdfWriter(outfn)
for index in range(0, len(pages), 6):
    writer.addpage(grid(pages[index:index + 6], 2, 3))
writer.write()
