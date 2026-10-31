#!/usr/bin/env python

'''
usage:   booklet.py [-p] my.pdf

Creates booklet.my.pdf

Pages organized in a form suitable for booklet printing, e.g.
to print 4 8.5x11 pages using a single 11x17 sheet (double-sided).

The output would be using the same type of sheet
and you can get up to 3 blank sides if -p is enabled.

Otherwise, when the page count is 2 more than a multiple of 4, the two
sides in the middle are in original page size (one leaf, printed on
both sides, that goes inside the folded sheets), and you get at most 1
blank side.

'''

import os
import argparse

from pdfrw import PdfReader, PdfWriter

from pagetools import max_page_size, side_by_side


parser = argparse.ArgumentParser()
parser.add_argument("input", help="Input pdf file name")
parser.add_argument("-p", "--padding", action = "store_true",
                    help="Padding the document so that all pages use the same type of sheet")
args = parser.parse_args()

inpfn = args.input
outfn = 'booklet.' + os.path.basename(inpfn)
ipages = PdfReader(inpfn).pages

if args.padding:
    pad_to = 4
else:
    pad_to = 2

if not ipages:
    raise SystemExit('%s has no pages' % inpfn)

# Each half sheet is as big as the largest input page
size = max_page_size(ipages)

# Make sure we have a correct number of sides
ipages += [None]*(-len(ipages)%pad_to)

opages = []
while len(ipages) > 2:
    opages.append(side_by_side(ipages.pop(), ipages.pop(0), size))
    opages.append(side_by_side(ipages.pop(0), ipages.pop(), size))

# Without padding, a page count of 2 mod 4 leaves the two middle sides,
# which go on a single leaf in their original size.  A one-page input
# leaves its page and a blank, which is left out.
opages += [x for x in ipages if x is not None]

PdfWriter(outfn).addpages(opages).write()
