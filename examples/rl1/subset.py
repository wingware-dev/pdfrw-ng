#!/usr/bin/env python

'''
usage:   subset.py my.pdf firstpage [lastpage]

Creates subset.my.pdf with pages firstpage to lastpage (default: just
firstpage).  Pages are numbered from 1.


Uses Form XObjects and reportlab to create output file.

Demonstrates use of pdfrw with reportlab.

'''

import sys
import os

from reportlab.pdfgen.canvas import Canvas

from pdfrw import PdfReader
from pdfrw.buildxobj import pagexobj
from pdfrw.toreportlab import makerl


def go(inpfn, firstpage, lastpage):
    firstpage, lastpage = int(firstpage), int(lastpage)
    outfn = 'subset.' + os.path.basename(inpfn)

    pages = PdfReader(inpfn).pages
    if not 1 <= firstpage <= lastpage <= len(pages):
        raise SystemExit('Bad page range %d-%d: pages are numbered 1 to %d'
                         % (firstpage, lastpage, len(pages)))
    pages = [pagexobj(x) for x in pages[firstpage - 1:lastpage]]
    canvas = Canvas(outfn)

    for page in pages:
        canvas.setPageSize((page.BBox[2], page.BBox[3]))
        canvas.doForm(makerl(canvas, page))
        canvas.showPage()

    canvas.save()

if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) not in (2, 3):
        raise SystemExit(__doc__)
    inpfn, firstpage = args[:2]
    lastpage = args[2] if len(args) == 3 else firstpage
    go(inpfn, firstpage, lastpage)
