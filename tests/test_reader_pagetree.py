# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""PdfReader.readpages on damaged page trees.

One bad node used to cost the whole tree: a single dangling /Kids
reference, or a /Pages node without /Type, gave 0 pages, and a copy
written from the reader had no pages either.  Now only the bad node is
skipped, as PDFium and pypdf do, and every input is first checked with
them.
"""

import io
import logging

import pytest

from pdfrw import PdfReader, PdfWriter

from .pdfgen import PdfBuilder, make_pdf, page_content, page_label
from .validate import assert_valid, pdfium_page_texts, pypdf_page_count

LABELS = [page_label(i) for i in range(3)]


def labels_of(reader):
    labels = []
    for page in reader.pages:
        stream = page.Contents.stream
        labels.append(stream[stream.index('(') + 1:stream.index(')')])
    return labels


def read(data, caplog):
    """Read `data`, returning the reader and pdfrw's warning messages."""
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger='pdfrw'):
        reader = PdfReader(fdata=data)
    return reader, [r.getMessage() for r in caplog.records]


def copy_via_trailer(reader):
    """Write the reader's own (repaired) page tree back out."""
    out = io.BytesIO()
    PdfWriter(out, trailer=reader).write()
    return out.getvalue()


def copy_via_addpages(reader):
    out = io.BytesIO()
    writer = PdfWriter(out)
    writer.addpages(reader.pages)
    writer.write()
    return out.getvalue()


def build_tree(kids, page_types=None, extra=None):
    """A 3-page file whose page tree `kids(b, pages, page_nums)` writes.

    `page_types` gives each page's /Type entry (bytes, may be empty).
    `extra(b)` may write more objects first and return their numbers.
    """
    b = PdfBuilder()
    catalog, pages, font = b.alloc(), b.alloc(), b.alloc()
    page_nums = [b.alloc() for _ in LABELS]
    contents = [b.stream(page_content(label)) for label in LABELS]
    b.obj(b'<< /Type /Catalog /Pages %d 0 R >>' % pages, num=catalog)
    b.obj(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
          num=font)
    page_types = page_types or [b'/Type /Page'] * len(LABELS)
    for num, content, ptype in zip(page_nums, contents, page_types):
        b.obj(b'<< ' + ptype + b' /Parent %d 0 R /MediaBox [0 0 612 792] '
              b'/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>'
              % (pages, font, content), num=num)
    kids(b, pages, page_nums)
    b.xref_table(b'/Root %d 0 R' % catalog)
    return b.getvalue()


def flat(extra_kids=b'', pages_type=b'/Type /Pages'):
    def write(b, pages, page_nums):
        refs = b' '.join(b'%d 0 R' % n for n in page_nums)
        b.obj(b'<< ' + pages_type + b' /Kids [' + refs + b' ' + extra_kids +
              b'] /Count %d >>' % len(page_nums), num=pages)
    return write


# -- the 0-page bug --------------------------------------------------------

@pytest.mark.parametrize('dangling', [1, 2])
def test_dangling_kid_skipped(dangling, caplog):
    data = make_pdf(3, dangling_kids=dangling)
    assert pdfium_page_texts(data) == LABELS
    assert pypdf_page_count(data, strict=False) == 3
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert reader.numPages == 3
    assert sum('not a dictionary' in w for w in warnings) == dangling


def test_untyped_pages_node(caplog):
    data = make_pdf(3, untyped_pages=True)
    assert pdfium_page_texts(data) == LABELS
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert any('reading it as /Pages' in w for w in warnings)
    assert reader.Root.Pages.Type == '/Pages'


@pytest.mark.parametrize('kid', [b'5', b'null', b'[1 2]', b'(text)',
                                 b'/Name'])
def test_non_dictionary_kid_skipped(kid, caplog):
    data = build_tree(flat(kid))
    assert pdfium_page_texts(data) == LABELS
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert any('not a dictionary' in w for w in warnings)


def test_writer_copies_keep_pages_of_damaged_tree(caplog):
    """The writer used to write 0 pages here, silently."""
    data = make_pdf(3, dangling_kids=1)
    reader, _ = read(data, caplog)
    assert_valid(copy_via_addpages(reader), texts=LABELS)
    reader, _ = read(data, caplog)
    assert_valid(copy_via_trailer(reader), texts=LABELS)


def test_untyped_pages_copy_is_valid(caplog):
    """The repaired /Type is written, so qpdf no longer has to override
    it."""
    reader, _ = read(make_pdf(3, untyped_pages=True), caplog)
    assert_valid(copy_via_trailer(reader), texts=LABELS)


# -- leaves ----------------------------------------------------------------

def test_untyped_page_read_as_page(caplog):
    data = build_tree(flat(), page_types=[b'/Type /Page', b'',
                                          b'/Type /Page'])
    assert pdfium_page_texts(data) == LABELS
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert any('reading it as a /Page' in w for w in warnings)
    assert reader.pages[1].Type == '/Page'
    assert_valid(copy_via_trailer(reader), texts=LABELS)


def test_wrongly_typed_leaf_skipped(caplog):
    """A leaf typed /Foo: PDFium cannot load it and pypdf drops it."""
    data = build_tree(flat(), page_types=[b'/Type /Page', b'/Type /Foo',
                                          b'/Type /Page'])
    assert pypdf_page_count(data, strict=False) == 2
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == [LABELS[0], LABELS[2]]
    assert any('/Type is /Foo' in w for w in warnings)


def test_duplicate_page_kept(caplog):
    def kids(b, pages, page_nums):
        b.obj(b'<< /Type /Pages /Kids [%d 0 R %d 0 R] /Count 2 >>'
              % (page_nums[0], page_nums[0]), num=pages)
    data = build_tree(kids)
    assert pdfium_page_texts(data) == [LABELS[0], LABELS[0]]
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == [LABELS[0], LABELS[0]]
    assert not warnings


# -- nesting and loops -----------------------------------------------------

def test_nested_tree_in_order(caplog):
    def kids(b, pages, page_nums):
        mid = b.alloc()
        b.obj(b'<< /Type /Pages /Kids [%d 0 R %d 0 R] /Count 3 >>'
              % (page_nums[0], mid), num=pages)
        b.obj(b'<< /Type /Pages /Parent %d 0 R /Kids [%d 0 R %d 0 R] '
              b'/Count 2 >>' % (pages, page_nums[1], page_nums[2]), num=mid)
    data = build_tree(kids)
    assert_valid(data, texts=LABELS)
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert not warnings


def test_loop_skipped(caplog):
    """A /Pages node listing its parent: PDFium reads the pages and
    ignores the loop; pdfrw does the same instead of looping forever."""
    def kids(b, pages, page_nums):
        mid = b.alloc()
        b.obj(b'<< /Type /Pages /Kids [%d 0 R %d 0 R] /Count 3 >>'
              % (page_nums[0], mid), num=pages)
        b.obj(b'<< /Type /Pages /Parent %d 0 R /Kids [%d 0 R %d 0 R %d 0 R]'
              b' /Count 2 >>' % (pages, page_nums[1], page_nums[2], pages),
              num=mid)
    data = build_tree(kids)
    assert pdfium_page_texts(data) == LABELS
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert any('loop' in w for w in warnings)
    assert_valid(copy_via_trailer(reader), texts=LABELS)


def test_self_loop_skipped(caplog):
    def kids(b, pages, page_nums):
        refs = b' '.join(b'%d 0 R' % n for n in page_nums)
        b.obj(b'<< /Type /Pages /Kids [' + refs + b' %d 0 R] /Count 3 >>'
              % pages, num=pages)
    data = build_tree(kids)
    assert pdfium_page_texts(data) == LABELS
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == LABELS
    assert any('loop' in w for w in warnings)


def test_shared_subtree_is_not_a_loop(caplog):
    """The same /Pages node listed twice is not a loop: PDFium and pypdf
    show its pages twice, and so does pdfrw."""
    def kids(b, pages, page_nums):
        mid = b.alloc()
        b.obj(b'<< /Type /Pages /Kids [%d 0 R %d 0 R] /Count 4 >>'
              % (mid, mid), num=pages)
        b.obj(b'<< /Type /Pages /Parent %d 0 R /Kids [%d 0 R %d 0 R] '
              b'/Count 2 >>' % (pages, page_nums[0], page_nums[1]), num=mid)
    data = build_tree(kids)
    expected = [LABELS[0], LABELS[1]] * 2
    assert pdfium_page_texts(data) == expected
    assert pypdf_page_count(data, strict=False) == 4
    reader, warnings = read(data, caplog)
    assert labels_of(reader) == expected
    assert not any('loop' in w for w in warnings)


# -- the catalog and /Kids itself ------------------------------------------

def test_untyped_catalog(caplog):
    def kids(b, pages, page_nums):
        flat()(b, pages, page_nums)
    data = build_tree(kids).replace(b'<< /Type /Catalog /Pages',
                                    b'<< /Pages                ')
    reader, _ = read(data, caplog)
    assert labels_of(reader) == LABELS


def test_kids_not_an_array(caplog):
    def kids(b, pages, page_nums):
        b.obj(b'<< /Type /Pages /Kids %d 0 R /Count 1 >>' % page_nums[0],
              num=pages)
    reader, warnings = read(build_tree(kids), caplog)
    assert reader.pages == []
    assert any('not an array' in w for w in warnings)


@pytest.mark.parametrize('pages_ref', [b'99 0 R', b'5'])
def test_catalog_pages_missing(pages_ref, caplog):
    def kids(b, pages, page_nums):
        flat()(b, pages, page_nums)
    data = build_tree(kids)
    marker = b'/Type /Catalog /Pages '
    start = data.index(marker) + len(marker)
    end = data.index(b'>>', start)
    data = (data[:start] + pages_ref.ljust(end - start - 1) +
            data[end - 1:])
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger='pdfrw'):
        reader = PdfReader(fdata=data)
    assert reader.pages == []
    assert any('catalog /Pages' in r.getMessage() for r in caplog.records)


# -- remove_page (upstream PR #221) ----------------------------------------

def nested_tree(npages=5):
    """Pages 1..npages in a three-level tree: root -> [p1, A], A -> [B, pN],
    B -> [p2 .. pN-1]."""
    labels = [page_label(i) for i in range(npages)]
    b = PdfBuilder()
    catalog, root, mid, low, font = (b.alloc() for _ in range(5))
    page_nums = [b.alloc() for _ in labels]
    parents = [root] + [low] * (npages - 2) + [mid]
    contents = [b.stream(page_content(label)) for label in labels]
    b.obj(b'<< /Type /Catalog /Pages %d 0 R >>' % root, num=catalog)
    b.obj(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
          num=font)
    for num, content, parent in zip(page_nums, contents, parents):
        b.obj(b'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] '
              b'/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>'
              % (parent, font, content), num=num)
    b.obj(b'<< /Type /Pages /Kids [%d 0 R %d 0 R] /Count %d >>'
          % (page_nums[0], mid, npages), num=root)
    b.obj(b'<< /Type /Pages /Parent %d 0 R /Kids [%d 0 R %d 0 R] '
          b'/Count %d >>' % (root, low, page_nums[-1], npages - 1), num=mid)
    refs = b' '.join(b'%d 0 R' % n for n in page_nums[1:-1])
    b.obj(b'<< /Type /Pages /Parent %d 0 R /Kids [' % mid + refs +
          b'] /Count %d >>' % (npages - 2), num=low)
    b.xref_table(b'/Root %d 0 R' % catalog)
    return b.getvalue(), labels


def test_remove_page_flat():
    """What the upstream PR handled: a single flat /Kids."""
    reader = PdfReader(fdata=make_pdf(3))
    pages = reader.pages
    assert reader.remove_page(1) is reader
    assert labels_of(reader) == [LABELS[0], LABELS[2]]
    assert reader.pages is pages
    assert reader.numPages == 2
    assert reader.Root.Pages.Count == '2'
    assert_valid(copy_via_trailer(reader), texts=[LABELS[0], LABELS[2]])


@pytest.mark.parametrize('index', [0, 1, 2, 3, 4, -1, -5])
def test_remove_page_nested(index):
    data, labels = nested_tree()
    assert_valid(data, texts=labels)
    reader = PdfReader(fdata=data)
    expected = list(labels)
    del expected[index]
    reader.remove_page(index)
    assert labels_of(reader) == expected
    assert reader.numPages == 4
    root = reader.Root.Pages
    assert root.Count == '4'
    assert_valid(copy_via_trailer(reader), texts=expected)


def test_remove_pages_until_empty_prunes_nodes():
    data, labels = nested_tree()
    reader = PdfReader(fdata=data)
    for _ in range(3):
        reader.remove_page(1)       # Empties B, then removes it from A.
    assert labels_of(reader) == [labels[0], labels[4]]
    mid = reader.Root.Pages.Kids[1]
    assert len(mid.Kids) == 1 and mid.Count == '1'
    assert_valid(copy_via_trailer(reader), texts=[labels[0], labels[4]])
    reader.remove_page(1)           # Empties A too.
    assert len(reader.Root.Pages.Kids) == 1
    assert_valid(copy_via_trailer(reader), texts=[labels[0]])


def test_remove_page_shared_subtree(caplog):
    """A page under a /Pages node listed twice goes from both places,
    and both /Counts above it are fixed."""
    def kids(b, pages, page_nums):
        mid, left, right = b.alloc(), b.alloc(), b.alloc()
        b.obj(b'<< /Type /Pages /Kids [%d 0 R %d 0 R] /Count 4 >>'
              % (left, right), num=pages)
        for node in (left, right):
            b.obj(b'<< /Type /Pages /Parent %d 0 R /Kids [%d 0 R] '
                  b'/Count 2 >>' % (pages, mid), num=node)
        b.obj(b'<< /Type /Pages /Parent %d 0 R /Kids [%d 0 R %d 0 R] '
              b'/Count 2 >>' % (left, page_nums[0], page_nums[1]), num=mid)
    reader, _ = read(build_tree(kids), caplog)
    reader.remove_page(0)
    assert labels_of(reader) == [LABELS[1], LABELS[1]]
    left, right = reader.Root.Pages.Kids
    assert (left.Count, right.Count, reader.Root.Pages.Count) == \
        ('1', '1', '2')
    data = copy_via_trailer(reader)
    assert pdfium_page_texts(data) == [LABELS[1], LABELS[1]]
    assert pypdf_page_count(data) == 2


@pytest.mark.parametrize('index', [3, -4])
def test_remove_page_out_of_range(index):
    reader = PdfReader(fdata=make_pdf(3))
    with pytest.raises(IndexError):
        reader.remove_page(index)
    assert reader.numPages == 3


def test_remove_page_tree_changed_after_reading():
    reader = PdfReader(fdata=make_pdf(3))
    reader.Root.Pages.Kids.reverse()
    with pytest.raises(ValueError):
        reader.remove_page(0)
