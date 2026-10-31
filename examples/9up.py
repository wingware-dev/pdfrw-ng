#!/usr/bin/env python

'''
usage:   9up.py my.pdf

Creates 9up.my.pdf with a single output page for every
9 input pages: three across and three down.
'''

import sys
import os

from pdfrw import PdfReader, PdfWriter

from pagetools import grid

if len(sys.argv) != 2:
    raise SystemExit(__doc__)
inpfn = sys.argv[1]
outfn = '9up.' + os.path.basename(inpfn)
pages = PdfReader(inpfn).pages
writer = PdfWriter(outfn)
for index in range(0, len(pages), 9):
    writer.addpage(grid(pages[index:index + 9], 3, 3))
writer.write()
