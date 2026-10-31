#!/usr/bin/env python
"""Render the before/after screenshots in docs/shots/.

usage:  python tools/shots.py [--out DIR] [--before-src DIR] [--rev REV]
                              [--only NAME ...] [--no-coverage]

Each shot runs the same small pdfrw program twice in a subprocess: once
against the unmodified upstream import (commit 9fd415d, upstream
6c89216, exported with ``git archive`` into a temporary directory unless
--before-src names one) and once against this working tree.  The input
PDFs come from tests/pdfgen.py.  Pages are rendered with pypdfium2
(PDFium), never with pdfrw, so the pictures show what a real viewer
shows.  Each PNG is captioned and has three rows: the input as PDFium
sees it, upstream pdfrw's output, and this tree's output.  The writer
shots (#135, #147) have no page image to show, so their first row is
the program both versions ran and the others are text panels with what
each run wrote, checked with qpdf (via pikepdf).

The coverage shot runs upstream's offline tests against upstream pdfrw
and this tree's whole suite against this tree, and draws line coverage
per module.

Needs what the project's ``test`` dependency group installs: pypdfium2,
pikepdf (to encrypt a test file), Pillow (which reportlab brings in),
and pytest and pytest-cov for the coverage shot.
"""

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

import pypdfium2
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests import pdfgen  # noqa: E402

BEFORE_REV = '9fd415d'
BEFORE_LABEL = 'Before: upstream pdfrw 0.4+ (6c89216, 2018)'
AFTER_LABEL = 'After: pdfrw-ng (this tree)'
INPUT_LABEL = 'Input, as PDFium shows it'

# Offline upstream tests: the rest need the static_pdfs download
BEFORE_TESTS = ['tests/test_pdfstring.py', 'tests/test_pdfdict.py',
                'tests/test_flate_png.py']

SCALE = 0.25              # 612pt letter page -> 153px wide
MARGIN = 24
GAP = 14
LABEL_W = 300
LINE_H = 21               # text panel line height
BG = (255, 255, 255)
INK = (33, 37, 41)
MUTED = (108, 117, 125)
BAD = (192, 57, 43)
GOOD = (39, 128, 72)
FRAME = (160, 160, 160)
PANEL = (246, 247, 249)


def font(size):
    return ImageFont.load_default(size=size)


def mono_font(size):
    """A monospaced font for code and bytes, else the default font."""
    for name in ('Menlo.ttc', 'DejaVuSansMono.ttf', 'consola.ttf',
                 'LiberationMono-Regular.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return font(size)


# -- running pdfrw ---------------------------------------------------------

class Run(object):
    """The outcome of one subprocess run."""

    def __init__(self, ok, pdf, message, stdout=''):
        self.ok = ok          # exit status 0
        self.pdf = pdf        # output bytes, or None if none was written
        self.message = message  # last stderr line: the error or last log
        self.stdout = stdout


COPY = '''
import sys
from pdfrw import PdfReader, PdfWriter
PdfWriter(sys.argv[2]).addpages(PdfReader(sys.argv[1]).pages).write()
'''


def run_pdfrw(src, workdir, argv, outname):
    """Run `argv` with `src` first on sys.path; return a Run for
    `outname` in `workdir`."""
    env = dict(os.environ)
    env['PYTHONPATH'] = src
    # Upstream's docstrings raise SyntaxWarning on 3.12+ (#170)
    env['PYTHONWARNINGS'] = 'ignore'
    out = os.path.join(workdir, outname)
    if os.path.exists(out):
        os.remove(out)
    proc = subprocess.run([sys.executable] + argv, cwd=workdir, env=env,
                          capture_output=True, text=True)
    pdf = None
    if os.path.exists(out):
        with open(out, 'rb') as f:
            pdf = f.read()
    lines = [x for x in proc.stderr.strip().splitlines() if x.strip()]
    # On failure the exception; on success the last thing pdfrw logged
    message = lines[-1] if lines else ''
    return Run(proc.returncode == 0, pdf, message, proc.stdout.strip())


def copy_with(src, workdir, data, program=COPY):
    """Run `program` (by default a plain PdfReader/PdfWriter copy) with
    pdfrw from `src`, as ``program.py in.pdf out.pdf`` on `data`."""
    with open(os.path.join(workdir, 'in.pdf'), 'wb') as f:
        f.write(data)
    # Not copy.py: that would shadow the standard library's copy module
    with open(os.path.join(workdir, 'pdfrw_program.py'), 'w') as f:
        f.write(program)
    return run_pdfrw(src, workdir,
                     ['pdfrw_program.py', 'in.pdf', 'out.pdf'], 'out.pdf')


# -- rendering -------------------------------------------------------------

def render(data):
    """Render every page of `data` with PDFium; return (images, error)."""
    try:
        doc = pypdfium2.PdfDocument(data)
    except pypdfium2.PdfiumError as exc:
        return [], 'PDFium cannot open it: %s' % exc
    try:
        images = [doc[i].render(scale=SCALE).to_pil().convert('RGB')
                  for i in range(len(doc))]
    finally:
        doc.close()
    return images, None


def page_text(data):
    """The text of each page, extracted by PDFium."""
    doc = pypdfium2.PdfDocument(data)
    try:
        return [doc[i].get_textpage().get_text_range().strip()
                for i in range(len(doc))]
    finally:
        doc.close()


class Row(object):
    """One captioned strip of page thumbnails, a text panel (`lines`,
    drawn in a monospaced font, unwrapped) or an error box."""

    def __init__(self, label, verdict, images=(), error=None, good=None,
                 lines=None):
        self.label = label
        self.verdict = verdict
        self.images = list(images)
        self.error = error
        self.good = good      # True green, False red, None neutral
        self.lines = lines


def run_row(label, run, describe):
    """A Row for pdfrw output `run`; `describe(images, data)` returns
    (verdict, good) for output that PDFium could render."""
    if not run.ok:
        return Row(label, 'Crashed', error=run.message or
                   'exited with an error', good=False)
    if not run.pdf:
        return Row(label, 'Wrote an empty file', error=run.message or
                   'no output', good=False)
    npages = qpdf_page_count(run.pdf)
    if npages == 0:
        error = ('The PDF has no pages (qpdf counts 0), and PDFium '
                 'refuses to open it.')
        if run.message:
            error += '  pdfrw only logged: ' + run.message
        return Row(label, 'Wrote a PDF with 0 pages, exit status 0',
                   error=error, good=False)
    images, error = render(run.pdf)
    if error:
        return Row(label, 'Unreadable output', error=error, good=False)
    verdict, good = describe(images, run.pdf)
    return Row(label, verdict, images, good=good)


def qpdf_page_count(data):
    """The page count qpdf (via pikepdf) reads, or None if it can't."""
    import pikepdf
    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            return len(pdf.pages)
    except pikepdf.PdfError:
        return None


def wrap(draw, text, fnt, width):
    """Split `text` into lines no wider than `width` pixels."""
    lines = []
    for para in text.split('\n'):
        words = para.split()
        line = ''
        for word in words:
            trial = (line + ' ' + word).strip()
            if draw.textlength(trial, font=fnt) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def compose(title, caption, rows, path):
    """Draw `title`, `caption` and `rows` into a PNG at `path`."""
    title_font, text_font, small = font(28), font(17), font(15)
    mono = mono_font(15)
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    thumbs_w = max([sum(im.width for im in r.images) +
                    GAP * max(len(r.images) - 1, 0) for r in rows] +
                   [scratch.textlength(line, font=mono) + 24
                    for r in rows for line in r.lines or ()] + [460])
    width = int(MARGIN * 2 + LABEL_W + thumbs_w)
    cap_lines = wrap(scratch, caption, text_font, width - 2 * MARGIN)

    heights = []
    for r in rows:
        if r.images:
            heights.append(max(im.height for im in r.images) + 22)
        elif r.lines is not None:
            heights.append(max(LINE_H * len(r.lines) + 20, 70))
        else:
            heights.append(90)
    height = (MARGIN + 40 + len(cap_lines) * 23 + 16 +
              sum(h + GAP * 2 for h in heights) + MARGIN)

    img = Image.new('RGB', (width, height), BG)
    draw = ImageDraw.Draw(img)
    y = MARGIN
    draw.text((MARGIN, y), title, font=title_font, fill=INK)
    y += 40
    for line in cap_lines:
        draw.text((MARGIN, y), line, font=text_font, fill=MUTED)
        y += 23
    y += 16

    for r, h in zip(rows, heights):
        draw.line([(MARGIN, y), (width - MARGIN, y)], fill=(222, 226, 230))
        y += GAP
        colour = {True: GOOD, False: BAD, None: INK}[r.good]
        ly = y
        for line in wrap(draw, r.label, text_font, LABEL_W - 20):
            draw.text((MARGIN, ly), line, font=text_font, fill=INK)
            ly += 22
        for line in wrap(draw, r.verdict, text_font, LABEL_W - 20):
            draw.text((MARGIN, ly + 4), line, font=text_font, fill=colour)
            ly += 22
        x = MARGIN + LABEL_W
        if r.images:
            for n, im in enumerate(r.images, 1):
                img.paste(im, (x, y))
                draw.rectangle([x - 1, y - 1, x + im.width, y + im.height],
                               outline=FRAME)
                if im.width > im.height:
                    # A booklet sheet: mark the fold
                    fx = x + im.width // 2
                    for dy in range(0, im.height, 8):
                        draw.line([(fx, y + dy), (fx, y + min(dy + 4,
                                                              im.height))],
                                  fill=FRAME)
                num = 'p. %d' % n
                draw.text((x + (im.width - draw.textlength(num, font=small))
                           / 2, y + im.height + 3), num, font=small,
                          fill=MUTED)
                x += im.width + GAP
        elif r.lines is not None:
            box = [x, y, width - MARGIN, y + h - 6]
            outline = {True: GOOD, False: BAD, None: FRAME}[r.good]
            draw.rectangle(box, fill=PANEL, outline=outline)
            ty = y + 10
            for line in r.lines:
                draw.text((x + 12, ty), line, font=mono, fill=INK)
                ty += LINE_H
        else:
            box = [x, y, width - MARGIN, y + h - 6]
            draw.rectangle(box, fill=(253, 237, 236), outline=BAD)
            ey = y + 10
            for line in wrap(draw, r.error, small, box[2] - x - 24)[:4]:
                draw.text((x + 12, ey), line, font=small, fill=BAD)
                ey += 20
        y += h + GAP
    img.save(path, optimize=True)
    print('wrote', os.path.relpath(path))


def pages_verdict(expected):
    """describe() for output that should have `expected` page texts."""
    def describe(images, data):
        texts = page_text(data)
        n = len(images)
        word = 'page' if n == 1 else 'pages'
        if texts == expected:
            return '%d %s, all correct' % (n, word), True
        if n and not any(texts):
            return '%d %s, all blank' % (n, word), False
        if n != len(expected):
            return '%d %s; expected %d' % (n, word, len(expected)), False
        return '%d %s, wrong content' % (n, word), False
    return describe


# -- the shots -------------------------------------------------------------

def shot_copy(name, title, caption, data, expected, before, out,
              workdir):
    images, _ = render(data)
    rows = [Row(INPUT_LABEL, '%d pages' % len(images), images)]
    for label, src in ((BEFORE_LABEL, before), (AFTER_LABEL, ROOT)):
        run = copy_with(src, workdir, data)
        rows.append(run_row(label, run, pages_verdict(expected)))
    compose(title, caption, rows, os.path.join(out, name + '.png'))


def shot_dangling_kids(before, out, workdir):
    data = pdfgen.make_pdf(3, dangling_kids=1)
    shot_copy(
        'dangling-kids', 'One dangling /Kids reference loses every page',
        'A 3-page file whose /Pages /Kids array also refers to an object '
        'that was never written.  Upstream pdfrw read 0 pages and its '
        'writer silently wrote an empty PDF.  pdfrw-ng skips only the '
        'bad reference, with a warning, as qpdf and PDFium do.  Each '
        'program reads the file with PdfReader and writes its pages '
        'with PdfWriter.',
        data, ['Page 1', 'Page 2', 'Page 3'], before, out, workdir)


def shot_encrypted_copy(before, out, workdir):
    data = pdfgen.encrypt(pdfgen.make_pdf(3), user='', R=4, aes=False)
    shot_copy(
        'encrypted-copy', 'Copying an encrypted PDF wrote blank pages',
        'A 3-page PDF encrypted (RC4, 128-bit) with an empty user '
        'password, which viewers open without asking for one.  Without '
        'decrypt=True, upstream pdfrw copied the still-encrypted '
        'streams into an unencrypted file, so every page came out '
        'blank, with no warning (and decrypt=True raised TypeError on '
        'Python 3, #48).  pdfrw-ng decrypts an empty-password file '
        'automatically.',
        data, ['Page 1', 'Page 2', 'Page 3'], before, out, workdir)


def shot_stale_page_tree(before, out, workdir):
    data = pdfgen.make_updated_pdf(5, [0, 2, 4], xref='stream', objstm=True,
                                   update_xref='stream')
    shot_copy(
        'stale-page-tree', '#121: an incremental update was ignored',
        'A 5-page PDF whose page tree is in an object stream, then an '
        'incremental update that rewrites /Pages to keep pages 1, 3 and '
        '5.  Upstream pdfrw loaded the object stream after merging the '
        'xref sections, so the old page tree overrode the newer one and '
        'deleted pages came back (#121, #177, #188, #223, #237, #181).',
        data, ['Page 1', 'Page 3', 'Page 5'], before, out, workdir)


def shot_booklet(before, out, workdir):
    npages = 6
    with open(os.path.join(workdir, 'six.pdf'), 'wb') as f:
        f.write(pdfgen.make_pdf(npages))
    images, _ = render(pdfgen.make_pdf(npages))
    rows = [Row(INPUT_LABEL, '%d pages' % npages, images)]
    # Sheets in reading order: (left, right) halves, None for blank
    expected = [(None, 1), (2, None), (6, 3), (4, 5)]

    def describe(images, data):
        layout = sheet_layout(data)
        n = len(images)
        if layout == expected:
            return '%d sheets, halves on the correct side' % n, True
        return '%d sheets, halves on the wrong side' % n, False

    for label, src in ((BEFORE_LABEL, before), (AFTER_LABEL, ROOT)):
        script = os.path.join(src, 'examples', 'booklet.py')
        run = run_pdfrw(src, workdir, [script, '-p', 'six.pdf'],
                        'booklet.six.pdf')
        rows.append(run_row(label, run, describe))
    compose(
        'booklet.py -p put pages on the wrong half of the sheet',
        'examples/booklet.py -p on a 6-page file, padded to 8 sides: '
        'sheet 1 should be blank | 1 and sheet 2 should be 2 | blank '
        '(the dashed line is the fold).  Upstream always shifted the '
        'last page on a sheet right by its own width, so page 2, which '
        'belongs on the left half of sheet 2, was printed on the right.  '
        'The fixed script places each half explicitly.',
        rows, os.path.join(out, 'booklet-padding.png'))


def sheet_layout(data):
    """Each page's (left, right) page numbers, read by PDFium."""
    doc = pypdfium2.PdfDocument(data)
    try:
        result = []
        for i in range(len(doc)):
            page = doc[i]
            width = page.get_width()
            text = page.get_textpage()
            halves = [None, None]
            for j in range(text.count_rects()):
                left, _, right, _ = text.get_rect(j)
                words = text.get_text_bounded(left, 0, right, 10000).split()
                for k, word in enumerate(words[:-1]):
                    if word == 'Page' and words[k + 1].isdigit():
                        half = 0 if (left + right) / 2 < width / 2 else 1
                        halves[half] = int(words[k + 1])
            result.append(tuple(halves))
        return result
    finally:
        doc.close()


# -- writer fixes: no page image, so text panels ---------------------------

def program_row(program):
    """A neutral Row listing `program`, the code each version ran."""
    return Row('Program, run with each version as', 'program.py in.pdf '
               'out.pdf on a 3-page file',
               lines=program.strip().splitlines())


def file_facts(run):
    """Text panel lines saying what a run printed and wrote."""
    lines = ['exit status: %s' % ('0' if run.ok else 'error')]
    if run.stdout:
        lines += ['stdout: ' + x for x in run.stdout.splitlines()[-2:]]
    if not run.ok and run.message:
        lines.append('stderr: ' + run.message)
    if run.pdf is None:
        lines.append('out.pdf: not written')
    else:
        npages = qpdf_page_count(run.pdf) if run.pdf else None
        lines.append('out.pdf: %d bytes%s' % (
            len(run.pdf), '' if npages is None else
            ', %d pages (read by qpdf)' % npages))
    return lines


STR_KEY = '''
import sys
from pdfrw import PdfReader, PdfWriter, PdfDict, PdfString
src = PdfReader(sys.argv[1])
try:
    src.Info = PdfDict()
    src.Info.update({'Title': PdfString.encode('x')})  # str key
except Exception as exc:
    print('update() raised %s: %s' % (type(exc).__name__, exc))
PdfWriter(sys.argv[2], trailer=src).write()
'''


def shot_str_key(before, out, workdir):
    data = pdfgen.make_pdf(3)
    rows = [program_row(STR_KEY)]
    for label, src in ((BEFORE_LABEL, before), (AFTER_LABEL, ROOT)):
        run = copy_with(src, workdir, data, STR_KEY)
        intact = (run.ok and bool(run.pdf) and
                  qpdf_page_count(run.pdf) == 3)
        if intact:
            verdict = 'Wrote an intact 3-page file'
            if 'update() raised' in run.stdout:
                verdict = ('update() refused the key at once; ' +
                           verdict[0].lower() + verdict[1:])
        elif run.pdf == b'':
            verdict = 'Crashed mid-write, leaving a 0-byte file'
        else:
            verdict = 'Crashed, or wrote a damaged file'
        rows.append(Row(label, verdict, lines=file_facts(run), good=intact))
    compose(
        '#135: a str dictionary key left a 0-byte file',
        "PdfDict.update() with a plain str key such as 'Title' (instead "
        "of PdfName.Title) was accepted, and the writer only failed on it "
        "halfway through writing, after it had already opened and "
        "truncated out.pdf.  pdfrw-ng's update() and setdefault() reject "
        "such a key at once, and the writer builds the whole file in "
        "memory before it opens the target, so a failed write never "
        "damages it (also #160).",
        rows, os.path.join(out, 'str-key-write.png'))


CR_TITLE = b'a\rb\r\nc'

CR_PROGRAM = '''
import sys
from pdfrw import PdfReader, PdfWriter, IndirectPdfDict, PdfString
src = PdfReader(sys.argv[1])
src.Info = IndirectPdfDict(Title=PdfString.from_bytes(
    b'a\\rb\\r\\nc', bytes_encoding='literal'))
PdfWriter(sys.argv[2], trailer=src).write()
'''


def show_bytes(raw):
    """`raw` with CR and LF bytes made visible as <CR> and <LF>."""
    text = raw.decode('latin-1')
    return text.replace('\r', '<CR>').replace('\n', '<LF>')


def written_title(pdf):
    """The /Title literal string exactly as it appears in the file."""
    match = re.search(rb'/Title\s*(\((?:\\.|[^\\)])*\))', pdf, re.DOTALL)
    return match.group(1) if match else None


def qpdf_title(pdf):
    """The /Info /Title bytes as qpdf (via pikepdf) reads them."""
    import pikepdf
    with pikepdf.open(io.BytesIO(pdf)) as doc:
        return bytes(doc.trailer.Info.Title)


def shot_cr_in_strings(before, out, workdir):
    data = pdfgen.make_pdf(3)
    rows = [program_row(CR_PROGRAM)]
    for label, src in ((BEFORE_LABEL, before), (AFTER_LABEL, ROOT)):
        run = copy_with(src, workdir, data, CR_PROGRAM)
        if not run.ok or not run.pdf:
            rows.append(Row(label, 'Crashed', lines=file_facts(run),
                            good=False))
            continue
        read = qpdf_title(run.pdf)
        good = read == CR_TITLE
        if good:
            verdict = 'The Title reads back unchanged'
        elif read == CR_TITLE.replace(b'\r\n', b'\n').replace(b'\r', b'\n'):
            verdict = 'Every CR came back as LF'
        else:
            verdict = 'The Title came back changed'
        lines = [
            'title set:     ' + show_bytes(CR_TITLE),
            'in out.pdf:    /Title ' + show_bytes(written_title(run.pdf)),
            'qpdf reads:    ' + show_bytes(read),
        ]
        rows.append(Row(label, verdict, lines=lines, good=good))
    compose(
        '#147: CR in a string was written raw and read back as LF',
        'A PDF reader must read an unescaped CR or CR LF inside a literal '
        'string as a single LF (PDF 32000-1, 7.3.4.2).  Upstream pdfrw '
        'wrote CR bytes into literal strings unescaped, so any string '
        'holding one, such as a title or form field value, changed on '
        'the round trip.  pdfrw-ng writes CR as the escape \\r.  '
        '<CR> and <LF> below stand for the raw bytes.',
        rows, os.path.join(out, 'cr-in-strings.png'))


# -- coverage --------------------------------------------------------------

def measure(src, tests, report):
    """Run `tests` in `src` under coverage; return the JSON report."""
    env = dict(os.environ)
    env['PYTHONPATH'] = src
    env['PYTHONWARNINGS'] = 'ignore'
    # Keep the .coverage data file out of the source tree
    env['COVERAGE_FILE'] = report + '.data'
    cmd = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
           '-W', 'ignore', '--cov=pdfrw', '--cov-report=json:' + report]
    proc = subprocess.run(cmd + tests, cwd=src, env=env,
                          capture_output=True, text=True)
    if not os.path.exists(report):
        sys.exit('coverage run in %s failed:\n%s%s'
                 % (src, proc.stdout[-2000:], proc.stderr[-2000:]))
    summary = proc.stdout.strip().splitlines()[-1:] or ['']
    with open(report) as f:
        return json.load(f), summary[0].strip('= ')


def line_coverage(report):
    """{module: (covered, statements)} plus a 'TOTAL' entry."""
    result = {}
    for path, data in report['files'].items():
        mod = path.replace(os.sep, '/').split('pdfrw/', 1)[-1]
        if mod.startswith('objects/'):
            mod = 'objects/*'
        s = data['summary']
        cov, num = result.get(mod, (0, 0))
        result[mod] = (cov + s['covered_lines'], num + s['num_statements'])
    t = report['totals']
    result['TOTAL'] = (t['covered_lines'], t['num_statements'])
    return result


def shot_coverage(before, out, workdir):
    before_rep, before_sum = measure(
        before, BEFORE_TESTS, os.path.join(workdir, 'before.json'))
    after_rep, after_sum = measure(
        ROOT, ['tests'], os.path.join(workdir, 'after.json'))
    b, a = line_coverage(before_rep), line_coverage(after_rep)
    mods = sorted(set(b) | set(a), key=lambda m: (m == 'TOTAL', m))

    def pct(cov):
        return 100.0 * cov[0] / cov[1] if cov and cov[1] else 0.0

    title_font, text_font, small = font(28), font(17), font(15)
    bar_w, row_h, name_w = 520, 46, 190
    width = MARGIN * 2 + name_w + bar_w + 90
    height = MARGIN * 2 + 150 + row_h * len(mods) + 40
    img = Image.new('RGB', (width, height), BG)
    draw = ImageDraw.Draw(img)
    y = MARGIN
    draw.text((MARGIN, y), 'Line coverage of pdfrw/, by module',
              font=title_font, fill=INK)
    y += 40
    caption = ('Grey: upstream pdfrw with its offline tests (%s).  '
               'Green: pdfrw-ng with its whole suite (%s), which builds '
               'its own PDFs and runs offline.'
               % (before_sum, after_sum))
    for line in wrap(draw, caption, text_font, width - 2 * MARGIN):
        draw.text((MARGIN, y), line, font=text_font, fill=MUTED)
        y += 23
    y = MARGIN + 150
    x0 = MARGIN + name_w
    for mod in mods:
        if mod == 'TOTAL':
            draw.line([(MARGIN, y - 6), (width - MARGIN, y - 6)], fill=FRAME)
        draw.text((MARGIN, y + 10), mod, font=text_font, fill=INK)
        for k, (cov, colour) in enumerate(((b.get(mod), (173, 181, 189)),
                                           (a.get(mod), GOOD))):
            by = y + 4 + k * 19
            draw.rectangle([x0, by, x0 + bar_w, by + 15], fill=PANEL)
            if cov is None:
                draw.text((x0 + 6, by), 'not in this version', font=small,
                          fill=MUTED)
                continue
            p = pct(cov)
            draw.rectangle([x0, by, x0 + bar_w * p / 100, by + 15],
                           fill=colour)
            draw.text((x0 + bar_w + 8, by - 1), '%3.0f%%' % p, font=small,
                      fill=INK)
        y += row_h
    path = os.path.join(out, 'coverage.png')
    img.save(path, optimize=True)
    print('wrote', os.path.relpath(path))


# -- main ------------------------------------------------------------------

SHOTS = {
    'dangling-kids': shot_dangling_kids,
    'encrypted-copy': shot_encrypted_copy,
    'stale-page-tree': shot_stale_page_tree,
    'booklet-padding': shot_booklet,
    'str-key-write': shot_str_key,
    'cr-in-strings': shot_cr_in_strings,
    'coverage': shot_coverage,
}


def export_rev(rev, dest):
    """Write the tree of commit `rev` into `dest` without touching the
    working copy or its history."""
    data = subprocess.run(['git', 'archive', '--format=tar', rev],
                          cwd=ROOT, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter='data')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', default=os.path.join(ROOT, 'docs', 'shots'),
                        help='output directory (default docs/shots)')
    parser.add_argument('--before-src',
                        help='an existing checkout of the "before" code; '
                        'default: export --rev to a temporary directory')
    parser.add_argument('--rev', default=BEFORE_REV,
                        help='commit with the "before" code (default %s)'
                        % BEFORE_REV)
    parser.add_argument('--only', nargs='+', choices=sorted(SHOTS),
                        help='render only these shots')
    parser.add_argument('--no-coverage', action='store_true',
                        help='skip the coverage shot, which runs the suite')
    args = parser.parse_args()

    names = args.only or sorted(SHOTS)
    if args.no_coverage and 'coverage' in names:
        names.remove('coverage')
    os.makedirs(args.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='pdfrw-shots-')
    try:
        before = args.before_src
        if before is None:
            before = os.path.join(tmp, 'before')
            export_rev(args.rev, before)
        before = os.path.abspath(before)
        for name in names:
            workdir = os.path.join(tmp, name)
            os.mkdir(workdir)
            SHOTS[name](before, os.path.abspath(args.out), workdir)
    finally:
        shutil.rmtree(tmp)


if __name__ == '__main__':
    main()
