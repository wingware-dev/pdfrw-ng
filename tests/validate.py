# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Independent checks of PDF bytes, so tests never trust pdfrw alone.

- `pikepdf_problems`: qpdf's syntax check plus anything qpdf logs while
  opening and walking the page tree (repairs, bad page-tree nodes).
- `pypdf_page_count`: page count from pypdf in strict mode.
- `pdfium_page_texts`: the text on each page, rendered by PDFium.
- `assert_valid`: all of the above, with optional expected pages/texts.

When a validator is not installed the test using it is skipped, unless
the environment variable PDFRW_REQUIRE_VALIDATORS is set (CI sets it),
in which case the ImportError fails the test.
"""

import importlib
import io
import logging
import os

import pytest

__all__ = ['pikepdf_problems', 'pypdf_page_count', 'pdfium_page_texts',
           'assert_valid', 'require']


def require(name):
    """Import and return validator module `name`, or skip the test."""
    try:
        return importlib.import_module(name)
    except ImportError:
        if os.environ.get('PDFRW_REQUIRE_VALIDATORS'):
            raise
        pytest.skip('%s is not installed' % name)


class _Collect(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self, logging.WARNING)
        self.messages = []

    def emit(self, record):
        message = record.getMessage().strip()
        if message:
            self.messages.append(message)


def pikepdf_problems(data, password=''):
    """Problems qpdf finds in `data`, as a list of strings (empty = clean).

    Covers xref reconstruction, syntax errors, and page-tree damage that
    qpdf only logs.  A file qpdf cannot open at all gives one entry.
    """
    pikepdf = require('pikepdf')
    handler = _Collect()
    logger = logging.getLogger('pikepdf')
    logger.addHandler(handler)
    try:
        try:
            with pikepdf.open(io.BytesIO(data), password=password) as pdf:
                problems = list(pdf.check_pdf_syntax())
                len(pdf.pages)
                problems.extend(str(w) for w in pdf.get_warnings())
        except pikepdf.PdfError as exc:
            problems = ['cannot open: %s' % exc]
    finally:
        logger.removeHandler(handler)
    return problems + handler.messages


def pypdf_page_count(data, password=None, strict=True):
    """Number of pages pypdf sees.  Strict mode raises on damage."""
    pypdf = require('pypdf')
    reader = pypdf.PdfReader(io.BytesIO(data), strict=strict,
                             password=password)
    return len(reader.pages)


def pdfium_page_texts(data, password=None):
    """The text PDFium extracts from each page, stripped."""
    pdfium = require('pypdfium2')
    doc = pdfium.PdfDocument(data, password=password)
    try:
        texts = []
        for index in range(len(doc)):
            page = doc[index]
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range().strip())
            textpage.close()
            page.close()
        return texts
    finally:
        doc.close()


def assert_valid(data, pages=None, texts=None, password=''):
    """Assert that every validator accepts `data`.

    `pages` is the expected page count; `texts` the expected text of each
    page (which also fixes the count).
    """
    assert data.startswith(b'%PDF-'), 'no %%PDF- header: %r' % data[:20]
    problems = pikepdf_problems(data, password=password)
    assert not problems, 'qpdf found problems: %r' % problems
    count = pypdf_page_count(data, password=password or None)
    found = pdfium_page_texts(data, password=password or None)
    assert count == len(found), \
        'pypdf sees %d pages, PDFium %d' % (count, len(found))
    if texts is not None:
        assert found == list(texts), \
            'page texts %r, expected %r' % (found, list(texts))
    if pages is not None:
        assert count == pages, '%d pages, expected %d' % (count, pages)
