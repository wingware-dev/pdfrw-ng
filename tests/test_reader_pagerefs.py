# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""PdfReader.remove_page drops what still goes to the removed page.

Bookmarks, named destinations, links and an /OpenAction that go to a
removed page used to stay, and pulled the page into a written copy as an
orphan object.  Each test builds its own PDF, removes pages, and checks
the written copy with qpdf (pikepdf), pypdf and PDFium: the page is gone
from the file, and what pointed at it is gone or has lost its target.
"""

import io

import pytest

from pdfrw import PdfReader, PdfWriter, PdfDict, PdfArray, PdfName, \
    PdfString, IndirectPdfDict
from pdfrw.pagerefs import drop_page_refs

from .pdfgen import PdfBuilder, page_content, page_label
from .validate import assert_valid, require

LABELS = [page_label(i) for i in range(4)]


def build(c_count=1, order=(0, 1, 2, 3)):
    """Four pages, "Page 1" to "Page 4", with references to each.

    Outline (top-level unless noted), each going to:
      A   page 1, explicit /Dest
      B   page 2, explicit /Dest
      C   page 2, named destination (two) via the name tree; /Count
          `c_count`
        C1  page 3, explicit /Dest
      D   page 2, /GoTo action to /old, a name in the /Dests dictionary
      E   page 4, /GoTo action with an explicit destination
    Name tree /Names /Dests: Kids [leaf1, leaf2], leaf1 holding (alpha)
    to page 1 and (zulu) to page 2, leaf2 holding (two) to page 2 as a
    dictionary with /D.  /Dests dictionary: /old to page 2, /keep to
    page 4.  Page 1 has links: to page 2 explicitly, to (zulu) by a
    /GoTo action, to page 3 explicitly, and a /URI link.  /OpenAction
    goes to page 2.  `order` lists the pages in /Kids (a page may be
    listed twice).
    """
    b = PdfBuilder()
    n = dict((name, b.alloc()) for name in (
        'catalog', 'pages', 'font', 'outlines', 'A', 'B', 'C', 'C1', 'D',
        'E', 'names', 'leaf1', 'leaf2', 'dests', 'L1', 'L2', 'L3', 'L4'))
    p = [b.alloc() for _ in LABELS]
    content = [b.stream(page_content(label)) for label in LABELS]

    def obj(name, body):
        b.obj((body % dict(n, p0=p[0], p1=p[1], p2=p[2], p3=p[3]))
              .encode('latin-1'), num=n[name])

    obj('catalog', '<< /Type /Catalog /Pages %(pages)d 0 R '
        '/Outlines %(outlines)d 0 R /PageMode /UseOutlines '
        '/Names << /Dests << /Kids [%(leaf1)d 0 R %(leaf2)d 0 R] >> >> '
        '/Dests %(dests)d 0 R /OpenAction [%(p1)d 0 R /Fit] >>')
    obj('font', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    kids = ' '.join('%d 0 R' % p[i] for i in order)
    obj('pages', '<< /Type /Pages /Kids [%s] /Count %d >>'
        % (kids, len(order)))
    for i, num in enumerate(p):
        annots = (' /Annots [%(L1)d 0 R %(L2)d 0 R %(L3)d 0 R %(L4)d 0 R]'
                  % n if i == 0 else '')
        b.obj(('<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] '
               '/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R%s'
               ' >>' % (n['pages'], n['font'], content[i], annots))
              .encode('latin-1'), num=num)

    top_count = 4 + (1 if c_count > 0 else 0) + 1
    obj('outlines', '<< /Type /Outlines /First %(A)d 0 R /Last %(E)d 0 R '
        '/Count ' + str(top_count) + ' >>')
    item = ('<< /Title (%s) /Parent %%(outlines)d 0 R %s %s >>')
    obj('A', item % ('A', '/Next %(B)d 0 R', '/Dest [%(p0)d 0 R /XYZ 0 792 0]'))
    obj('B', item % ('B', '/Prev %(A)d 0 R /Next %(C)d 0 R',
                     '/Dest [%(p1)d 0 R /Fit]'))
    obj('C', item % ('C', '/Prev %(B)d 0 R /Next %(D)d 0 R /First %(C1)d 0 R'
                     ' /Last %(C1)d 0 R /Count ' + str(c_count), '/Dest (two)'))
    obj('C1', '<< /Title (C1) /Parent %(C)d 0 R /Dest [%(p2)d 0 R /Fit] >>')
    obj('D', item % ('D', '/Prev %(C)d 0 R /Next %(E)d 0 R',
                     '/A << /S /GoTo /D /old >>'))
    obj('E', item % ('E', '/Prev %(D)d 0 R',
                     '/A << /S /GoTo /D [%(p3)d 0 R /Fit] >>'))

    obj('leaf1', '<< /Limits [(alpha) (zulu)] /Names [(alpha) '
        '[%(p0)d 0 R /Fit] (zulu) [%(p1)d 0 R /Fit]] >>')
    obj('leaf2', '<< /Limits [(two) (two)] /Names [(two) '
        '<< /D [%(p1)d 0 R /Fit] >>] >>')
    obj('dests', '<< /old [%(p1)d 0 R /Fit] /keep [%(p3)d 0 R /Fit] >>')

    link = '<< /Type /Annot /Subtype /Link /Rect [%s] /Border [0 0 0] %s >>'
    obj('L1', link % ('0 0 10 10', '/Dest [%(p1)d 0 R /Fit]'))
    obj('L2', link % ('10 0 20 10', '/A << /S /GoTo /D (zulu) >>'))
    obj('L3', link % ('20 0 30 10', '/Dest [%(p2)d 0 R /Fit]'))
    obj('L4', link % ('30 0 40 10',
                      '/A << /S /URI /URI (https://example.com/) >>'))
    b.xref_table(b'/Root %d 0 R' % n['catalog'])
    return b.getvalue()


def copy(reader):
    out = io.BytesIO()
    PdfWriter(out, trailer=reader).write()
    return out.getvalue()


def pdfium_toc(data):
    """[(level, title, page index or None)] as PDFium shows bookmarks,
    following explicit destinations, named ones and /GoTo actions."""
    pdfium = require('pypdfium2')
    raw = pdfium.raw
    doc = pdfium.PdfDocument(data)
    try:
        toc = []
        for mark in doc.get_toc():
            dest = raw.FPDFBookmark_GetDest(doc, mark)
            if not dest:
                action = raw.FPDFBookmark_GetAction(mark)
                if action:
                    dest = raw.FPDFAction_GetDest(doc, action)
            index = raw.FPDFDest_GetDestPageIndex(doc, dest) if dest else -1
            toc.append((mark.level, mark.get_title(),
                        None if index < 0 else index))
        return toc
    finally:
        doc.close()


def page_objects(pdf):
    """How many /Type /Page dictionaries the file holds, reachable or
    not."""
    pikepdf = require('pikepdf')
    return sum(1 for obj in pdf.objects
               if isinstance(obj, pikepdf.Dictionary) and
               obj.get('/Type') == '/Page')


def open_pdf(data):
    return require('pikepdf').open(io.BytesIO(data))


def link_targets(pdf, page_index=0):
    """Where each annotation on a page goes: a page index, a name, or
    the URI."""
    pikepdf = require('pikepdf')
    pages = [page.obj.objgen for page in pdf.pages]
    targets = []
    for annot in pdf.pages[page_index].obj.get('/Annots', []):
        dest = annot.get('/Dest')
        action = annot.get('/A')
        if dest is None and action is not None:
            if action.get('/S') == '/URI':
                targets.append(str(action.URI))
                continue
            dest = action.get('/D')
        if isinstance(dest, pikepdf.Array):
            targets.append(pages.index(dest[0].objgen))
        else:
            targets.append(str(dest))
    return targets


def test_input_is_valid():
    data = build()
    assert_valid(data, texts=LABELS)
    assert pdfium_toc(data) == [(0, 'A', 0), (0, 'B', 1), (0, 'C', 1),
                                (1, 'C1', 2), (0, 'D', 1), (0, 'E', 3)]
    with open_pdf(data) as pdf:
        assert link_targets(pdf) == [1, 'zulu', 2, 'https://example.com/']


@pytest.mark.parametrize('c_count, top_count', [(1, 4), (-1, 3)])
def test_remove_page_drops_refs(c_count, top_count):
    reader = PdfReader(fdata=build(c_count=c_count))
    reader.remove_page(1)
    data = copy(reader)
    kept = [LABELS[0], LABELS[2], LABELS[3]]
    assert_valid(data, texts=kept)
    assert b'(Page 2)' not in data
    # C stays, without a destination, for its child C1.
    assert pdfium_toc(data) == [(0, 'A', 0), (0, 'C', None), (1, 'C1', 1),
                                (0, 'E', 2)]
    with open_pdf(data) as pdf:
        assert page_objects(pdf) == 3
        root = pdf.Root
        assert '/OpenAction' not in root
        assert int(root.Outlines.Count) == top_count
        assert int(root.Outlines.First.Next.Count) == c_count
        assert link_targets(pdf) == [1, 'https://example.com/']
        tree = root.Names.Dests
        assert len(tree.Kids) == 1
        leaf = tree.Kids[0]
        assert [str(x) for x in leaf.Names[0::2]] == ['alpha']
        assert [str(x) for x in leaf.Limits] == ['alpha', 'alpha']
        assert list(root.Dests.keys()) == ['/keep']


def test_remove_several_pages():
    reader = PdfReader(fdata=build())
    for index in (3, 1, 0):
        reader.remove_page(index)
    data = copy(reader)
    assert_valid(data, texts=[LABELS[2]])
    assert pdfium_toc(data) == [(0, 'C', None), (1, 'C1', 0)]
    with open_pdf(data) as pdf:
        assert page_objects(pdf) == 1
        assert int(pdf.Root.Outlines.Count) == 2
        assert pdf.Root.Outlines.First == pdf.Root.Outlines.Last
        assert '/Annots' not in pdf.pages[0].obj or \
            len(pdf.pages[0].obj.Annots) == 0
        assert list(pdf.Root.Dests.keys()) == []


def test_page_still_listed_keeps_refs():
    """A page listed twice in /Kids is still in the tree after one of
    its places is removed, so nothing that goes to it is dropped."""
    order = (1, 0, 1, 2, 3)
    reader = PdfReader(fdata=build(order=order))
    reader.remove_page(0)
    data = copy(reader)
    assert_valid(data, texts=[LABELS[i] for i in order[1:]])
    titles = [title for _, title, _ in pdfium_toc(data)]
    assert titles == ['A', 'B', 'C', 'C1', 'D', 'E']
    with open_pdf(data) as pdf:
        assert '/OpenAction' in pdf.Root
        assert len(link_targets(pdf)) == 4


# -- drop_page_refs on objects made in memory ------------------------------

def make_page():
    return IndirectPdfDict(Type=PdfName.Page)


def test_last_outline_item_removed():
    page, other = make_page(), make_page()
    top = IndirectPdfDict(Type=PdfName.Outlines, Count=1)
    item = IndirectPdfDict(Title=PdfString.encode('only'), Parent=top,
                           Dest=PdfArray([page, PdfName.Fit]))
    top.First = top.Last = item
    root = PdfDict(Outlines=top)
    drop_page_refs(root, page, [other])
    assert (top.First, top.Last, top.Count) == (None, None, None)


def test_goto_dropped_from_other_annotations():
    """A widget (say, a button) with a /GoTo action to the page keeps
    its place and loses only the action; other actions stay."""
    page, other = make_page(), make_page()
    goto = PdfDict(S=PdfName.GoTo, D=PdfArray([page, PdfName.Fit]))
    widget = PdfDict(Subtype=PdfName.Widget, A=goto)
    uri = PdfDict(Subtype=PdfName.Widget,
                  A=PdfDict(S=PdfName.URI, URI=PdfString.encode('x')))
    other.Annots = PdfArray([widget, uri])
    drop_page_refs(PdfDict(), page, [other])
    assert list(other.Annots) == [widget, uri]
    assert widget.A is None and uri.A is not None


def test_open_action_goto():
    page, other = make_page(), make_page()
    root = PdfDict(OpenAction=PdfDict(S=PdfName.GoTo,
                                      D=PdfArray([page, PdfName.Fit])))
    drop_page_refs(root, page, [other])
    assert root.OpenAction is None
    root.OpenAction = PdfArray([other, PdfName.Fit])
    drop_page_refs(root, page, [other])
    assert root.OpenAction is not None


def test_name_tree_limits_and_strings_by_value():
    """Name keys match by their bytes, whatever the string's syntax, and
    the limits of each changed node above a removal are recomputed."""
    page, other = make_page(), make_page()
    leaf = PdfDict(Limits=PdfArray([PdfString('(a)'), PdfString('(c)')]),
                   Names=PdfArray([PdfString('(a)'),
                                   PdfArray([other, PdfName.Fit]),
                                   PdfString('(c)'),
                                   PdfArray([page, PdfName.Fit])]))
    mid = PdfDict(Limits=PdfArray([PdfString('(a)'), PdfString('(c)')]),
                  Kids=PdfArray([leaf]))
    tree = PdfDict(Kids=PdfArray([mid]))
    link = PdfDict(Subtype=PdfName.Link, Dest=PdfString('<63>'))  # "c"
    other.Annots = PdfArray([link])
    drop_page_refs(PdfDict(Names=PdfDict(Dests=tree)), page, [other])
    assert leaf.Limits == ['(a)', '(a)'] and mid.Limits == ['(a)', '(a)']
    assert list(other.Annots) == []
    assert link.Dest is None
