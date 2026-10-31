# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Writing encrypted PDFs: ``PdfWriter(..., encrypt=Encryption(...))``.

Inputs are generated with tests/pdfgen.py.  pdfrw encrypts them with
AES-256, AES-128 and RC4 128-bit, and qpdf (through pikepdf), pypdf,
PDFium and pdfrw itself must open the output with the user and with the
owner password and find the same text, strings and metadata.
"""

import io

import pytest

from pdfrw import (PdfReader, PdfWriter, PdfDict, PdfArray, PdfName,
                   PdfString, IndirectPdfDict, Encryption, crypt)
from pdfrw.errors import PdfOutputError
from pdfrw.pdfwriter import _later_version

from .pdfgen import make_pdf, encrypt
from .test_crypt import (TEXTS, TITLE, SUBJECT, source_pdf,
                         metadata_of, labels_of)
from .validate import assert_valid, pikepdf_problems, require

# method: (/V, /R, header)
METHODS = {
    'aes-256': (5, 6, b'%PDF-2.0'),
    'aes-128': (4, 4, b'%PDF-1.6'),
    'rc4-128': (2, 3, b'%PDF-1.4'),
}
AES_METHODS = ['aes-256', 'aes-128']


def needs_aes(method):
    if method.startswith('aes'):
        pytest.importorskip('Crypto')


def write(source, **kwargs):
    """`source` (bytes) read by pdfrw and written with
    ``encrypt=Encryption(**kwargs)``."""
    out = io.BytesIO()
    PdfWriter(out, trailer=PdfReader(fdata=source),
              encrypt=Encryption(**kwargs)).write()
    return out.getvalue()


def check_encrypted(data, password, method, owner):
    """`data` is a valid encrypted copy of source_pdf() that `password`
    opens, as the owner password when `owner`."""
    pikepdf = require('pikepdf')
    version, revision, header = METHODS[method]
    assert data.startswith(header)
    assert_valid(data, texts=TEXTS, password=password)
    with pikepdf.open(io.BytesIO(data), password=password) as pdf:
        assert pdf.is_encrypted
        assert pdf.encryption.V == version
        assert pdf.encryption.R == revision
        assert pdf.encryption.bits == (256 if version == 5 else 128)
        if method != 'rc4-128':
            assert pdf.encryption.stream_method.name == (
                'aesv3' if version == 5 else 'aes')
        assert pdf.owner_password_matched == owner
        assert str(pdf.docinfo.Title) == TITLE
        assert str(pdf.docinfo.Subject) == SUBJECT
        assert str(pdf.pages[1].obj.PieceInfo.Note) == 'page two note'
        assert pdf.Root.Metadata.read_bytes().startswith(b'<?xpacket')
    reader = PdfReader(fdata=data, password=password, decompress=True)
    assert labels_of(reader) == TEXTS
    assert reader.Info.Title.to_unicode() == TITLE
    assert reader.pages[1].PieceInfo.Note.to_unicode() == 'page two note'


@pytest.mark.parametrize('owner', [False, True], ids=['user', 'owner'])
@pytest.mark.parametrize('method', sorted(METHODS))
def test_round_trip(method, owner):
    needs_aes(method)
    source = source_pdf()
    data = write(source, user_password='userpw', owner_password='ownerpw',
                 method=method)
    # Nothing readable is left in the file.
    for text in (b'Page 1', b'page two note', b'secret', b'xpacket'):
        assert text not in data
    check_encrypted(data, 'ownerpw' if owner else 'userpw', method, owner)


@pytest.mark.parametrize('method', sorted(METHODS))
def test_wrong_or_missing_password(method):
    needs_aes(method)
    pikepdf = require('pikepdf')
    data = write(make_pdf(1), user_password='userpw', method=method)
    for password in ('', 'nope'):
        with pytest.raises(pikepdf.PasswordError):
            pikepdf.open(io.BytesIO(data), password=password)
        with pytest.raises(Exception, match='password'):
            PdfReader(fdata=data, password=password)


@pytest.mark.parametrize('method', sorted(METHODS))
def test_empty_user_password(method):
    """The default empty user password lets anyone open the file."""
    needs_aes(method)
    data = write(source_pdf(), owner_password='ownerpw', method=method)
    check_encrypted(data, '', method, False)


def test_owner_password_defaults_to_user_password():
    pytest.importorskip('Crypto')
    pikepdf = require('pikepdf')
    data = write(make_pdf(1), user_password='same')
    with pikepdf.open(io.BytesIO(data), password='same') as pdf:
        assert pdf.owner_password_matched and pdf.user_password_matched


@pytest.mark.parametrize('method', sorted(METHODS))
def test_permissions(method):
    needs_aes(method)
    pikepdf = require('pikepdf')
    # No printing or copying; the reserved bits are set for us.
    permissions = -4 & ~(4 | 16 | 2048)
    data = write(make_pdf(1), owner_password='ownerpw', method=method,
                 permissions=permissions & 0xFFF)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert pdf.encryption.P == permissions
        allow = pdf.allow
        assert not allow.print_lowres and not allow.print_highres
        assert not allow.extract
        assert allow.modify_annotation and allow.modify_form
    # pdfrw reads AES-256 /Perms back and finds it matches /P.
    if method == 'aes-256':
        reader = PdfReader(fdata=data)
        assert reader.crypt_handler.perms_ok
        assert int(reader.crypt_handler.revision) == 6


def test_permissions_normalized():
    assert Encryption(method='rc4-128', permissions=0).permissions == -3904
    assert Encryption(method='rc4-128', permissions=-1).permissions == -4
    assert Encryption(method='rc4-128',
                      permissions=0xFFFFFFFF).permissions == -4


@pytest.mark.parametrize('method', AES_METHODS)
def test_unencrypted_metadata(method):
    pytest.importorskip('Crypto')
    source = source_pdf()
    data = write(source, user_password='userpw', method=method,
                 encrypt_metadata=False)
    assert b'/EncryptMetadata false' in data
    # The XMP packet is stored in the clear; everything else is not.
    assert b'<?xpacket' in data
    assert b'Page 1' not in data
    assert metadata_of(data, 'userpw') == metadata_of(source)
    reader = PdfReader(fdata=data, password='userpw', decompress=True)
    assert labels_of(reader) == TEXTS
    assert reader.Root.Metadata.stream.startswith('<?xpacket')
    if method == 'aes-256':
        assert reader.crypt_handler.perms_ok


def test_unencrypted_metadata_needs_aes():
    with pytest.raises(ValueError, match='AES'):
        Encryption(method='rc4-128', encrypt_metadata=False)


def test_reencrypt_encrypted_file():
    """A file pdfrw decrypts can be written encrypted again: the round
    trip T7 documented as losing the encryption."""
    pytest.importorskip('Crypto')
    original = encrypt(source_pdf(), user='old', owner='oldowner', R=4)
    reader = PdfReader(fdata=original, password='old')
    out = io.BytesIO()
    PdfWriter(out, trailer=reader,
              encrypt=Encryption('new', 'newowner')).write()
    data = out.getvalue()
    check_encrypted(data, 'new', 'aes-256', False)
    check_encrypted(data, 'newowner', 'aes-256', True)
    # The document /ID is kept.
    assert PdfReader(fdata=data, password='new').ID == reader.ID


@pytest.mark.parametrize('method', sorted(METHODS))
def test_compressed(method):
    needs_aes(method)
    out = io.BytesIO()
    PdfWriter(out, trailer=PdfReader(fdata=source_pdf()), compress=True,
              encrypt=Encryption('pw', method=method)).write()
    check_encrypted(out.getvalue(), 'pw', method, True)


def test_new_document_gets_an_id():
    """A document built from pages (no /ID) is given one, as revisions
    2 to 4 need it for the key."""
    data = write(make_pdf(2), user_password='pw', method='rc4-128')
    reader = PdfReader(fdata=data, password='pw')
    assert len(reader.ID) == 2
    assert len(reader.ID[0].to_bytes()) == 16
    out = io.BytesIO()
    writer = PdfWriter(out, encrypt=Encryption('pw', method='rc4-128'))
    writer.addpages(PdfReader(fdata=make_pdf(2)).pages)
    writer.write()
    assert_valid(out.getvalue(), texts=TEXTS[:2], password='pw')


def test_writer_leaves_document_unchanged():
    """Encrypting the output changes nothing in memory: the reader's
    trailer, streams and strings are as they were, a second write is
    valid, and each write uses new keys."""
    pytest.importorskip('Crypto')
    reader = PdfReader(fdata=source_pdf())
    stream = reader.pages[0].Contents.stream
    writer = PdfWriter(trailer=reader, encrypt=Encryption('pw'))
    first, second = io.BytesIO(), io.BytesIO()
    writer.write(first)
    writer.write(second)
    assert reader.Encrypt is None
    assert reader.pages[0].Contents.stream == stream
    assert reader.Info.Title.to_unicode() == TITLE
    assert first.getvalue() != second.getvalue()
    for data in (first.getvalue(), second.getvalue()):
        check_encrypted(data, 'pw', 'aes-256', True)
    unencrypted = io.BytesIO()
    PdfWriter(unencrypted, trailer=reader).write()
    assert b'/Encrypt' not in unencrypted.getvalue()
    assert unencrypted.getvalue().startswith(b'%PDF-1.3')


def test_strings_of_every_kind():
    """PdfStrings, an indirect string object, plain str and bytes values,
    and strings nested in arrays and direct dictionaries are encrypted;
    a signature's /Contents is not."""
    pytest.importorskip('Crypto')
    reader = PdfReader(fdata=make_pdf(1))
    indirect = PdfString.from_unicode(u'indirect ☃')
    indirect.indirect = True
    sig = IndirectPdfDict(Type=PdfName.Sig,
                          ByteRange=PdfArray([0, 10, 20, 10]),
                          Contents=PdfString('<0102ABCD>'),
                          Name=PdfString.from_bytes(b'signer'))
    reader.Root.Extra = PdfDict(
        Literal=PdfString.from_bytes(b'literal (text)'),
        Indirect=indirect,
        Plain='plain str',
        Raw=b'raw bytes',
        Nested=PdfArray([PdfString.from_bytes(b'in array'),
                         PdfDict(Deep=PdfString.from_bytes(b'deep'))]),
        Sig=sig)
    data = write_reader(reader, Encryption('pw'))
    for text in (b'literal', b'plain str', b'raw bytes', b'in array',
                 b'deep', b'signer'):
        assert text not in data
    assert b'<0102ABCD>' in data
    extra = PdfReader(fdata=data, password='pw').Root.Extra
    assert extra.Literal.to_bytes() == b'literal (text)'
    assert extra.Indirect.to_unicode() == u'indirect ☃'
    assert extra.Plain.to_bytes() == b'plain str'
    assert extra.Raw.to_bytes() == b'raw bytes'
    assert extra.Nested[0].to_bytes() == b'in array'
    assert extra.Nested[1].Deep.to_bytes() == b'deep'
    assert extra.Sig.Name.to_bytes() == b'signer'
    assert extra.Sig.Contents.to_bytes() == b'\x01\x02\xab\xcd'
    pikepdf = require('pikepdf')
    with pikepdf.open(io.BytesIO(data), password='pw') as pdf:
        assert bytes(pdf.Root.Extra.Literal) == b'literal (text)'
        assert bytes(pdf.Root.Extra.Sig.Contents) == b'\x01\x02\xab\xcd'


def write_reader(reader, encryption):
    out = io.BytesIO()
    PdfWriter(out, trailer=reader, encrypt=encryption).write()
    return out.getvalue()


def test_empty_stream():
    pytest.importorskip('Crypto')
    reader = PdfReader(fdata=make_pdf(1))
    reader.pages[0].Contents.stream = ''
    for method in sorted(METHODS):
        data = write_reader(reader, Encryption('pw', method=method))
        assert_valid(data, texts=[''], password='pw')
        page = PdfReader(fdata=data, password='pw').pages[0]
        assert page.Contents.stream == ''


def test_non_ascii_password_aes256():
    pytest.importorskip('Crypto')
    password = u'p\xe4ssw\xf6rd ☃'
    data = write(source_pdf(), user_password=password)
    check_encrypted(data, password, 'aes-256', True)


def test_aes256_password_is_saslprepped():
    """A soft hyphen is mapped to nothing by SASLprep, so the password
    without it opens the file."""
    pytest.importorskip('Crypto')
    data = write(make_pdf(1), user_password=u'pass\xadword',
                 owner_password='owner')
    assert_valid(data, password='password')


def test_password_bytes():
    pytest.importorskip('Crypto')
    for method in sorted(METHODS):
        data = write(make_pdf(1), user_password=b'\xffbytes',
                     owner_password=b'o', method=method)
        assert not pikepdf_problems(data, password=b'\xffbytes')
        assert PdfReader(fdata=data, password=b'\xffbytes').pages
        assert PdfReader(fdata=data, password=b'o').pages


def test_non_ascii_password_rc4():
    password = u'p\xe4ssw\xf6rd'
    data = write(make_pdf(1), user_password=password, method='rc4-128')
    assert not pikepdf_problems(data, password.encode('pdfdocencoding'))
    assert PdfReader(fdata=data, password=password).pages


def test_bad_passwords():
    with pytest.raises(ValueError, match='PDFDocEncoding'):
        Encryption(u'☃', method='rc4-128')
    with pytest.raises(TypeError, match='owner password'):
        Encryption('', 5, method='rc4-128')
    pytest.importorskip('Crypto')
    with pytest.raises(ValueError, match='not valid for AES-256'):
        Encryption(u'bad\u0007')


def test_long_passwords_truncated():
    assert len(Encryption(b'x' * 50, method='rc4-128').user) == 32
    pytest.importorskip('Crypto')
    assert len(Encryption(b'x' * 200).owner) == 127


def test_bad_method_and_type():
    with pytest.raises(ValueError, match='aes-128, aes-256, rc4-128'):
        Encryption(method='rc4-40')
    with pytest.raises(TypeError, match='pdfrw.Encryption'):
        PdfWriter(io.BytesIO(), encrypt='password')
    assert repr(Encryption(method='RC4-128')) == '<Encryption rc4-128>'


@pytest.mark.parametrize('method', AES_METHODS)
def test_aes_without_pycryptodome_says_what_to_install(monkeypatch, method):
    monkeypatch.setattr(crypt, 'AES', None)
    with pytest.raises(PdfOutputError,
                       match=r'pip install "pdfrw-ng\[crypto\]"'):
        Encryption('pw', method=method)


def test_rc4_without_pycryptodome(monkeypatch):
    monkeypatch.setattr(crypt, 'AES', None)
    monkeypatch.setattr(crypt, '_ARC4', None)
    data = write(source_pdf(), user_password='pw', method='rc4-128')
    check_encrypted(data, 'pw', 'rc4-128', True)


def test_version_only_raised():
    """The header is at least the version the method needs, and a later
    version asked for is kept."""
    out = io.BytesIO()
    PdfWriter(out, version='1.7', trailer=PdfReader(fdata=make_pdf(1)),
              encrypt=Encryption('pw', method='rc4-128')).write()
    assert out.getvalue().startswith(b'%PDF-1.7\n')
    assert _later_version('1.3', '2.0') == '2.0'
    assert _later_version('1.10', '1.6') == '1.10'
    assert _later_version('junk', '1.4') == '1.4'


def test_supplied_id_kept_or_replaced():
    first = PdfString.from_bytes(b'0123456789abcdef', 'hex')
    good = PdfArray([first, PdfString.from_bytes(b'x' * 16, 'hex')])
    writer = Encryption(method='rc4-128').start(good)
    assert writer.file_id == good and writer.file_id is not good
    for bad in (None, PdfArray([first]), PdfArray([first, 5])):
        writer = Encryption(method='rc4-128').start(bad)
        assert len(writer.file_id) == 2
        assert writer.file_id[0].to_bytes() == writer.file_id[1].to_bytes()


def test_encrypt_stream_bytes_and_identity():
    """A stream held as bytes is encrypted too; with
    encrypt_metadata=False a metadata stream is left as it is."""
    writer = Encryption(method='rc4-128').start()
    obj = PdfDict()
    data = writer.encrypt_stream(3, obj, b'abc')
    assert writer.filter.decrypt_data(3, 0, data.encode('latin-1')) == \
        b'abc'
    pytest.importorskip('Crypto')
    writer = Encryption(encrypt_metadata=False).start()
    metadata = PdfDict(Type=PdfName.Metadata)
    assert writer.encrypt_stream(3, metadata, 'xmp') == 'xmp'
