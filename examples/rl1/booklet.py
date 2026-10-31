#!/usr/bin/env python

'''
usage:   booklet.py my.pdf


Uses Form XObjects and reportlab to create booklet.my.pdf.

Demonstrates use of pdfrw with reportlab.

'''

import sys
import os

from reportlab.pdfgen.canvas import Canvas

from pdfrw import PdfReader
from pdfrw.buildxobj import pagexobj
from pdfrw.toreportlab import makerl


def read_and_double(inpfn):
    pages = PdfReader(inpfn).pages
    pages = [pagexobj(x) for x in pages]
    if len(pages) & 1:
        pages.append(None)  # Blank back page

    xobjs = []
    while len(pages) > 2:
        xobjs.append((pages.pop(), pages.pop(0)))
        xobjs.append((pages.pop(0), pages.pop()))
    xobjs += [(x,) for x in pages if x is not None]
    return xobjs


def make_pdf(outfn, xobjpairs):
    canvas = Canvas(outfn)
    for xobjlist in xobjpairs:
        # A blank half (None) is as big as the other half
        present = [xobj for xobj in xobjlist if xobj is not None]
        width = max(xobj.BBox[2] for xobj in present)
        height = max(xobj.BBox[3] for xobj in present)
        canvas.setPageSize((width * len(xobjlist), height))

        x = 0
        for xobj in xobjlist:
            if xobj is not None:
                canvas.saveState()
                canvas.translate(x, 0)
                canvas.doForm(makerl(canvas, xobj))
                canvas.restoreState()
            x += width
        canvas.showPage()
    canvas.save()


inpfn, = sys.argv[1:]
outfn = 'booklet.' + os.path.basename(inpfn)

make_pdf(outfn, read_and_double(inpfn))
