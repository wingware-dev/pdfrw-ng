==================
pdfrw-ng 0.5.0
==================

:Author: Patrick Maupin and the pdfrw contributors (see Credits_)

**pdfrw-ng** is a maintained fork of `pdfrw`__, the pure-Python PDF
reader and writer written by Patrick Maupin.  Upstream pdfrw's last
release was 0.4 (September 2017) and its last commit was in February
2018.  This fork brings it up to date with current Python and fixes
bugs reported upstream, keeping the public API compatible: existing
code only has to change the package it installs.  The import name is
still ``pdfrw``.

__ https://github.com/pmaupin/pdfrw

.. contents::
    :backlinks: none

.. sectnum::

Installation
============

pdfrw-ng **is not published on PyPI**.  Install it from a copy of
this source tree.

Because the import name is still ``pdfrw``, pdfrw-ng cannot be
installed alongside upstream ``pdfrw`` or the separate ``pdfrw2``
fork: they would overwrite each other's files.  Uninstall them first:

.. code-block:: bash

    $ pip uninstall pdfrw pdfrw2
    $ cd path/to/pdfrw-ng
    $ pip install .

To read or write encrypted PDFs that use AES, also install the optional
``crypto`` extra, which pulls in pycryptodome:

.. code-block:: bash

    $ pip install ".[crypto]"

pdfrw-ng has no other runtime dependencies.  It uses `reportlab`_
only in the examples and modules that work with reportlab.

Supported Python versions
-------------------------

pdfrw-ng requires Python 3.11 or later.  It is tested on CPython 3.11,
3.12, 3.13, 3.14 and 3.15 and on PyPy 3.11, on Linux, macOS and
Windows.  Python 2 and older Python 3 versions are no longer
supported; use upstream pdfrw 0.4 for those.

What changed from pdfrw 0.4
---------------------------

* Packaging moved to ``pyproject.toml``, and the distribution is named
  ``pdfrw-ng``.  The version is 0.5.0.
* The test suite runs offline.  Tests build their own PDFs instead of
  using the external static_pdfs collection, and check pdfrw's output
  with independent tools (qpdf through pikepdf, pypdf, and PDFium
  through pypdfium2), not only by reading it back with pdfrw.
* Bugs reported on the upstream issue tracker are being fixed, each
  with a regression test.  They include reading files that pdfrw
  misread or lost pages from, writing files that were broken or
  incomplete, encrypted files, and fixes to the examples.

`CHANGELOG.md`__ lists each change, with the upstream issue number it
fixes.

__ CHANGELOG.md

Before and after
----------------

These pictures compare upstream pdfrw 0.4 with pdfrw-ng on the same
generated input.  Pages are rendered with PDFium, not pdfrw, so they
show what a viewer shows.  ``tools/shots.py`` regenerates them.

* `Dangling page-tree reference`__: one bad ``/Kids`` entry no longer
  loses every page.
* `Incremental update`__: the current page tree is read, not a stale
  one from an older revision (#121).
* `Encrypted file`__: a copy is decrypted instead of having blank
  pages (#116).
* `Booklet padding`__: ``booklet.py -p`` puts each page on the right
  half sheet.
* `str key in a PdfDict`__: the error comes when the key is set, and
  an existing file is not truncated (#135).
* `Carriage return in a string`__: it survives a copy (#147).
* `Test coverage`__ of ``pdfrw/`` by module: 28% upstream, 90%
  (87% with branch coverage) in pdfrw-ng.

__ docs/shots/dangling-kids.png
__ docs/shots/stale-page-tree.png
__ docs/shots/encrypted-copy.png
__ docs/shots/booklet-padding.png
__ docs/shots/str-key-write.png
__ docs/shots/cr-in-strings.png
__ docs/shots/coverage.png

About the name
--------------

The fork needs its own distribution name, since ``pdfrw`` belongs to
the upstream project and ``pdfrw2`` is taken by another fork.  Other
free names considered were ``pdfrw-next``, ``pdfrw-community`` and
``pdfrw3``.

Introduction
============

**pdfrw** is a Python library and utility that reads and writes PDF files:

* Operations include subsetting, merging, rotating, modifying metadata, etc.
* The fastest pure Python PDF parser available
* Has been used for years by a printer in pre-press production
* Can be used with rst2pdf to faithfully reproduce vector images
* Can be used either standalone, or in conjunction with `reportlab`_
  to reuse existing PDFs in new ones
* Permissively licensed

.. _reportlab: https://www.reportlab.com/opensource/


pdfrw will faithfully reproduce vector formats without
rasterization, so the rst2pdf package has used pdfrw
for PDF and SVG images by default since March 2010.

pdfrw can also be used in conjunction with reportlab, in order
to re-use portions of existing PDFs in new PDFs created with
reportlab.


Examples
=========

The library comes with several examples that show operation both with
and without reportlab.


All examples
------------------

The examples directory has a few scripts which use the library.
Note that if these examples do not work with your PDF, you should
try to use pdftk or qpdf to uncompress and/or unencrypt them first.
The examples whose names start with ``rl1/`` or ``rl2/`` also need
reportlab (``pip install reportlab``).

* `4up.py`__ will shrink pages down and place 4 of them on
  each output page.
* `6up.py`__ and `9up.py`__ do the same with 6 (two across, three
  down) or 9 (three by three) pages per output page.
* `alter.py`__ shows an example of modifying metadata, without
  altering the structure of the PDF.
* `booklet.py`__ shows an example of creating a 2-up output
  suitable for printing and folding (e.g. on tabloid size paper).
* `cat.py`__ shows an example of concatenating multiple PDFs together.
* `extract.py`__ will extract images and Form XObjects (embedded pages)
  from existing PDFs to make them easier to use and refer to from
  new PDFs (e.g. with reportlab or rst2pdf).
* `poster.py`__ increases the size of a PDF so it can be printed
  as a poster.
* `print_two.py`__ Allows creation of 8.5 X 5.5" booklets by slicing
  8.5 X 11" paper apart after printing.
* `rotate.py`__ Rotates all or selected pages in a PDF.
* `subset.py`__ Creates a new PDF with only a subset of pages from the
  original.
* `unspread.py`__ Takes a 2-up PDF, and splits out pages.
* `watermark.py`__ Adds a watermark PDF image over or under all the pages
  of a PDF.
* `rl1/4up.py`__ Another 4up example, using reportlab canvas for output.
* `rl1/booklet.py`__ Another booklet example, using reportlab canvas for
  output.
* `rl1/subset.py`__ Another subsetting example, using reportlab canvas for
  output.
* `rl1/platypus_pdf_template.py`__ Another watermarking example, using
  reportlab canvas and generated output for the document.  Contributed
  by user asannes.
* `rl2`__ Experimental code for parsing graphics.  Needs work.
* `subset_booklets.py`__ shows an example of creating a full printable pdf
  version in a more professional and practical way ( take a look at
  http://www.wikihow.com/Bind-a-Book )

__ examples/4up.py
__ examples/6up.py
__ examples/9up.py
__ examples/alter.py
__ examples/booklet.py
__ examples/cat.py
__ examples/extract.py
__ examples/poster.py
__ examples/print_two.py
__ examples/rotate.py
__ examples/subset.py
__ examples/unspread.py
__ examples/watermark.py
__ examples/rl1/4up.py
__ examples/rl1/booklet.py
__ examples/rl1/subset.py
__ examples/rl1/platypus_pdf_template.py
__ examples/rl2/
__ examples/subset_booklets.py

Notes on selected examples
------------------------------------

Reorganizing pages and placing them two-up
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A printer with a fancy printer and/or a full-up copy of Acrobat can
easily turn your small PDF into a little booklet (for example, print 4
letter-sized pages on a single 11" x 17").

But that assumes several things, including that the personnel know how
to operate the hardware and software. `booklet.py`__ lets you turn your PDF
into a preformatted booklet, to give them fewer chances to mess it up.

__ examples/booklet.py

Adding or modifying metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The `cat.py`__ example will accept multiple input files on the command
line, concatenate them and output them to output.pdf, after adding some
nonsensical metadata to the output PDF file.

__ examples/cat.py

The `alter.py`__ example alters a single metadata item in a PDF,
and writes the result to a new PDF.

__ examples/alter.py


One difference is that, since **cat** is creating a new PDF structure,
and **alter** is attempting to modify an existing PDF structure, the
PDF produced by alter (and also by watermark.py) *should* be
more faithful to the original (except for the desired changes).

For example, the alter.py navigation should be left intact, whereas with
cat.py it will be stripped.


Rotating and doubling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you ever want to print something that is like a small booklet, but
needs to be spiral bound, you either have to do some fancy rearranging,
or just waste half your paper.

The `print_two.py`__ example program will, for example, make two side-by-side
copies each page of your PDF on each output sheet.

__ examples/print_two.py

But, every other page is flipped, so that you can print double-sided and
the pages will line up properly and be pre-collated.

Graphics stream parsing proof of concept
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The `copy_pdf.py`__ script shows a simple example of reading in a PDF, and
using the decodegraphics.py module to try to write the same information
out to a new PDF through a reportlab canvas. (If you know about reportlab,
you know that if you can faithfully render a PDF to a reportlab canvas, you
can do pretty much anything else with that PDF you want.) This kind of
low level manipulation should be done only if you really need to.
decodegraphics is really more than a proof of concept than anything
else. For most cases, just use the Form XObject capability, as shown in
the examples/rl1/booklet.py demo.

__ examples/rl2/copy_pdf.py

pdfrw philosophy
==================

Core library
-------------

The philosophy of the library portion of pdfrw is to provide intuitive
functions to read, manipulate, and write PDF files.  There should be
minimal leakage between abstraction layers, although getting useful
work done makes "pure" functionality separation difficult.

A key concept supported by the library is the use of Form XObjects,
which allow easy embedding of pieces of one PDF into another.

Addition of core support to the library is typically done carefully
and thoughtfully, so as not to clutter it up with too many special
cases.

There are a lot of incorrectly formatted PDFs floating around; support
for these is added in some cases.  The decision is often based on what
acroread and okular do with the PDFs; if they can display them properly,
then eventually pdfrw should, too, if it is not too difficult or costly.

Contributions are welcome; one user has contributed some decompression
filters and the ability to process PDF 1.5 stream objects.  Additional
functionality that would obviously be useful includes additional
decompression filters, the ability to process password-protected PDFs,
and the ability to output linearized PDFs.

Examples
--------

The philosophy of the examples is to provide small, easily-understood
examples that showcase pdfrw functionality.


PDF files and Python
======================

Introduction
------------

In general, PDF files conceptually map quite well to Python. The major
objects to think about are:

-  **strings**. Most things are strings. These also often decompose
   naturally into
-  **lists of tokens**. Tokens can be combined to create higher-level
   objects like
-  **arrays** and
-  **dictionaries** and
-  **Contents streams** (which can be more streams of tokens)

Difficulties
------------

The apparent primary difficulty in mapping PDF files to Python is the
PDF file concept of "indirect objects."  Indirect objects provide
the efficiency of allowing a single piece of data to be referred to
from more than one containing object, but probably more importantly,
indirect objects provide a way to get around the chicken and egg
problem of circular object references when mapping arbitrary data
structures to files. To flatten out a circular reference, an indirect
object is *referred to* instead of being *directly included* in another
object. PDF files have a global mechanism for locating indirect objects,
and they all have two reference numbers (a reference number and a
"generation" number, in case you wanted to append to the PDF file
rather than just rewriting the whole thing).

pdfrw automatically handles indirect references on reading in a PDF
file. When pdfrw encounters an indirect PDF file object, the
corresponding Python object it creates will have an 'indirect' attribute
with a value of True. When writing a PDF file, if you have created
arbitrary data, you just need to make sure that circular references are
broken up by putting an attribute named 'indirect' which evaluates to
True on at least one object in every cycle.

Another PDF file concept that doesn't quite map to regular Python is a
"stream". Streams are dictionaries which each have an associated
unformatted data block. pdfrw handles streams by placing a special
attribute on a subclassed dictionary.

Usage Model
-----------

The usage model for pdfrw treats most objects as strings (it takes their
string representation when writing them to a file). The two main
exceptions are the PdfArray object and the PdfDict object.

PdfArray is a subclass of list with two special features.  First,
an 'indirect' attribute allows a PdfArray to be written out as
an indirect PDF object.  Second, pdfrw reads files lazily, so
PdfArray knows about, and resolves references to other indirect
objects on an as-needed basis.

PdfDict is a subclass of dict that also has an indirect attribute
and lazy reference resolution as well.  (And the subclassed
IndirectPdfDict has indirect automatically set True).

But PdfDict also has an optional associated stream. The stream object
defaults to None, but if you assign a stream to the dict, it will
automatically set the PDF /Length attribute for the dictionary.

Finally, since PdfDict instances are indexed by PdfName objects (which
always start with a /) and since most (all?) standard Adobe PdfName
objects use names formatted like "/CamelCase", it makes sense to allow
access to dictionary elements via object attribute accesses as well as
object index accesses. So usage of PdfDict objects is normally via
attribute access, although non-standard names (though still with a
leading slash) can be accessed via dictionary index lookup.

Reading PDFs
~~~~~~~~~~~~~~~

The PdfReader object is a subclass of PdfDict, which allows easy access
to an entire document::

    >>> from pdfrw import PdfReader
    >>> x = PdfReader('source.pdf')
    >>> x.keys()
    ['/Info', '/Size', '/Root']
    >>> x.Info
    {'/Producer': '(cairo 1.8.6 (http://cairographics.org))',
     '/Creator': '(cairo 1.8.6 (http://cairographics.org))'}
    >>> x.Info.Creator.decode()
    'cairo 1.8.6 (http://cairographics.org)'
    >>> x.Root.keys()
    ['/Type', '/Pages']

Info, Size, and Root are retrieved from the trailer of the PDF file.
String values such as those in Info are PdfString objects that hold the
raw PDF encoding, delimiters and escapes included; call their decode()
method to get the text.

In addition to the tree structure, pdfrw creates a special attribute
named *pages*, that is a list of all the pages in the document. pdfrw
creates the *pages* attribute as a simplification for the user, because
the PDF format allows arbitrarily complicated nested dictionaries to
describe the page order. Each entry in the *pages* list is the PdfDict
object for one of the pages in the file, in order.

::

    >>> len(x.pages)
    1
    >>> x.pages[0]
    {'/Parent': {'/Kids': [{...}], '/Type': '/Pages', '/Count': '1'},
     '/Contents': {'/Length': '11260', '/Filter': None},
     '/Resources': ... (Lots more stuff snipped)
    >>> x.pages[0].Contents
    {'/Length': '11260', '/Filter': None}
    >>> x.pages[0].Contents.stream
    'q\n1 1 1 rg /a0 gs\n0 0 0 RG 0.657436
      w\n0 J\n0 j\n[] 0.0 d\n4 M q' ... (Lots more stuff snipped)

Writing PDFs
~~~~~~~~~~~~~~~

As you can see, it is quite easy to dig down into a PDF document. But
what about when it's time to write it out?

::

    >>> from pdfrw import PdfWriter
    >>> y = PdfWriter()
    >>> y.addpage(x.pages[0])
    >>> y.write('result.pdf')

That's all it takes to create a new PDF. You may still need to read the
`Adobe PDF reference manual`__ to figure out what needs to go *into*
the PDF, but at least you don't have to sweat actually building it
and getting the file offsets right.

__ http://www.adobe.com/devnet/acrobat/pdfs/pdf_reference_1-7.pdf

Manipulating PDFs in memory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For the most part, pdfrw tries to be agnostic about the contents of
PDF files, and support them as containers, but to do useful work,
something a little higher-level is required, so pdfrw works to
understand a bit about the contents of the containers.  For example:

-  PDF pages. pdfrw knows enough to find the pages in PDF files you read
   in, and to write a set of pages back out to a new PDF file.
-  Form XObjects. pdfrw can take any page or rectangle on a page, and
   convert it to a Form XObject, suitable for use inside another PDF
   file.  It knows enough about these to perform scaling, rotation,
   and positioning.
-  reportlab objects. pdfrw can recursively create a set of reportlab
   objects from its internal object format. This allows, for example,
   Form XObjects to be used inside reportlab, so that you can reuse
   content from an existing PDF file when building a new PDF with
   reportlab.

There are several examples that demonstrate these features in
the example code directory.

Missing features
~~~~~~~~~~~~~~~~~~~~~~~

Even as a pure PDF container library, pdfrw comes up a bit short. It
does not currently support:

-  Decompression filters other than ``/FlateDecode`` (with or without
   PNG predictors).  Streams that use other filters, such as
   ``/LZWDecode`` or ``/ASCII85Decode``, are copied as they are but
   cannot be uncompressed.
-  Encryption other than the standard (password) security handler,
   such as certificate encryption.  The standard handler is supported
   with RC4 (40 to 128 bit), AES-128 and AES-256 (revisions 2 to 6);
   AES needs the ``crypto`` extra.
-  Writing encrypted files with RC4 40-bit or certificate encryption.
   Output is unencrypted unless asked for; ``PdfWriter(...,
   encrypt=Encryption(...))`` writes AES-256, AES-128 or RC4 128-bit
   (see `File output`_).

`CHANGELOG.md`__ lists what this fork has added.

__ CHANGELOG.md

`pdftk`__ is a wonderful command-line
tool that can convert your PDFs to remove other encryption and compression.
However, in most cases, you can do a lot of useful work with PDFs
without actually removing compression, because only certain elements
inside PDFs are actually compressed.

__ https://www.pdflabs.com/tools/pdftk-the-pdf-toolkit/

Library internals
==================

Introduction
------------

**pdfrw** consists of a main package and one sub-package.

The `__init.py__`__ module does the usual thing of importing a few
major attributes from some of the submodules, and the `errors.py`__
module supports logging and exception generation.

__ pdfrw/__init__.py
__ pdfrw/errors.py


PDF object model support
--------------------------

The `objects`__ sub-package contains one module for each of the
internal representations of the kinds of basic objects that exist
in a PDF file, with the `objects/__init__.py`__ module in that
package simply gathering them up and making them available to the
main pdfrw package.

One feature that all the PDF object classes have in common is the
inclusion of an 'indirect' attribute. If 'indirect' exists and evaluates
to True, then when the object is written out, it is written out as an
indirect object. That is to say, it is addressable in the PDF file, and
could be referenced by any number (including zero) of container objects.
This indirect object capability saves space in PDF files by allowing
objects such as fonts to be referenced from multiple pages, and also
allows PDF files to contain internal circular references.  This latter
capability is used, for example, when each page object has a "parent"
object in its dictionary.

__ pdfrw/objects/
__ pdfrw/objects/__init__.py

Ordinary objects
~~~~~~~~~~~~~~~~

The `objects/pdfobject.py`__ module contains the PdfObject class, which is
a subclass of str, and is the catch-all object for any PDF file elements
that are not explicitly represented by other objects, as described below.

__ pdfrw/objects/pdfobject.py

Name objects
~~~~~~~~~~~~

The `objects/pdfname.py`__ module contains the PdfName singleton object,
which will convert a string into a PDF name by prepending a slash. It can
be used either by calling it or getting an attribute, e.g.::

    PdfName.Rotate == PdfName('Rotate') == PdfObject('/Rotate')

In the example above, there is a slight difference between the objects
returned from PdfName, and the object returned from PdfObject.  The
PdfName objects are actually objects of class "BasePdfName".  This
is important, because only these may be used as keys in PdfDict objects.

__ pdfrw/objects/pdfname.py

String objects
~~~~~~~~~~~~~~

The `objects/pdfstring.py`__
module contains the PdfString class, which is a subclass of str that is
used to represent encoded strings in a PDF file. The class has encode
and decode methods for the strings.

__ pdfrw/objects/pdfstring.py


Array objects
~~~~~~~~~~~~~

The `objects/pdfarray.py`__
module contains the PdfArray class, which is a subclass of list that is
used to represent arrays in a PDF file. A regular list could be used
instead, but use of the PdfArray class allows for an indirect attribute
to be set, and also allows for proxying of unresolved indirect objects
(that haven't been read in yet) in a manner that is transparent to pdfrw
clients.

__ pdfrw/objects/pdfarray.py

Dict objects
~~~~~~~~~~~~

The `objects/pdfdict.py`__
module contains the PdfDict class, which is a subclass of dict that is
used to represent dictionaries in a PDF file. A regular dict could be
used instead, but the PdfDict class matches the requirements of PDF
files more closely:

* Transparent (from the library client's viewpoint) proxying
  of unresolved indirect objects
* Return of None for non-existent keys (like dict.get)
* Mapping of attribute accesses to the dict itself
  (pdfdict.Foo == pdfdict[NameObject('Foo')])
* Automatic management of following stream and /Length attributes
  for content dictionaries
* Indirect attribute
* Other attributes may be set for private internal use of the
  library and/or its clients.
* Support for searching parent dictionaries for PDF "inheritable"
  attributes.

__ pdfrw/objects/pdfdict.py

If a PdfDict has an associated data stream in the PDF file, the stream
is accessed via the 'stream' (all lower-case) attribute.  Setting the
stream attribute on the PdfDict will automatically set the /Length attribute
as well.  If that is not what is desired (for example if the stream
is compressed), then _stream (same name with an underscore) may be used
to associate the stream with the PdfDict without setting the length.

To set private attributes (that will not be written out to a new PDF
file) on a dictionary, use the 'private' attribute::

    mydict.private.foo = 1

Once the attribute is set, it may be accessed directly as an attribute
of the dictionary::

    foo = mydict.foo

Some attributes of PDF pages are "inheritable."  That is, they may
belong to a parent dictionary (or a parent of a parent dictionary, etc.)
The "inheritable" attribute allows for easy discovery of these::

    mediabox = mypage.inheritable.MediaBox


Proxy objects
~~~~~~~~~~~~~

The `objects/pdfindirect.py`__
module contains the PdfIndirect class, which is a non-transparent proxy
object for PDF objects that have not yet been read in and resolved from
a file. Although these are non-transparent inside the library, client code
should never see one of these -- they exist inside the PdfArray and PdfDict
container types, but are resolved before being returned to a client of
those types.

__ pdfrw/objects/pdfindirect.py


File reading, tokenization and parsing
--------------------------------------

`pdfreader.py`__
contains the PdfReader class, which can read a PDF file (or be passed a
file object or already read string) and parse it. It uses the PdfTokens
class in `tokens.py`__  for low-level tokenization.

__ pdfrw/pdfreader.py
__ pdfrw/tokens.py


The PdfReader class does not, in general, parse into containers (e.g.
inside the content streams). There is a proof of concept for doing that
inside the examples/rl2 subdirectory, but that is slow and not well-developed,
and not useful for most applications.

An instance of the PdfReader class is an instance of a PdfDict -- the
trailer dictionary of the PDF file, to be exact.  It will have a private
attribute set on it that is named 'pages' that is a list containing all
the pages in the file.

PdfReader reads files that have been updated incrementally, including
hybrid-reference files and files whose cross-reference data is in
streams: it merges every cross-reference section, newest first, so it
sees the current version of each object.  It also reads damaged files
instead of raising.  When the cross-reference data cannot be used, it
rebuilds it by scanning the file for objects, and it tolerates a
missing ``%%EOF``, junk before the ``%PDF-`` header, bad stream
lengths and objects cut off by the end of the file.  A page tree with
a dangling or malformed node loses only that node, with a warning,
and the tree is repaired so that a copy shows the same pages.
Problems that pdfrw works around are logged to the ``pdfrw`` logger,
which has only a ``NullHandler``: configure logging to see them.

When instantiating a PdfReader object, there are options available
for decompressing all the objects in the file.  pdfrw does not currently
have very many options for decompression, so this is not all that useful,
except in the specific case of compressed object streams.

Encrypted files are decrypted as they are read: RC4 (40 to 128 bit)
always, and AES-128 and AES-256 with the ``crypto`` extra.  A file
anyone can open needs no password; otherwise pass the user or owner
password as ``PdfReader(..., password='...')``.  Without it, or when
the encryption is not supported, PdfReader raises
``PdfDecryptionError`` (a ``PdfParseError``).  A copy written from the
reader is not encrypted unless you give PdfWriter an ``encrypt=``
option (see `File output`_).  ``decrypt=True`` is still accepted; it now
only reads every object up front.
If you have PDF files that are encrypted in other ways or heavily
compressed, you may find that using another program like pdftk or qpdf
on them can make them readable by pdfrw.

In general, the objects are read from the file lazily, but this is not
currently true with compressed object streams -- all of these are decompressed
and read in when the PdfReader is instantiated.


File output
-----------

`pdfwriter.py`__
contains the PdfWriter class, which can create and output a PDF file.

__ pdfrw/pdfwriter.py

There are a few options available when creating and using this class.

In the simplest case, an instance of PdfWriter is instantiated, and
then pages are added to it from one or more source files (or created
programmatically), and then the write method is called to dump the
results out to a file.

If you have a source PDF and do not want to disturb the structure
of it too badly, then you may pass its trailer directly to PdfWriter
rather than letting PdfWriter construct one for you.  There is an
example of this (alter.py) in the examples directory.

Output is unencrypted unless you pass ``encrypt=``, an ``Encryption``
giving the passwords, method and permissions:

.. code-block:: python

    from pdfrw import PdfReader, PdfWriter, Encryption

    reader = PdfReader('in.pdf', password='old')
    PdfWriter('out.pdf', trailer=reader,
              encrypt=Encryption(user_password='open me',
                                 owner_password='full rights')).write()

``Encryption(user_password='', owner_password=None, method='aes-256',
permissions=-4, encrypt_metadata=True)``:

-  An empty user password lets anyone open the file; the owner
   password (the user password when None) opens it with every
   permission.
-  ``method`` is ``'aes-256'`` (revision 6), ``'aes-128'`` or
   ``'rc4-128'`` (weak; only for old readers).  AES needs the
   ``crypto`` extra; without it ``Encryption`` raises
   ``PdfOutputError`` saying what to install.  The file is written as
   at least the PDF version the method needs: 2.0, 1.6 or 1.4.
-  ``permissions`` is the ``/P`` value (PDF 32000-2 Table 22: 4 print,
   8 modify, 16 copy text, 32 annotate, 256 fill forms, 512 extract
   for accessibility, 1024 assemble, 2048 high-quality print); the
   default allows everything.  Viewers honour them; nothing enforces
   them.
-  ``encrypt_metadata=False`` (AES only) leaves XMP metadata readable.

Each write makes new keys, so two writes of the same document differ.
The document's ``/ID`` is kept, or made when it has none.


Advanced features
-----------------

`buildxobj.py`__
contains functions to build Form XObjects out of pages or rectangles on
pages.  These may be reused in new PDFs essentially as if they were images.

buildxobj is careful to cache any page used so that it only appears in
the output once.

__ pdfrw/buildxobj.py


`toreportlab.py`__
provides the makerl function, which will translate pdfrw objects into a
format which can be used with `reportlab`_.
It is normally used in conjunction with buildxobj, to be able to reuse
parts of existing PDFs when using reportlab.

__ pdfrw/toreportlab.py


`pagemerge.py`__ builds on the foundation laid by buildxobj.  It
contains classes to create a new page (or overlay an existing page)
using one or more rectangles from other pages.  There are examples
showing its use for watermarking, scaling, 4-up output, splitting
each page in 2, etc.

__ pdfrw/pagemerge.py

`findobjs.py`__ contains code that can find specific kinds of objects
inside a PDF file.  The extract.py example uses this module to create
a new PDF that places each image and Form XObject from a source PDF onto
its own page, e.g. for easy reuse with some of the other examples or
with reportlab.

__ pdfrw/findobjs.py


Miscellaneous
----------------

`compress.py`__ and `uncompress.py`__
contains compression and decompression functions. Very few filters are
currently supported, so an external tool like pdftk might be good if you
require the ability to decompress (or, for that matter, decrypt) PDF
files.

__ pdfrw/compress.py
__ pdfrw/uncompress.py


`py23_diffs.py`__ contains code to help manage the differences between
Python 2 and Python 3.

__ pdfrw/py23_diffs.py

Testing
===============

The tests need no external PDFs and no network access.  Each test
builds the PDFs it needs (with ``tests/pdfgen.py``), and checks pdfrw's
output with independent tools (``tests/validate.py``): qpdf through
pikepdf, pypdf, and PDFium through pypdfium2.  Network connections are
blocked while the tests run.

From the top of the source tree, in a virtual environment, install
pdfrw-ng in editable mode with the ``test`` dependency group, then run
pytest.  ``--group`` needs pip 25.1 or later.

.. code-block:: bash

    $ python -m pip install --upgrade pip
    $ pip install --group test -e ".[crypto]"
    $ pytest

Warnings are treated as errors, so a new DeprecationWarning or
SyntaxWarning from pdfrw fails the suite.  To run one test file or
one test:

.. code-block:: bash

    $ pytest tests/test_pdfstring.py
    $ pytest tests/test_pdfstring.py -k encode

GitHub Actions (``.github/workflows/ci.yml``) runs the suite with
coverage on Linux, macOS and Windows for every supported Python.

Other libraries
=====================

Pure Python
-----------

-  `reportlab`_

    reportlab is must-have software if you want to programmatically
    generate arbitrary PDFs.

-  `pypdf <https://github.com/py-pdf/pypdf>`__ (formerly pyPdf and
   PyPDF2)

    pyPdf is, in some ways, very full-featured. It can do decompression
    and decryption and seems to know a lot about items inside at least
    some kinds of PDF files. In comparison, pdfrw knows less about
    specific PDF file features (such as metadata), but focuses on trying
    to have a more Pythonic API for mapping the PDF file container
    syntax to Python, and (IMO) has a simpler and better PDF file
    parser.  The Form XObject capability of pdfrw means that, in many
    cases, it does not actually need to decompress objects -- they
    can be left compressed.

-  `pdftools <http://www.boddie.org.uk/david/Projects/Python/pdftools/index.html>`__

    pdftools feels large and I fell asleep trying to figure out how it
    all fit together, but many others have done useful things with it.

-  `pagecatcher <http://www.reportlab.com/docs/pagecatcher-ds.pdf>`__

    My understanding is that pagecatcher would have done exactly what I
    wanted when I built pdfrw. But I was on a zero budget, so I've never
    had the pleasure of experiencing pagecatcher. I do, however, use and
    like `reportlab`_ (open source, from
    the people who make pagecatcher) so I'm sure pagecatcher is great,
    better documented and much more full-featured than pdfrw.

-  `pdfminer <http://www.unixuser.org/~euske/python/pdfminer/index.html>`__

    This looks like a useful, actively-developed program. It is quite
    large, but then, it is trying to actively comprehend a full PDF
    document. From the website:

    "PDFMiner is a suite of programs that help extracting and analyzing
    text data of PDF documents. Unlike other PDF-related tools, it
    allows to obtain the exact location of texts in a page, as well as
    other extra information such as font information or ruled lines. It
    includes a PDF converter that can transform PDF files into other
    text formats (such as HTML). It has an extensible PDF parser that
    can be used for other purposes instead of text analysis."

non-pure-Python libraries
-------------------------

-  `pyPoppler <https://launchpad.net/poppler-python/>`__ can read PDF
   files.
-  `pycairo <http://www.cairographics.org/pycairo/>`__ can write PDF
   files.
-  `PyMuPDF <https://github.com/rk700/PyMuPDF>`_ high performance rendering
   of PDF, (Open)XPS, CBZ and EPUB

Other tools
-----------

-  `pdftk <https://www.pdflabs.com/tools/pdftk-the-pdf-toolkit/>`__ is a wonderful command
   line tool for basic PDF manipulation. It complements pdfrw extremely
   well, supporting many operations such as decryption and decompression
   that pdfrw cannot do.
-  `MuPDF <http://www.mupdf.com/>`_ is a free top performance PDF, (Open)XPS, CBZ and EPUB rendering library
   that also comes with some command line tools. One of those, ``mutool``, has big overlaps with pdftk's - 
   except it is up to 10 times faster.

Credits
=======

pdfrw was created by **Patrick Maupin**, who wrote the majority of it
and maintained it from 2006 to 2018.  pdfrw-ng is his work, carried
forward; please direct thanks for pdfrw itself to him.

Some of the decompression code was based on the decompressor from
PyPDF2, written by **Mathieu Fenniak**.

The other authors listed in `LICENSE.txt`__ contributed to upstream
pdfrw:

__ LICENSE.txt

* Attila Tajti
* Nerijus Mika
* Bastien Gandouet
* Tzerjen Wei
* Jorj X. McKie
* Nicholas Devenish
* Jonatan Dellagostin
* Thomas Kluyver
* James Laird-Wah
* Marcus Brinkmann
* Edward Betts
* Patrick Mazulo
* Haochen Wu
* Jon Lund Steffensen
* Henddher Pedroza

License
=======

pdfrw-ng is distributed under the same terms as pdfrw: the MIT license,
with the parts derived from PyPDF2 under the BSD license.  Both are
reproduced, unchanged, in `LICENSE.txt`__.

__ LICENSE.txt

Release information
=======================

Changes in pdfrw-ng are listed in `CHANGELOG.md`__.

__ CHANGELOG.md

Upstream pdfrw revisions:

0.4 -- Released 18 September, 2017

    - Python 3.6 added to test matrix
    - Proper unicode support for text strings in PDFs added
    - buildxobj fixes allow better support creating form XObjects
      out of compressed pages in some cases
    - Compression fixes for Python 3+
    - New subset_booklets.py example
    - Bug with non-compressed indices into compressed object streams fixed
    - Bug with distinguishing compressed object stream first objects fixed
    - Better error reporting added for some invalid PDFs (e.g. when reading
      past the end of file)
    - Better scrubbing of old bookmark information when writing PDFs, to
      remove dangling references
    - Refactoring of pdfwriter, including updating API, to allow future
      enhancements for things like incremental writing
    - Minor tokenizer speedup
    - Some flate decompressor bugs fixed
    - Compression and decompression tests added
    - Tests for new unicode handling added
    - PdfReader.readpages() recursion error (issue #92) fixed.
    - Initial crypt filter support added


0.3 -- Released 19 October, 2016.

    - Python 3.5 added to test matrix
    - Better support under Python 3.x for in-memory PDF file-like objects
    - Some pagemerge and Unicode patches added
    - Changes to logging allow better coexistence with other packages
    - Fix for "from pdfrw import \*"
    - New fancy_watermark.py example shows off capabilities of pagemerge.py
    - metadata.py example renamed to cat.py


0.2 -- Released 21 June, 2015.  Supports Python 2.6, 2.7, 3.3, and 3.4.

    - Several bugs have been fixed
    - New regression test functionally tests core with dozens of
      PDFs, and also tests examples.
    - Core has been ported and tested on Python3 by round-tripping
      several difficult files and observing binary matching results
      across the different Python versions.
    - Still only minimal support for compression and no support
      for encryption or newer PDF features.  (pdftk is useful
      to put PDFs in a form that pdfrw can use.)

0.1 -- Released to PyPI in 2012.  Supports Python 2.5 - 2.7

