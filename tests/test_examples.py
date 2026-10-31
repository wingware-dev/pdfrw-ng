# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""The scripts in examples/, run as a user runs them.

Each test writes generated input into a temporary directory, runs the
script there in a subprocess (`python examples/<script> ...`) with the
working tree's pdfrw first on the path, and checks the output file:
validity with qpdf, pypdf and PDFium (`validate.assert_valid`) and page
order with PDFium text.

Text is read only inside each page's (or each half page's) box, so text
that a script crops away does not count.  Generated pages show
"Page N" near the top left of a 612x792 page.
"""

import os
import subprocess
import sys

import pytest

from .pdfgen import make_pdf, page_label
from .validate import assert_valid, require

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, 'examples')

WIDTH, HEIGHT = 612, 792


def labels(*numbers):
    return [page_label(n - 1) for n in numbers]


def run_example(script, args, cwd, ok=True):
    """Run examples/`script` with `args` in `cwd`; return the result.

    With `ok`, a nonzero exit fails the test, showing the output.
    """
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(
        [ROOT] + [p for p in [env.get('PYTHONPATH')] if p])
    result = subprocess.run(
        [sys.executable, '-W', 'error', os.path.join(EXAMPLES, script)]
        + [str(a) for a in args],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120)
    if ok:
        assert result.returncode == 0, (
            '%s %s exited %d\nstdout:\n%s\nstderr:\n%s' % (
                script, ' '.join(map(str, args)), result.returncode,
                result.stdout, result.stderr))
    return result


def assert_refused(result, message):
    """The script exited with an error message, not a traceback."""
    assert result.returncode != 0
    assert message in result.stderr, result.stderr
    assert 'Traceback' not in result.stderr, result.stderr


@pytest.fixture
def work(tmp_path):
    """A directory with input files in.pdf (N pages) made on demand."""
    class Work(object):
        path = tmp_path

        def pdf(self, npages, name=None):
            name = name or 'p%d.pdf' % npages
            (tmp_path / name).write_bytes(make_pdf(npages))
            return name

        def read(self, name):
            return (tmp_path / name).read_bytes()

        def run(self, script, *args, **kw):
            return run_example(script, args, tmp_path, **kw)
    return Work()


def page_layout(data):
    """Each page's width and text, read inside the page's box.

    A page wider than it is tall is a two-up sheet: its entry is
    (width, left half text, right half text).  Others are (width, text).
    """
    pdfium = require('pypdfium2')
    doc = pdfium.PdfDocument(data)
    try:
        result = []
        for index in range(len(doc)):
            page = doc[index]
            width, height = page.get_size()
            text = page.get_textpage()
            if width > height:
                result.append((
                    round(width),
                    text.get_text_bounded(0, 0, width / 2, height).strip(),
                    text.get_text_bounded(width / 2, 0, width,
                                          height).strip()))
            else:
                result.append((
                    round(width),
                    text.get_text_bounded(0, 0, width, height).strip()))
            text.close()
            page.close()
        return result
    finally:
        doc.close()


def page_texts(data):
    return [entry[1] for entry in page_layout(data)]


def sheet(left, right):
    """A two-up sheet: page numbers (or None for blank) per half."""
    return (2 * WIDTH, page_label(left - 1) if left else '',
            page_label(right - 1) if right else '')


def single(number):
    return (WIDTH, page_label(number - 1))


# -- examples/*.py -------------------------------------------------------

def quadrant_texts(data):
    """Per page, the text in its top left, top right, bottom left and
    bottom right quarters."""
    pdfium = require('pypdfium2')
    doc = pdfium.PdfDocument(data)
    try:
        result = []
        for index in range(len(doc)):
            page = doc[index]
            width, height = page.get_size()
            text = page.get_textpage()
            result.append([
                text.get_text_bounded(x, y, x + width / 2,
                                      y + height / 2).strip()
                for y in (height / 2, 0) for x in (0, width / 2)])
            text.close()
            page.close()
        return result
    finally:
        doc.close()


def test_4up(work):
    work.run('4up.py', work.pdf(8))
    data = work.read('4up.p8.pdf')
    assert_valid(data, pages=2)
    assert quadrant_texts(data) == [labels(1, 2, 3, 4), labels(5, 6, 7, 8)]


def test_alter(work):
    """No /Info dictionary in the input used to crash the script."""
    work.run('alter.py', work.pdf(3))
    data = work.read('alter.p3.pdf')
    assert_valid(data, texts=labels(1, 2, 3))
    pikepdf = require('pikepdf')
    with pikepdf.open(work.path / 'alter.p3.pdf') as pdf:
        assert str(pdf.docinfo.Title) == 'My New Title Goes Here'


@pytest.mark.parametrize('npages, padding, expected', [
    # One page used to crash
    (1, False, [single(1)]),
    (1, True, [sheet(None, 1), sheet(None, None)]),
    (2, False, [single(1), single(2)]),
    # With padding, page 2 used to land on the right half
    (2, True, [sheet(None, 1), sheet(2, None)]),
    (3, False, [sheet(None, 1), sheet(2, 3)]),
    # 2 mod 4 without padding: the middle leaf keeps the original size
    (6, False, [sheet(6, 1), sheet(2, 5), single(3), single(4)]),
    (6, True, [sheet(None, 1), sheet(2, None), sheet(6, 3), sheet(4, 5)]),
    (7, False, [sheet(None, 1), sheet(2, 7), sheet(6, 3), sheet(4, 5)]),
    (8, False, [sheet(8, 1), sheet(2, 7), sheet(6, 3), sheet(4, 5)]),
])
def test_booklet(work, npages, padding, expected):
    args = ['-p'] if padding else []
    work.run('booklet.py', *(args + [work.pdf(npages)]))
    data = work.read('booklet.p%d.pdf' % npages)
    assert_valid(data, pages=len(expected))
    assert page_layout(data) == expected


def test_cat(work):
    work.run('cat.py', work.pdf(3), work.pdf(2))
    data = work.read('cat.p3.pdf')
    assert_valid(data, texts=labels(1, 2, 3, 1, 2))


def test_extract(work):
    work.run('4up.py', work.pdf(8))
    work.run('extract.py', '4up.p8.pdf')
    data = work.read('extract.4up.p8.pdf')
    assert_valid(data)
    assert page_texts(data) == labels(*range(1, 9))


def test_extract_without_xobjects(work):
    """A file with no XObjects used to end in an IndexError traceback."""
    result = work.run('extract.py', work.pdf(3), ok=False)
    assert_refused(result, 'No Form or Image XObjects found in p3.pdf')
    assert not (work.path / 'extract.p3.pdf').exists()


@pytest.mark.parametrize('script', ['watermark.py', 'fancy_watermark.py'])
@pytest.mark.parametrize('underneath', [False, True])
def test_watermark(work, script, underneath):
    work.pdf(1, 'mark.pdf')
    args = ['-u'] if underneath else []
    work.run(script, *(args + [work.pdf(3), 'mark.pdf']))
    data = work.read('watermark.p3.pdf')
    # The watermark ("Page 1") is drawn over or under each page
    assert_valid(data, pages=3)
    texts = page_texts(data)
    for number, text in enumerate(texts, 1):
        words = text.split()
        assert len(words) == 4 and words.count('Page') == 2
        assert sorted(words[1::2]) == sorted(['1', str(number)]), text


def test_poster(work):
    work.run('poster.py', work.pdf(3))
    data = work.read('poster.p3.pdf')
    assert_valid(data, pages=1)
    pikepdf = require('pikepdf')
    with pikepdf.open(work.path / 'poster.p3.pdf') as pdf:
        box = [float(x) for x in pdf.pages[0].mediabox]
    # 0.5" margins cropped, then scaled by 4.8
    assert box == [0, 0, (WIDTH - 72) * 4.8, (HEIGHT - 72) * 4.8]
    assert page_texts(data) == labels(1)


def test_print_two(work):
    work.run('print_two.py', work.pdf(4))
    data = work.read('print_two.p4.pdf')
    assert_valid(data, pages=4)
    for number, (width, left, right) in enumerate(page_layout(data), 1):
        assert width == 2 * WIDTH
        assert left == right == page_label(number - 1)


@pytest.mark.parametrize('rotation, ranges, expected', [
    ('90', [], [90, 90, 90]),
    ('90', ['1', '3'], [90, 0, 90]),
    ('270', ['2-3'], [0, 270, 270]),
    ('180', ['3-2'], [0, 180, 180]),
])
def test_rotate(work, rotation, ranges, expected):
    work.run('rotate.py', work.pdf(3), rotation, *ranges)
    data = work.read('rotate.p3.pdf')
    assert_valid(data, texts=labels(1, 2, 3))
    pikepdf = require('pikepdf')
    with pikepdf.open(work.path / 'rotate.p3.pdf') as pdf:
        assert [int(page.obj.get('/Rotate', 0)) for page in pdf.pages] \
            == expected


@pytest.mark.parametrize('args, message', [
    # Page 0 used to rotate the last page
    (['90', '0'], 'Page 0 is out of range: pages are numbered 1 to 3'),
    (['90', '4'], 'Page 4 is out of range'),
    (['45'], 'Rotation must be a multiple of 90 degrees'),
    (['90', 'x'], "Bad page range 'x'"),
])
def test_rotate_refuses(work, args, message):
    result = work.run('rotate.py', work.pdf(3), *args, ok=False)
    assert_refused(result, message)
    assert not (work.path / 'rotate.p3.pdf').exists()


@pytest.mark.parametrize('ranges, expected', [
    (['2'], [2]),
    (['1-3', '1'], [1, 2, 3, 1]),
    (['3-1', '2'], [3, 2, 1, 2]),
])
def test_subset(work, ranges, expected):
    work.run('subset.py', work.pdf(3), *ranges)
    data = work.read('subset.p3.pdf')
    assert_valid(data, texts=labels(*expected))


@pytest.mark.parametrize('ranges, message', [
    # Page 0 used to give the last page
    (['0'], 'Page 0 is out of range: pages are numbered 1 to 3'),
    (['2-4'], 'Page 4 is out of range'),
    (['1-2-3'], "Bad page range '1-2-3'"),
])
def test_subset_refuses(work, ranges, message):
    result = work.run('subset.py', work.pdf(3), *ranges, ok=False)
    assert_refused(result, message)
    assert not (work.path / 'subset.p3.pdf').exists()


@pytest.mark.parametrize('npages, expected', [
    (1, [sheet(None, 1)]),
    (3, [sheet(None, 1), sheet(2, 3)]),
    # One 20-page booklet, then a 6-page one
    (26, [sheet(20, 1), sheet(2, 19), sheet(18, 3), sheet(4, 17),
          sheet(16, 5), sheet(6, 15), sheet(14, 7), sheet(8, 13),
          sheet(12, 9), sheet(10, 11),
          sheet(26, 21), sheet(22, 25), sheet(24, 23)]),
])
def test_subset_booklets(work, npages, expected):
    """Used to be Python 2 only (print statements)."""
    result = work.run('subset_booklets.py', work.pdf(npages))
    assert 'has %d pages' % npages in result.stdout
    data = work.read('subset_booklets.p%d.pdf' % npages)
    assert_valid(data, pages=len(expected))
    assert page_layout(data) == expected


def test_unspread(work):
    work.run('booklet.py', work.pdf(4))
    work.run('unspread.py', 'booklet.p4.pdf')
    data = work.read('unspread.booklet.p4.pdf')
    assert_valid(data, pages=4)
    assert page_layout(data) == [single(4), single(1), single(2),
                                 single(3)]


# -- examples/rl1 (reportlab) --------------------------------------------

@pytest.fixture
def reportlab():
    return require('reportlab')


def test_rl1_4up(work, reportlab):
    work.run('rl1/4up.py', work.pdf(8))
    data = work.read('4up.p8.pdf')
    assert_valid(data, pages=2)
    assert quadrant_texts(data) == [labels(1, 2, 3, 4), labels(5, 6, 7, 8)]


@pytest.mark.parametrize('npages, expected', [
    (1, [single(1)]),
    # The generated pages differ only in their content streams, which
    # compared equal, so the script took page 3 for the blank back of
    # page 2 and dropped it
    (3, [sheet(None, 1), sheet(2, 3)]),
    (4, [sheet(4, 1), sheet(2, 3)]),
    (6, [sheet(6, 1), sheet(2, 5), single(3), single(4)]),
])
def test_rl1_booklet(work, reportlab, npages, expected):
    work.run('rl1/booklet.py', work.pdf(npages))
    data = work.read('booklet.p%d.pdf' % npages)
    assert_valid(data, pages=len(expected))
    assert page_layout(data) == expected


def test_rl1_platypus_pdf_template(work, reportlab):
    work.run('rl1/platypus_pdf_template.py', work.pdf(2))
    data = work.read('platypus_pdf_template.p2.pdf')
    assert_valid(data)
    texts = page_texts(data)
    assert len(texts) > 1
    # Page 1 of the source is the background of every page
    assert all(text.startswith('Page 1') for text in texts), texts
    assert 'Hello World199' in texts[-1]


@pytest.mark.parametrize('args, expected', [
    # The last page used to be required
    (['2'], [2]),
    (['2', '3'], [2, 3]),
])
def test_rl1_subset(work, reportlab, args, expected):
    work.run('rl1/subset.py', work.pdf(3), *args)
    data = work.read('subset.p3.pdf')
    assert_valid(data, texts=labels(*expected))


@pytest.mark.parametrize('args, message', [
    (['0', '1'], 'Bad page range 0-1: pages are numbered 1 to 3'),
    (['3', '2'], 'Bad page range 3-2'),
    ([], 'usage:'),
])
def test_rl1_subset_refuses(work, reportlab, args, message):
    result = work.run('rl1/subset.py', work.pdf(3), *args, ok=False)
    assert_refused(result, message)


# -- examples/rl2 (reportlab) --------------------------------------------

def test_rl2_copy(work, reportlab):
    """Upstream #218: the script was named copy.py, so it shadowed the
    standard library's copy module and reportlab failed to import."""
    work.run('rl2/copy_pdf.py', work.pdf(3))
    data = work.read('copy.p3.pdf')
    assert_valid(data, texts=labels(1, 2, 3))


def test_rl2_decodegraphics(work, reportlab):
    """Run as a script it traces each operator; it used inspect.getargspec,
    which Python 3.11 removed."""
    result = work.run('rl2/decodegraphics.py', work.pdf(2))
    assert 'Tj called parse_text_out((Page 2))' in result.stdout
