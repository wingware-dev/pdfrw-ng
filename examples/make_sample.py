#!/usr/bin/env python

'''
usage:   make_sample.py [npages [outfile]]

Writes outfile, by default build/sample.pdf at the top of the source
tree (whatever the current directory), with npages pages, 8 by
default, each showing "Page N" in large type.  The other examples can then be tried on it,
e.g.

    python examples/make_sample.py
    python examples/booklet.py build/sample.pdf

It uses the PDF builder from the test suite (tests/pdfgen.py), so it
works only from a source checkout, not an installed package.
'''

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.pdfgen import make_pdf  # noqa: E402


def main(argv):
    if len(argv) > 2:
        raise SystemExit(__doc__)
    try:
        npages = int(argv[0]) if argv else 8
    except ValueError:
        raise SystemExit('npages must be a number: %r' % argv[0])
    if npages < 1:
        raise SystemExit('npages must be at least 1')
    if len(argv) == 2:
        outfn = argv[1]
    else:
        outfn = os.path.join(ROOT, 'build', 'sample.pdf')
        os.makedirs(os.path.dirname(outfn), exist_ok=True)
    with open(outfn, 'wb') as f:
        f.write(make_pdf(npages, compress=True))
    print('Wrote %s (%d pages)' % (outfn, npages))


if __name__ == '__main__':
    main(sys.argv[1:])
