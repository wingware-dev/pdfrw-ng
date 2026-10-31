# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Reading encrypted PDFs (#48, #116, #249, #200, #123).

Inputs are generated, then encrypted by qpdf (through pikepdf) with each
method the standard security handler has: RC4 40 and 128 bit, AES-128,
and AES-256 (revision 6), with and without object streams.  pdfrw must
read them, and a copy it writes must be an unencrypted PDF that qpdf,
pypdf and PDFium accept and that shows the same text, strings included.
"""

import io

import pytest

from pdfrw import (PdfReader, PdfWriter, PdfDecryptionError, PdfDict,
                   PdfArray, PdfName, PdfString, crypt)

from .pdfgen import make_pdf, page_label, encrypt
from .validate import assert_valid, pdfium_page_texts, require

TEXTS = [page_label(i) for i in range(3)]
TITLE = u'Caf\xe9 (secret) \\ title ☃'
SUBJECT = 'plain ascii subject'
# pikepdf rewrites this packet to match /Info when it saves.
XMP = (b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
       b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf='
       b'"http://www.w3.org/1999/02/22-rdf-syntax-ns#"></rdf:RDF>'
       b'</x:xmpmeta><?xpacket end="w"?>')

# (R, aes): RC4 40-bit, RC4 128-bit, RC4 128-bit with crypt filters,
# AES-128, AES-256.
METHODS = [(2, False), (3, False), (4, False), (4, True), (6, True)]
METHOD_IDS = ['rc4-40', 'rc4-128', 'rc4-cf', 'aes-128', 'aes-256']


def needs_aes(aes):
    if aes:
        pytest.importorskip('Crypto')


def source_pdf():
    """make_pdf(3) with an /Info title and subject, a string in a page
    dictionary and an XMP metadata stream, so encryption covers strings
    and a metadata stream as well as page content."""
    pikepdf = require('pikepdf')
    with pikepdf.open(io.BytesIO(make_pdf(3))) as pdf:
        pdf.docinfo['/Title'] = TITLE
        pdf.docinfo['/Subject'] = SUBJECT
        pdf.pages[1].obj['/PieceInfo'] = pikepdf.Dictionary(
            Note=pikepdf.String('page two note'))
        pdf.Root.Metadata = pdf.make_stream(
            XMP, Type=pikepdf.Name.Metadata, Subtype=pikepdf.Name.XML)
        out = io.BytesIO()
        pdf.save(out, static_id=True)
    return out.getvalue()


def copy(reader):
    out = io.BytesIO()
    PdfWriter(out, trailer=reader).write()
    return out.getvalue()


def labels_of(reader):
    labels = []
    for page in reader.pages:
        stream = page.Contents.stream
        labels.append(stream[stream.index('(') + 1:stream.index(')')])
    return labels


def metadata_of(data, password=''):
    """The decoded XMP stream, as qpdf reads it."""
    pikepdf = require('pikepdf')
    with pikepdf.open(io.BytesIO(data), password=password) as pdf:
        return pdf.Root.Metadata.read_bytes()


def check_copy(data, original, password=''):
    """`data`, a copy pdfrw wrote of the encrypted `original`, is valid,
    unencrypted and has the same strings and metadata as qpdf reads from
    `original`."""
    pikepdf = require('pikepdf')
    assert_valid(data, texts=TEXTS)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert not pdf.is_encrypted
        assert str(pdf.docinfo.Title) == TITLE
        assert str(pdf.docinfo.Subject) == SUBJECT
        assert str(pdf.pages[1].obj.PieceInfo.Note) == 'page two note'
        metadata = pdf.Root.Metadata.read_bytes()
    assert metadata == metadata_of(original, password)
    assert metadata.startswith(b'<?xpacket')


@pytest.mark.parametrize('object_streams', [False, True],
                         ids=['plain', 'objstm'])
@pytest.mark.parametrize('R, aes', METHODS, ids=METHOD_IDS)
def test_empty_user_password_decrypts_without_asking(R, aes, object_streams):
    """A file anyone can open is decrypted by default.  Before, reading it
    without decrypt=True kept the ciphertext and a copy had blank pages
    (#48), and with object streams reading crashed (#116, #249, #200)."""
    needs_aes(aes)
    data = encrypt(source_pdf(), R=R, aes=aes,
                   object_streams=object_streams)
    assert pdfium_page_texts(data) == TEXTS
    reader = PdfReader(fdata=data)
    assert reader.Encrypt is None
    assert reader.Info.Title.to_unicode() == TITLE
    assert reader.Info.Subject.to_unicode() == SUBJECT
    check_copy(copy(reader), data)
    assert labels_of(PdfReader(fdata=data, decompress=True)) == TEXTS


@pytest.mark.parametrize('R, aes', METHODS, ids=METHOD_IDS)
def test_decrypt_true_still_works(R, aes):
    """decrypt=True, the upstream way to ask for decryption, raised
    TypeError on Python 3 for RC4 and AES-128 (#48)."""
    needs_aes(aes)
    data = encrypt(source_pdf(), R=R, aes=aes)
    reader = PdfReader(fdata=data, decrypt=True)
    check_copy(copy(reader), data)


@pytest.mark.parametrize('R, aes', METHODS, ids=METHOD_IDS)
@pytest.mark.parametrize('password', ['user pw', 'owner pw'])
def test_user_and_owner_passwords(R, aes, password):
    needs_aes(aes)
    data = encrypt(source_pdf(), user='user pw', owner='owner pw', R=R,
                   aes=aes, object_streams=True)
    assert pdfium_page_texts(data, password='user pw') == TEXTS
    check_copy(copy(PdfReader(fdata=data, password=password)), data,
               password)


@pytest.mark.parametrize('R, aes', METHODS, ids=METHOD_IDS)
def test_password_bytes(R, aes):
    needs_aes(aes)
    data = encrypt(source_pdf(), user='user pw', R=R, aes=aes)
    check_copy(copy(PdfReader(fdata=data, password=b'user pw')), data,
               'user pw')


@pytest.mark.parametrize('R, aes', METHODS, ids=METHOD_IDS)
def test_missing_password_raises(R, aes):
    """Never read ciphertext as if it were plaintext: without the
    password the read fails, saying what is needed."""
    needs_aes(aes)
    data = encrypt(source_pdf(), user='user pw', R=R, aes=aes)
    with pytest.raises(PdfDecryptionError, match='needs a password'):
        PdfReader(fdata=data)


@pytest.mark.parametrize('R, aes', METHODS, ids=METHOD_IDS)
def test_wrong_password_raises(R, aes):
    needs_aes(aes)
    data = encrypt(source_pdf(), user='user pw', R=R, aes=aes)
    with pytest.raises(PdfDecryptionError, match='password is wrong'):
        PdfReader(fdata=data, password='nope')


def test_decryption_error_is_a_parse_error():
    from pdfrw import PdfParseError
    assert issubclass(PdfDecryptionError, PdfParseError)


def test_non_ascii_password_aes256():
    pytest.importorskip('Crypto')
    password = u'p\xe4ssw\xf6rd ☃'
    data = encrypt(source_pdf(), user=password, R=6, aes=True)
    check_copy(copy(PdfReader(fdata=data, password=password)), data,
               password)


def test_non_ascii_password_rc4():
    """Revisions 2-4 hash the password in PDFDocEncoding."""
    password = u'p\xe4ssw\xf6rd'
    data = encrypt(source_pdf(), user=password, R=3, aes=False)
    # pikepdf opens with the UTF-8 bytes of a str password; qpdf
    # encrypted with the PDFDocEncoding ones.
    check_copy(copy(PdfReader(fdata=data, password=password)), data,
               password.encode('pdfdocencoding'))


@pytest.mark.parametrize('R', [4, 6])
def test_unencrypted_metadata(R):
    """With /EncryptMetadata false the XMP stream is stored in the clear
    and must not be 'decrypted' into garbage."""
    pytest.importorskip('Crypto')
    data = encrypt(source_pdf(), R=R, aes=True, metadata=False)
    assert b'/EncryptMetadata false' in data
    reader = PdfReader(fdata=data, decompress=True)
    assert (reader.Root.Metadata.stream.encode('latin-1') ==
            metadata_of(data))
    check_copy(copy(PdfReader(fdata=data)), data)


@pytest.mark.parametrize('R', [2, 3, 4])
def test_rc4_without_pycryptodome(monkeypatch, R):
    """RC4 needs no extra package: pdfrw has its own."""
    monkeypatch.setattr(crypt, '_ARC4', None)
    data = encrypt(source_pdf(), R=R, aes=False, object_streams=True)
    check_copy(copy(PdfReader(fdata=data)), data)


@pytest.mark.parametrize('R', [4, 6])
def test_aes_without_pycryptodome_says_what_to_install(monkeypatch, R):
    pytest.importorskip('Crypto')
    data = encrypt(source_pdf(), R=R, aes=True)
    monkeypatch.setattr(crypt, 'AES', None)
    with pytest.raises(PdfDecryptionError, match='pycryptodome'):
        PdfReader(fdata=data)


@pytest.mark.parametrize('object_streams', [False, True],
                         ids=['plain', 'objstm'])
def test_damaged_encrypted_file(object_streams):
    """With an unusable startxref the cross-reference data is rebuilt by
    scanning; in an encrypted file the object streams it finds are read
    once decryption is set up, instead of being skipped (0 pages)."""
    pytest.importorskip('Crypto')
    data = encrypt(source_pdf(), R=4, aes=True,
                   object_streams=object_streams)
    index = data.rfind(b'startxref')
    damaged = data[:index] + b'startxref\n99999999\n%%EOF\n'
    # qpdf cannot rebuild the damaged file with object streams itself,
    # so compare with the undamaged one.
    check_copy(copy(PdfReader(fdata=damaged)), data)


# -- primitives and the security handler ----------------------------------

def test_rc4_known_answer(monkeypatch):
    # The Wikipedia RC4 test vectors.
    vectors = [(b'Key', b'Plaintext', 'bbf316e8d940af0ad3'),
               (b'Wiki', b'pedia', '1021bf0420'),
               (b'Secret', b'Attack at dawn', '45a01f645fc35b383552544b9bf5')]
    for builtin in (False, True):
        if builtin:
            monkeypatch.setattr(crypt, '_ARC4', None)
        for key, plain, expected in vectors:
            assert crypt.rc4(key, plain).hex() == expected


def test_aes_decrypt_damaged_data(caplog):
    pytest.importorskip('Crypto')
    key = b'k' * 16
    assert crypt._aes_decrypt(key, b'') == b''
    assert crypt._aes_decrypt(key, b'x' * 20) == b''
    assert 'not an IV and whole blocks' in caplog.text
    # Wrong key: padding check fails, data kept rather than lost.
    from Crypto.Cipher import AES
    iv = b'i' * 16
    good = iv + AES.new(key, AES.MODE_CBC, iv).encrypt(b'hello' + b'\x0b' * 11)
    assert crypt._aes_decrypt(key, good) == b'hello'
    caplog.clear()
    assert len(crypt._aes_decrypt(b'K' * 16, good)) == 16
    assert 'Invalid padding' in caplog.text


class _Reverse(object):
    """A stand-in crypt filter, so the tests below need no real keys."""
    def decrypt_data(self, num, gen, data):
        return data[::-1]


def _handler():
    handler = object.__new__(crypt.SecurityHandler)
    handler.string_filter = handler.stream_filter = _Reverse()
    handler.filters = {PdfName.Identity: crypt.IdentityCryptFilter(),
                       PdfName.Rev: _Reverse()}
    handler.encrypt_metadata = True
    return handler


def test_strings_decrypted_in_nested_objects_only():
    handler = _handler()
    other = PdfDict(Title=PdfString.from_bytes(b'cba'))
    other.indirect = (9, 0)
    obj = PdfDict(A=PdfString.from_bytes(b'cba'),
                  B=PdfArray([PdfString.from_bytes(b'fed'),
                              PdfDict(C=PdfString.from_bytes(b'ihg'))]),
                  Other=other)
    handler.decrypt_object(obj, (5, 0))
    assert obj.A.to_bytes() == b'abc'
    assert obj.B[0].to_bytes() == b'def'
    assert obj.B[1].C.to_bytes() == b'ghi'
    # Another indirect object is decrypted when it is read, not here.
    assert other.Title.to_bytes() == b'cba'


def test_indirect_string_object():
    result = _handler().decrypt_object(PdfString.from_bytes(b'zyx'), (3, 0))
    assert result.to_bytes() == b'xyz'


def test_signature_contents_not_decrypted():
    sig = PdfDict(Type=PdfName.Sig, Contents=PdfString('<0102>'),
                  Name=PdfString.from_bytes(b'eman'))
    _handler().decrypt_object(sig, (4, 0))
    assert sig.Contents == '<0102>'
    assert sig.Name.to_bytes() == b'name'


def test_xref_stream_not_decrypted():
    obj = PdfDict(Type=PdfName.XRef)
    obj.stream = 'abc'
    _handler().decrypt_object(obj, (7, 0))
    assert obj.stream == 'abc'


def test_crypt_filter_in_stream_filter_list():
    """A stream's own /Crypt filter picks the crypt filter, and is
    removed with its /DecodeParms entry once applied."""
    handler = _handler()
    handler.stream_filter = crypt.IdentityCryptFilter()
    obj = PdfDict(Filter=PdfArray([PdfName.Crypt, PdfName.FlateDecode]),
                  DecodeParms=PdfArray([PdfDict(Name=PdfName.Rev),
                                        PdfDict(Predictor=12)]))
    obj.stream = 'cba'
    handler.decrypt_object(obj, (6, 0))
    assert obj.stream == 'abc'
    assert obj.Filter == [PdfName.FlateDecode]
    assert obj.DecodeParms == [PdfDict(Predictor=12)]
    # Already decrypted: a second pass leaves it alone.
    handler.decrypt_object(obj, (6, 0))
    assert obj.stream == 'abc'

    single = PdfDict(Filter=PdfName.Crypt)
    single.stream = 'zyx'
    handler.decrypt_object(single, (8, 0))
    assert single.stream == 'zyx'           # No /Name: /Identity
    assert single.Filter is None


def test_unknown_crypt_filter_name():
    obj = PdfDict(Filter=PdfName.Crypt,
                  DecodeParms=PdfDict(Name=PdfName.Missing))
    obj.stream = 'abc'
    with pytest.raises(PdfDecryptionError, match='Missing'):
        _handler().decrypt_object(obj, (6, 0))


@pytest.mark.parametrize('encrypt_dict, message', [
    (PdfDict(Filter=PdfName('Adobe.PubSec'), V=4, R=4), 'Adobe.PubSec'),
    (PdfDict(Filter=PdfName.Standard, V=3, R=3), 'Unsupported encryption'),
    (PdfDict(Filter=PdfName.Standard, V=5, R=4), 'revision'),
    (PdfDict(Filter=PdfName.Standard, V=4, R=4,
             CF=PdfDict(StdCF=PdfDict(CFM=PdfName.Weird))), 'Weird'),
    (PdfString('(not a dict)'), 'not a dictionary'),
], ids=['pubsec', 'v3', 'v5-r4', 'bad-cfm', 'not-dict'])
def test_unsupported_encryption(encrypt_dict, message):
    with pytest.raises(PdfDecryptionError, match=message):
        crypt.SecurityHandler(encrypt_dict, None, '')


@pytest.mark.parametrize('R', [2, 3])
def test_upstream_helpers(monkeypatch, R):
    """The pdfrw 0.4 module functions work on Python 3."""
    data = encrypt(source_pdf(), R=R, aes=False)
    seen = []

    def record(self, source, password, trailer):
        seen.append(PdfDict(Encrypt=trailer.Encrypt, ID=trailer.ID))

    # Read the /Encrypt dictionary without decrypting anything.
    monkeypatch.setattr(PdfReader, '_parse_encrypt_info', record)
    PdfReader(fdata=data)
    doc, = seen
    key = crypt.create_key('', doc)
    assert len(key) == (5 if R == 2 else 16)
    assert crypt.check_user_password(key, doc)
    assert not crypt.check_user_password(b'x' * len(key), doc)
    assert len(crypt.create_user_hash(key, doc)) == (32 if R == 2 else 16)


# -- /Perms (Algorithm 13) -------------------------------------------------

def _perms_dict(P=-1028, metadata=b'T', tag=b'adb', key=b'k' * 32,
                perms=None):
    from Crypto.Cipher import AES
    if perms is None:
        block = ((P & 0xFFFFFFFF).to_bytes(4, 'little') + b'\xff' * 4 +
                 metadata + tag + b'rand')
        perms = AES.new(key, AES.MODE_ECB).encrypt(block)
    return PdfDict(P=P, Perms=PdfString.from_bytes(perms))


def test_aes256_perms_checked(caplog):
    """A file qpdf wrote has /Perms that matches /P: no warning."""
    pytest.importorskip('Crypto')
    data = encrypt(source_pdf(), R=6, aes=True)
    reader = PdfReader(fdata=data)
    assert reader.crypt_handler.perms_ok is True
    assert 'Perms' not in caplog.text


def test_aes256_tampered_p_warns_but_reads(caplog):
    """Changing /P without updating /Perms is reported, and the file
    is still read: only software enforcing permissions cares."""
    pytest.importorskip('Crypto')
    data = encrypt(source_pdf(), R=6, aes=True)
    assert data.count(b'/P -1028') == 1
    data = data.replace(b'/P -1028', b'/P -1029')
    reader = PdfReader(fdata=data)
    assert reader.crypt_handler.perms_ok is False
    assert '/P is -1029 but /Perms says -1028' in caplog.text
    check_copy(copy(reader), data)


def test_check_perms_cases(caplog):
    pytest.importorskip('Crypto')
    key = b'k' * 32
    check = crypt._check_perms
    assert check(key, _perms_dict(), 6, True)
    assert check(key, _perms_dict(metadata=b'F'), 6, False)
    assert caplog.text == ''

    assert not check(key, _perms_dict(metadata=b'F'), 6, True)
    assert '/EncryptMetadata is true but /Perms says false' in caplog.text
    caplog.clear()

    assert not check(key, _perms_dict(tag=b'xyz'), 6, True)
    assert 'valid permissions block' in caplog.text
    caplog.clear()

    assert not check(b'K' * 32, _perms_dict(), 6, True)  # wrong key
    assert 'valid permissions block' in caplog.text
    caplog.clear()

    assert not check(key, PdfDict(P=-4), 6, True)
    assert 'missing or too short' in caplog.text
    caplog.clear()

    # Revision 5 files may lack /Perms; that is not worth a warning.
    assert not check(key, PdfDict(P=-4), 5, True)
    assert caplog.text == ''


# -- SASLprep for AES-256 passwords ----------------------------------------

@pytest.mark.parametrize('text, expected', [
    (u'user', u'user'),
    (u'I­X', u'IX'),                   # RFC 4013 examples
    (u'ª', u'a'),
    (u'Ⅸ', u'IX'),
    (u'été', u'été'),    # NFKC composes accents
    (u'a b', u'a b'),                  # Non-ASCII space
    (u'​', u''),                       # Mapped to nothing
    (u'اب', u'اب'),     # Right-to-left only
], ids=['ascii', 'soft-hyphen', 'ordinal', 'roman', 'decomposed', 'nbsp',
        'zwsp', 'rtl'])
def test_saslprep(text, expected):
    assert crypt.saslprep(text) == expected


@pytest.mark.parametrize('text', [u'a\u0007', u'ا1', u'a'],
                         ids=['control', 'bidi', 'private-use'])
def test_saslprep_rejects(text):
    with pytest.raises(ValueError):
        crypt.saslprep(text)


DECOMPOSED = u'café pa­ss'      # e + combining acute, soft hyphen
PREPARED = u'café pass'


@pytest.mark.parametrize('owner', [False, True], ids=['user', 'owner'])
def test_aes256_password_is_saslprepped(owner):
    """A password typed in another Unicode form opens a file whose
    password was SASLprepped when it was encrypted, as the spec says."""
    pytest.importorskip('Crypto')
    kw = {'owner': PREPARED, 'user': 'other'} if owner else \
        {'user': PREPARED}
    data = encrypt(source_pdf(), R=6, aes=True, **kw)
    reader = PdfReader(fdata=data, password=DECOMPOSED)
    check_copy(copy(reader), data, PREPARED)


def test_aes256_password_not_saslprepped_by_writer():
    """A writer that skipped SASLprep hashed the password as given; that
    is tried too."""
    pytest.importorskip('Crypto')
    data = encrypt(source_pdf(), user=DECOMPOSED, R=6, aes=True)
    reader = PdfReader(fdata=data, password=DECOMPOSED)
    check_copy(copy(reader), data, DECOMPOSED)


def test_aes256_password_saslprep_prohibited(caplog):
    """A password SASLprep rejects is used as given, with a warning."""
    pytest.importorskip('Crypto')
    password = u'pass\u0007word'
    data = encrypt(source_pdf(), user=password, R=6, aes=True)
    check_copy(copy(PdfReader(fdata=data, password=password)), data,
               password)
    assert 'not valid for SASLprep' in caplog.text


def test_rc4_password_not_saslprepped():
    """Revisions 2-4 use PDFDocEncoding, not SASLprep."""
    # SASLprep would make U+00AA 'a'.
    assert crypt._password_candidates(u'xª', 4) == [b'x\xaa']
