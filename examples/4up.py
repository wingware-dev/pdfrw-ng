#!/usr/bin/env python

'''
usage:   4up.py my.pdf

Creates 4up.my.pdf with a single output page for every
4 input pages: two across and two down.
'''

import sys
import os

from pdfrw import PdfReader, PdfWriter

from pagetools import grid

if len(sys.argv) != 2:
    raise SystemExit(__doc__)
inpfn = sys.argv[1]
outfn = '4up.' + os.path.basename(inpfn)
pages = PdfReader(inpfn).pages
writer = PdfWriter(outfn)
for index in range(0, len(pages), 4):
    writer.addpage(grid(pages[index:index + 4], 2, 2))
writer.write()
