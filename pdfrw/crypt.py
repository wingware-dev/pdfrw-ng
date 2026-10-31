# A part of pdfrw (https://github.com/pmaupin/pdfrw)
# Copyright (C) 2017  Jon Lund Steffensen
# MIT license -- See LICENSE.txt for details

"""Encryption and decryption for the PDF standard (password) security
handler.

PDF 32000-2:2020 section 7.6.  Supported for reading:

- RC4, 40 to 128 bits (/V 1, 2 and 4, revisions 2 to 4), built in.
- AES-128 (/AESV2, /V 4) and AES-256 (/AESV3, /V 5, revisions 5 and 6),
  which need pycryptodome: ``pip install 'pdfrw-ng[crypto]'``.

`PdfReader` makes a `SecurityHandler` from the file's /Encrypt
dictionary and password, and decrypts each object's strings and stream
as the object is read.

For writing, `Encryption` describes how `PdfWriter(..., encrypt=...)`
encrypts its output: AES-256 (revision 6, the default), AES-128
(revision 4) or RC4 128-bit (revision 3).  All the arithmetic here is
on bytes.
"""

import hashlib
import os
import stringprep
import unicodedata

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None

try:
    from Crypto.Cipher import ARC4 as _ARC4
except ImportError:
    _ARC4 = None

from .errors import PdfDecryptionError, PdfOutputError, log
from .objects import PdfDict, PdfArray, PdfName, PdfObject, PdfString
from .py23_diffs import convert_load, convert_store

#: Whether pycryptodome is installed.  AES needs it; RC4 does not.
HAS_CRYPTO = AES is not None

_PASSWORD_PAD = (b'(\xbfN^Nu\x8aAd\x00NV\xff\xfa\x01\x08'
                 b'..\x00\xb6\xd0h>\x80/\x0c\xa9\xfedSiz')

_NEEDS_PYCRYPTODOME = ('This PDF is encrypted with AES, which needs '
                       'pycryptodome: pip install "pdfrw-ng[crypto]"')

_WRITE_NEEDS_PYCRYPTODOME = ('Encrypting with %s needs pycryptodome: '
                             'pip install "pdfrw-ng[crypto]"')


# -- primitives ------------------------------------------------------------

def rc4(key, data):
    """RC4-encrypt or decrypt `data` with `key` (both bytes)."""
    if _ARC4 is not None:
        return _ARC4.new(key).encrypt(data)
    state = list(range(256))
    j = 0
    keylen = len(key)
    for i in range(256):
        j = (j + state[i] + key[i % keylen]) & 0xFF
        state[i], state[j] = state[j], state[i]
    out = bytearray(data)
    i = j = 0
    for index in range(len(out)):
        i = (i + 1) & 0xFF
        j = (j + state[i]) & 0xFF
        state[i], state[j] = state[j], state[i]
        out[index] ^= state[(state[i] + state[j]) & 0xFF]
    return bytes(out)


def _aes_decrypt(key, data):
    """AES-CBC decrypt `data`, whose first 16 bytes are the IV, and
    remove the PKCS#7 padding.

    Damaged data is decrypted as far as it can be, with a warning,
    rather than failing the read.
    """
    if not data:
        return b''
    usable = len(data) - len(data) % 16
    if usable != len(data) or usable < 32:
        log.warning('AES-encrypted data is %d bytes, not an IV and whole '
                    'blocks; decrypting the first %d', len(data),
                    max(usable - 16, 0))
        if usable < 32:
            return b''
        data = data[:usable]
    plain = AES.new(key, AES.MODE_CBC, data[:16]).decrypt(data[16:])
    pad = plain[-1]
    if 1 <= pad <= 16 and plain[-pad:] == bytes((pad,)) * pad:
        return plain[:-pad]
    log.warning('Invalid padding in AES-encrypted data; keeping all of it')
    return plain


def _aes_encrypt(key, data):
    """AES-CBC encrypt `data` with PKCS#7 padding and a random IV, which
    is put first."""
    iv = os.urandom(16)
    pad = 16 - len(data) % 16
    return iv + AES.new(key, AES.MODE_CBC, iv).encrypt(
        data + bytes((pad,)) * pad)


def _object_key(key, num, gen, salt=b''):
    """The key for one object (Algorithm 1)."""
    data = (key + (num & 0xFFFFFF).to_bytes(3, 'little') +
            (gen & 0xFFFF).to_bytes(2, 'little') + salt)
    return hashlib.md5(data).digest()[:min(len(key) + 5, 16)]


def _bytes(value):
    """A PDF string (or None) as bytes."""
    if value is None:
        return b''
    if isinstance(value, bytes):
        return value
    if isinstance(value, PdfString):
        return value.to_bytes()
    return convert_store(str(value))


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def saslprep(text):
    """Prepare `text` with SASLprep (RFC 4013), as revisions 5 and 6
    require before a password is UTF-8 encoded.

    Treated as a query: unassigned code points are allowed.  Raises
    ValueError for a prohibited character or bad bidirectional text.
    """
    in_c12 = stringprep.in_table_c12
    in_b1 = stringprep.in_table_b1
    text = u''.join(u' ' if in_c12(ch) else ch for ch in text
                    if not in_b1(ch))
    text = unicodedata.normalize('NFKC', text)
    if not text:
        return text
    prohibited = (stringprep.in_table_c12, stringprep.in_table_c21_c22,
                  stringprep.in_table_c3, stringprep.in_table_c4,
                  stringprep.in_table_c5, stringprep.in_table_c6,
                  stringprep.in_table_c7, stringprep.in_table_c8,
                  stringprep.in_table_c9)
    for ch in text:
        if any(table(ch) for table in prohibited):
            raise ValueError('prohibited character U+%04X' % ord(ch))
    if any(stringprep.in_table_d1(ch) for ch in text):
        if any(stringprep.in_table_d2(ch) for ch in text):
            raise ValueError('mixes right-to-left and left-to-right text')
        if not (stringprep.in_table_d1(text[0]) and
                stringprep.in_table_d1(text[-1])):
            raise ValueError('right-to-left text must start and end with '
                             'a right-to-left character')
    return text


def _password_candidates(password, revision):
    """The byte strings to try as the password, best first.

    Revisions 2-4 hash the password in PDFDocEncoding.  Revisions 5 and
    6 hash its SASLprep form in UTF-8, at most 127 bytes; the password
    UTF-8 encoded as given is tried too, since some writers skip
    SASLprep.  Bytes are used as they are.
    """
    if password is None:
        password = b''
    if isinstance(password, (bytes, bytearray)):
        data = bytes(password)
        return [data[:127] if revision >= 5 else data]
    if revision < 5:
        try:
            return [password.encode('pdfdocencoding')]
        except UnicodeEncodeError:
            return [password.encode('utf-8')]
    candidates = []
    try:
        candidates.append(saslprep(password).encode('utf-8')[:127])
    except ValueError as exc:
        log.warning('Password is not valid for SASLprep (%s); using it '
                    'as given', exc)
    raw = password.encode('utf-8')[:127]
    if raw not in candidates:
        candidates.append(raw)
    return candidates


def _password_bytes(password, revision):
    """The password as the security handler hashes it (the first of
    `_password_candidates`)."""
    return _password_candidates(password, revision)[0]


# -- revisions 2 to 4 (RC4 and AES-128) ---------------------------------

def _file_key_r4(password, owner_hash, permissions, id0, revision, length,
                 encrypt_metadata=True):
    """The file key from a user password (Algorithm 2)."""
    hasher = hashlib.md5()
    hasher.update((password + _PASSWORD_PAD)[:32])
    hasher.update(owner_hash[:32])
    hasher.update((permissions & 0xFFFFFFFF).to_bytes(4, 'little'))
    hasher.update(id0)
    if revision >= 4 and not encrypt_metadata:
        hasher.update(b'\xff\xff\xff\xff')
    digest = hasher.digest()
    if revision >= 3:
        for _ in range(50):
            digest = hashlib.md5(digest[:length]).digest()
    return digest[:length]


def _user_hash_r4(key, id0, revision):
    """The /U value `key` gives (Algorithms 4 and 5).  For revision 3
    and up only the first 16 bytes are significant."""
    if revision < 3:
        return rc4(key, _PASSWORD_PAD)
    data = rc4(key, hashlib.md5(_PASSWORD_PAD + id0).digest())
    for i in range(1, 20):
        data = rc4(bytes(b ^ i for b in key), data)
    return data


def _user_hash_matches(key, user_hash, id0, revision):
    expected = _user_hash_r4(key, id0, revision)
    if revision < 3:
        return user_hash[:32] == expected
    return user_hash[:16] == expected


def _user_password_from_owner(password, owner_hash, revision, length):
    """The padded user password that the owner password `password`
    unlocks (Algorithm 7, using Algorithm 3's key)."""
    digest = hashlib.md5((password + _PASSWORD_PAD)[:32]).digest()
    if revision >= 3:
        for _ in range(50):
            digest = hashlib.md5(digest).digest()
    key = digest[:length]
    data = owner_hash[:32]
    if revision < 3:
        return rc4(key, data)
    for i in range(19, -1, -1):
        data = rc4(bytes(b ^ i for b in key), data)
    return data


# -- revisions 5 and 6 (AES-256) -----------------------------------------

def _hash_r6(password, salt, udata, revision):
    """The password hash of Algorithm 2.A (revision 5) or 2.B (6)."""
    digest = hashlib.sha256(password + salt + udata).digest()
    if revision < 6:
        return digest
    hashes = (hashlib.sha256, hashlib.sha384, hashlib.sha512)
    rounds = 0
    last = 0
    while rounds < 64 or last > rounds - 32:
        block = (password + digest + udata) * 64
        encrypted = AES.new(digest[:16], AES.MODE_CBC,
                            digest[16:32]).encrypt(block)
        digest = hashes[sum(encrypted[:16]) % 3](encrypted).digest()
        last = encrypted[-1]
        rounds += 1
    return digest[:32]


def _file_key_r6(password, encrypt, revision):
    """The file key for the user or owner `password`, or None."""
    owner_hash = _bytes(encrypt.O)[:48]
    user_hash = _bytes(encrypt.U)[:48]
    if len(owner_hash) < 48 or len(user_hash) < 48:
        raise PdfDecryptionError('The /O or /U entry of /Encrypt is too '
                                 'short for AES-256 encryption')
    if _hash_r6(password, user_hash[32:40], b'', revision) == \
            user_hash[:32]:
        intermediate = _hash_r6(password, user_hash[40:48], b'', revision)
        wrapped = _bytes(encrypt.UE)
    elif _hash_r6(password, owner_hash[32:40], user_hash, revision) == \
            owner_hash[:32]:
        intermediate = _hash_r6(password, owner_hash[40:48], user_hash,
                                revision)
        wrapped = _bytes(encrypt.OE)
    else:
        return None
    if len(wrapped) < 32:
        raise PdfDecryptionError('The /UE or /OE entry of /Encrypt is too '
                                 'short for AES-256 encryption')
    return AES.new(intermediate, AES.MODE_CBC, b'\0' * 16).decrypt(
        wrapped[:32])


def _check_perms(key, encrypt, revision, encrypt_metadata):
    """Check /Perms against /P and /EncryptMetadata (Algorithm 13).

    Returns True when they match.  Otherwise logs a warning and returns
    False: the permissions may have been tampered with, which matters
    only to software that enforces them, so the file is still read.
    """
    perms = _bytes(encrypt.Perms)
    if len(perms) < 16:
        if revision >= 6 or perms:
            log.warning('The /Perms entry of /Encrypt is missing or too '
                        'short; cannot check the permissions in /P')
        return False
    plain = AES.new(key, AES.MODE_ECB).decrypt(perms[:16])
    if plain[9:12] != b'adb':
        log.warning('The /Perms entry of /Encrypt does not decrypt to a '
                    'valid permissions block; /P may have been altered')
        return False
    problems = []
    permissions = _int(encrypt.P)
    if plain[:4] != (permissions & 0xFFFFFFFF).to_bytes(4, 'little'):
        problems.append('/P is %d but /Perms says %d' % (
            permissions, int.from_bytes(plain[:4], 'little', signed=True)))
    if plain[8:9] != (b'T' if encrypt_metadata else b'F'):
        problems.append('/EncryptMetadata is %s but /Perms says %s' % (
            str(encrypt_metadata).lower(),
            'true' if plain[8:9] == b'T' else 'false'))
    if problems:
        log.warning('Permissions in /Encrypt do not match /Perms (%s); '
                    'they may have been altered', '; '.join(problems))
        return False
    return True


# -- crypt filters -------------------------------------------------------

class IdentityCryptFilter(object):
    """Identity crypt filter: the data is not encrypted."""
    needs_aes = False

    def decrypt_data(self, num, gen, data):
        return data

    encrypt_data = decrypt_data


class RC4CryptFilter(object):
    """Crypt filter /V2 (and the RC4 of /V 1 and 2): RC4 with a key per
    object."""
    needs_aes = False

    def __init__(self, key):
        self._key = key

    def decrypt_data(self, num, gen, data):
        return rc4(_object_key(self._key, num, gen), data)

    encrypt_data = decrypt_data


class AESCryptFilter(object):
    """Crypt filter /AESV2: AES-128 with a key per object."""
    needs_aes = True

    def __init__(self, key):
        self._key = key

    def decrypt_data(self, num, gen, data):
        return _aes_decrypt(_object_key(self._key, num, gen, b'sAlT'), data)

    def encrypt_data(self, num, gen, data):
        return _aes_encrypt(_object_key(self._key, num, gen, b'sAlT'), data)


class AESV3CryptFilter(object):
    """Crypt filter /AESV3: AES-256 with the file key."""
    needs_aes = True

    def __init__(self, key):
        self._key = key

    def decrypt_data(self, num, gen, data):
        return _aes_decrypt(self._key, data)

    def encrypt_data(self, num, gen, data):
        return _aes_encrypt(self._key, data)


_CRYPT_METHODS = {
    PdfName.V2: RC4CryptFilter,
    PdfName.AESV2: AESCryptFilter,
    PdfName.AESV3: AESV3CryptFilter,
}


# -- the security handler ------------------------------------------------

class SecurityHandler(object):
    """The standard security handler of an encrypted document.

    Checks `password` against the /Encrypt dictionary `encrypt`, as the
    user password and then as the owner password, and raises
    `PdfDecryptionError` if it is neither, or if the encryption is not
    one this module supports.  `file_id` is the trailer's /ID array.

    Attributes: `key` (the file key), `filters` (crypt filter name to
    filter), `stream_filter` and `string_filter` (the defaults),
    `encrypt_metadata`, and for AES-256 `perms_ok`, whether /Perms
    matches /P and /EncryptMetadata (a mismatch is logged, not raised).
    """

    def __init__(self, encrypt, file_id=None, password=''):
        if not isinstance(encrypt, PdfDict):
            raise PdfDecryptionError('The /Encrypt entry of the trailer is '
                                     'not a dictionary')
        handler = encrypt.Filter
        if handler is not None and handler != PdfName.Standard:
            raise PdfDecryptionError(
                'This PDF uses the %s security handler; only /Standard '
                '(password) encryption is supported' % handler)
        version = _int(encrypt.V)
        revision = _int(encrypt.R)
        self.version, self.revision = version, revision
        self.encrypt_metadata = str(encrypt.EncryptMetadata) != 'false'

        identity = IdentityCryptFilter()
        filters = {PdfName.Identity: identity}
        if version in (1, 2):
            methods = {}
            default = PdfName.V2
            length = 5 if version == 1 else _key_bytes(encrypt.Length, 5)
        elif version == 4:
            methods = {}
            cf = encrypt.CF
            for name, params in (cf.iteritems() if isinstance(cf, PdfDict)
                                 else ()):
                if name == PdfName.Identity:
                    continue
                cfm = params.CFM if isinstance(params, PdfDict) else None
                if cfm in (None, PdfName('None')):
                    methods[name] = None
                elif cfm in (PdfName.V2, PdfName.AESV2):
                    methods[name] = cfm
                else:
                    raise PdfDecryptionError(
                        'Unsupported crypt filter method %s for %s' %
                        (cfm, name))
            default = None
            length = _key_bytes(encrypt.Length, 16)
        elif version == 5:
            if revision not in (5, 6):
                raise PdfDecryptionError(
                    'Unsupported AES-256 encryption revision %s' % revision)
            methods = {}
            cf = encrypt.CF
            for name, params in (cf.iteritems() if isinstance(cf, PdfDict)
                                 else ()):
                if name == PdfName.Identity:
                    continue
                cfm = params.CFM if isinstance(params, PdfDict) else None
                if cfm in (None, PdfName('None')):
                    methods[name] = None
                elif cfm == PdfName.AESV3:
                    methods[name] = cfm
                else:
                    raise PdfDecryptionError(
                        'Unsupported crypt filter method %s for %s' %
                        (cfm, name))
            default = None
            length = 32
        else:
            raise PdfDecryptionError(
                'Unsupported encryption: /V %s /R %s' %
                (encrypt.V, encrypt.R))

        if (version == 5 or PdfName.AESV2 in methods.values()) and \
                AES is None:
            raise PdfDecryptionError(_NEEDS_PYCRYPTODOME)

        key = None
        for password in _password_candidates(password, revision):
            if version == 5:
                key = _file_key_r6(password, encrypt, revision)
            else:
                key = self._file_key_r4(password, encrypt, file_id,
                                        revision, length)
            if key is not None:
                break
        if key is None:
            if password:
                raise PdfDecryptionError(
                    'The password is wrong: it is neither the user nor the '
                    'owner password of this encrypted PDF')
            raise PdfDecryptionError(
                'This PDF is encrypted and needs a password: '
                'PdfReader(..., password="...")')
        self.key = key
        if version == 5:
            self.perms_ok = _check_perms(key, encrypt, revision,
                                         self.encrypt_metadata)

        for name, method in methods.items():
            filters[name] = (identity if method is None
                             else _CRYPT_METHODS[method](key))
        self.filters = filters
        if default is not None:
            self.stream_filter = self.string_filter = \
                _CRYPT_METHODS[default](key)
        else:
            self.stream_filter = self._named_filter(encrypt.StmF, 'StmF')
            self.string_filter = self._named_filter(encrypt.StrF, 'StrF')

    def _file_key_r4(self, password, encrypt, file_id, revision, length):
        if revision == 2:
            length = 5
        owner_hash = _bytes(encrypt.O)
        user_hash = _bytes(encrypt.U)
        permissions = _int(encrypt.P)
        id0 = b''
        if isinstance(file_id, list) and len(file_id):
            id0 = _bytes(file_id[0])
        candidates = (password,
                      _user_password_from_owner(password, owner_hash,
                                                revision, length))
        for candidate in candidates:
            key = _file_key_r4(candidate, owner_hash, permissions, id0,
                               revision, length, self.encrypt_metadata)
            if _user_hash_matches(key, user_hash, id0, revision):
                return key
        return None

    def _named_filter(self, name, entry):
        if name is None:
            return self.filters[PdfName.Identity]
        result = self.filters.get(name)
        if result is None:
            raise PdfDecryptionError('/%s names %s, which is not a crypt '
                                     'filter in /CF' % (entry, name))
        return result

    # -- decrypting objects

    def decrypt_object(self, obj, key):
        """Decrypt the indirect object `obj` numbered `key`, a
        ``(number, generation)`` pair, as read from the file: its stream
        and the strings in it.  Returns the object, which is a new one
        when `obj` is itself a string.  Not for objects read from an
        object stream: the stream as a whole was encrypted, not them.
        """
        num, gen = key
        if isinstance(obj, PdfString):
            return self._decrypt_string(obj, num, gen)
        if isinstance(obj, PdfDict):
            if dict.get(obj, PdfName.Type) == PdfName.XRef:
                return obj      # Cross-reference streams are not encrypted
            if obj.stream is not None:
                self._decrypt_stream(obj, num, gen)
        if isinstance(obj, (PdfDict, PdfArray)):
            self._decrypt_strings(obj, num, gen)
        return obj

    def _decrypt_string(self, value, num, gen):
        try:
            data = value.to_bytes()
        except (ValueError, TypeError) as exc:
            log.warning('Cannot decrypt string in object %d %d: %s',
                        num, gen, exc)
            return value
        return PdfString.from_bytes(
            self.string_filter.decrypt_data(num, gen, data))

    def _decrypt_strings(self, container, num, gen):
        """Decrypt each string directly inside `container`: in it, or
        in dictionaries and arrays in it, but not in other indirect
        objects it refers to."""
        decrypt = self._decrypt_string
        stack = [container]
        while stack:
            item = stack.pop()
            if isinstance(item, PdfDict):
                # A signature's /Contents is not encrypted.
                signature = (dict.get(item, PdfName.Type) == PdfName.Sig or
                             PdfName.ByteRange in item)
                for name, value in list(dict.items(item)):
                    if isinstance(value, PdfString):
                        if not (signature and name == PdfName.Contents):
                            dict.__setitem__(item, name,
                                             decrypt(value, num, gen))
                    elif (isinstance(value, (PdfDict, PdfArray)) and
                          not value.indirect):
                        stack.append(value)
            else:
                for index, value in enumerate(list.__iter__(item)):
                    if isinstance(value, PdfString):
                        list.__setitem__(item, index,
                                         decrypt(value, num, gen))
                    elif (isinstance(value, (PdfDict, PdfArray)) and
                          not value.indirect):
                        stack.append(value)

    def _decrypt_stream(self, obj, num, gen):
        if vars(obj).get('decrypted'):
            return
        default = self.stream_filter
        if (not self.encrypt_metadata and
                dict.get(obj, PdfName.Type) == PdfName.Metadata):
            default = self.filters[PdfName.Identity]
        _decrypt_stream(obj, num, gen, default, self.filters)


def _key_bytes(length, default):
    """The key length in bytes from an /Length in bits."""
    length = _int(length, 0)
    if 40 <= length <= 256 and not length % 8:
        return min(length // 8, 16)
    if 5 <= length <= 16:       # Some writers give bytes, not bits
        return length
    return default


def _decrypt_stream(obj, num, gen, default_filter, filters):
    """Decrypt `obj`'s stream in place, with the crypt filter named by a
    /Crypt entry in its /Filter, or else `default_filter`."""
    crypt_filter = default_filter
    ftype = obj.Filter
    if ftype is not None:
        multiple = isinstance(ftype, list)
        ftypes = list(ftype) if multiple else [ftype]
        if ftypes and ftypes[0] == PdfName.Crypt:
            parms = obj.DecodeParms
            parms_key = PdfName.DecodeParms
            if parms is None and obj.DP is not None:
                parms, parms_key = obj.DP, PdfName.DP
            parmslist = (list(parms) if isinstance(parms, list)
                         else [parms])
            first = parmslist[0] if parmslist else None
            name = PdfName.Identity
            if isinstance(first, PdfDict) and first.Name is not None:
                name = first.Name
            crypt_filter = filters.get(name)
            if crypt_filter is None:
                raise PdfDecryptionError(
                    'Object %d %d uses crypt filter %s, which is not in '
                    '/CF' % (num, gen, name))
            ftypes = ftypes[1:]
            obj.Filter = (PdfArray(ftypes) if multiple and ftypes else
                          ftypes[0] if ftypes else None)
            if isinstance(parms, list):
                rest = parmslist[1:]
                obj[parms_key] = PdfArray(rest) if rest else None
            else:
                obj[parms_key] = None
    data = obj.stream
    if not isinstance(data, bytes):
        data = convert_store(data)
    obj.stream = convert_load(crypt_filter.decrypt_data(num, gen, data))
    obj.private.decrypted = True


# -- encrypting output -----------------------------------------------------

# method: (/V, /R, key bytes, crypt filter method, lowest PDF version)
_WRITE_METHODS = {
    'aes-256': (5, 6, 32, PdfName.AESV3, '2.0'),
    'aes-128': (4, 4, 16, PdfName.AESV2, '1.6'),
    'rc4-128': (2, 3, 16, None, '1.4'),
}


def _hex(data):
    return PdfString.from_bytes(data, 'hex')


def _owner_hash_r4(owner, user, length):
    """The /O value (Algorithm 3, revisions 3 and 4) for the passwords
    `owner` and `user` (bytes, unpadded)."""
    digest = hashlib.md5((owner + _PASSWORD_PAD)[:32]).digest()
    for _ in range(50):
        digest = hashlib.md5(digest).digest()
    key = digest[:length]
    data = rc4(key, (user + _PASSWORD_PAD)[:32])
    for i in range(1, 20):
        data = rc4(bytes(b ^ i for b in key), data)
    return data


class Encryption(object):
    """How `PdfWriter` encrypts its output, with the standard (password)
    security handler: ``PdfWriter(f, encrypt=Encryption(...))``.

    `user_password` opens the file; an empty one (the default) lets
    anyone open it, subject to `permissions`.  `owner_password` opens it
    with every permission; when None it is the user password.
    Passwords are str or bytes; for AES-256 a str is prepared with
    SASLprep and UTF-8 encoded, and for the others it must be in
    PDFDocEncoding (Latin-1, roughly).

    `method` is ``'aes-256'`` (revision 6, the default), ``'aes-128'``
    (revision 4) or ``'rc4-128'`` (revision 3, weak; only for old
    readers).  AES needs pycryptodome: ``pip install
    'pdfrw-ng[crypto]'``.

    `permissions` is the /P value, the bits of PDF 32000-2:2020 Table 22
    (4 print, 8 modify, 16 copy text, 32 annotate, 256 fill forms, 512
    extract for accessibility, 1024 assemble, 2048 high-quality print);
    the default -4 allows everything.  Reserved bits are set as the
    standard requires.  Readers that are not given the owner password
    are expected, not forced, to honour them.

    `encrypt_metadata=False` leaves XMP metadata streams readable
    without the password (AES only).

    The file is written as at least the PDF version the method needs:
    1.4 for RC4, 1.6 for AES-128 and 2.0 for AES-256.
    """

    def __init__(self, user_password='', owner_password=None,
                 method='aes-256', permissions=-4, encrypt_metadata=True):
        method = str(method).lower()
        if method not in _WRITE_METHODS:
            raise ValueError('Unknown encryption method %r; use one of %s'
                             % (method, ', '.join(sorted(_WRITE_METHODS))))
        version, revision, length, cfm, pdf_version = _WRITE_METHODS[method]
        if cfm is not None and AES is None:
            raise PdfOutputError(_WRITE_NEEDS_PYCRYPTODOME % method.upper())
        if not encrypt_metadata and revision < 4:
            raise ValueError('encrypt_metadata=False needs AES encryption')
        if owner_password is None:
            owner_password = user_password
        self.method = method
        self.version, self.revision, self.length = version, revision, length
        self.cfm = cfm
        self.pdf_version = pdf_version
        self.user = self._password(user_password, 'user')
        self.owner = self._password(owner_password, 'owner')
        self.permissions = _signed32((_int(permissions) | 0xFFFFF0C0) &
                                     0xFFFFFFFC)
        self.encrypt_metadata = bool(encrypt_metadata)

    def __repr__(self):
        return '<Encryption %s>' % self.method

    def _password(self, password, which):
        if isinstance(password, (bytes, bytearray)):
            data = bytes(password)
        elif not isinstance(password, str):
            raise TypeError('The %s password must be str or bytes, not %s'
                            % (which, type(password).__name__))
        elif self.revision >= 5:
            try:
                data = saslprep(password).encode('utf-8')
            except ValueError as exc:
                raise ValueError('The %s password is not valid for AES-256 '
                                 'encryption: %s' % (which, exc))
        else:
            try:
                data = password.encode('pdfdocencoding')
            except UnicodeEncodeError:
                raise ValueError(
                    'The %s password has characters that %s encryption '
                    'cannot use (it needs PDFDocEncoding); use AES-256 for '
                    'other characters' % (which, self.method.upper()))
        return data[:127] if self.revision >= 5 else data[:32]

    def start(self, file_id=None):
        """Set up encrypting one file whose trailer /ID is `file_id`
        (made when missing or malformed).  Returns an
        `EncryptionWriter`; each call makes new keys and salts."""
        if not (isinstance(file_id, list) and len(file_id) == 2 and
                all(isinstance(x, PdfString) for x in file_id)):
            first = _hex(os.urandom(16))
            file_id = PdfArray([first, _hex(first.to_bytes())])
        else:
            file_id = PdfArray(file_id)
        return EncryptionWriter(self, file_id)


class EncryptionWriter(object):
    """The keys and /Encrypt dictionary for one encrypted file.

    `encrypt_dict` and `file_id` go in the trailer; `encrypt_string`
    and `encrypt_stream` encrypt the data of object number `num`.
    """

    def __init__(self, settings, file_id):
        self.file_id = file_id
        self.encrypt_metadata = settings.encrypt_metadata
        revision = settings.revision
        encrypt = PdfDict(Filter=PdfName.Standard,
                          V=PdfObject(settings.version),
                          R=PdfObject(revision),
                          Length=PdfObject(settings.length * 8),
                          P=PdfObject(settings.permissions))
        encrypt.indirect = True
        if revision >= 5:
            key = self._setup_r6(settings, encrypt)
        else:
            key = self._setup_r4(settings, encrypt)
        self.key = key
        if settings.cfm is None:
            self.filter = RC4CryptFilter(key)
        else:
            encrypt.CF = PdfDict(StdCF=PdfDict(
                AuthEvent=PdfName.DocOpen, CFM=settings.cfm,
                Length=PdfObject(settings.length)))
            encrypt.StmF = encrypt.StrF = PdfName.StdCF
            self.filter = _CRYPT_METHODS[settings.cfm](key)
            if not settings.encrypt_metadata:
                encrypt.EncryptMetadata = PdfObject('false')
        self.encrypt_dict = encrypt

    def _setup_r6(self, settings, encrypt):
        """Algorithms 8 to 10."""
        key = os.urandom(32)
        salts = os.urandom(32)
        user, owner = settings.user, settings.owner
        u_hash = (_hash_r6(user, salts[:8], b'', 6) + salts[:16])
        ue = AES.new(_hash_r6(user, salts[8:16], b'', 6), AES.MODE_CBC,
                     b'\0' * 16).encrypt(key)
        o_hash = (_hash_r6(owner, salts[16:24], u_hash, 6) + salts[16:32])
        oe = AES.new(_hash_r6(owner, salts[24:32], u_hash, 6), AES.MODE_CBC,
                     b'\0' * 16).encrypt(key)
        perms = ((settings.permissions & 0xFFFFFFFF).to_bytes(4, 'little') +
                 b'\xff' * 4 +
                 (b'T' if settings.encrypt_metadata else b'F') + b'adb' +
                 os.urandom(4))
        encrypt.U, encrypt.UE = _hex(u_hash), _hex(ue)
        encrypt.O, encrypt.OE = _hex(o_hash), _hex(oe)
        encrypt.Perms = _hex(AES.new(key, AES.MODE_ECB).encrypt(perms))
        return key

    def _setup_r4(self, settings, encrypt):
        """Algorithms 2, 3 and 5."""
        revision, length = settings.revision, settings.length
        id0 = self.file_id[0].to_bytes()
        o_hash = _owner_hash_r4(settings.owner, settings.user, length)
        key = _file_key_r4(settings.user, o_hash, settings.permissions, id0,
                           revision, length, settings.encrypt_metadata)
        u_hash = _user_hash_r4(key, id0, revision) + os.urandom(16)
        encrypt.O, encrypt.U = _hex(o_hash), _hex(u_hash)
        return key

    def encrypt_string(self, num, value):
        """The PdfString `value` (or a str or bytes to write as a PDF
        string) encrypted for object `num`."""
        if not isinstance(value, PdfString):
            value = PdfString.encode(value)
        return PdfString.from_bytes(
            self.filter.encrypt_data(num, 0, value.to_bytes()))

    def encrypt_stream(self, num, obj, data):
        """`data`, the stream of the PdfDict `obj`, encrypted for object
        `num`.  Strings in, strings out, as `PdfDict.stream` holds."""
        if (not self.encrypt_metadata and
                dict.get(obj, PdfName.Type) == PdfName.Metadata):
            return data
        if not isinstance(data, bytes):
            data = convert_store(data)
        return convert_load(self.filter.encrypt_data(num, 0, data))


def _signed32(value):
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


# -- the upstream pdfrw 0.4 interface, kept for compatibility -------------

def streamobjects(mylist, isinstance=isinstance, PdfDict=PdfDict):
    for obj in mylist:
        if isinstance(obj, PdfDict) and obj.stream is not None:
            yield obj


def create_key(password, doc):
    """Create an encryption key (Algorithm 2) from the user password,
    for revisions 2 to 4.  `doc` has the /Encrypt and /ID entries."""
    encrypt = doc.Encrypt
    revision = _int(encrypt.R)
    length = 5 if revision == 2 else _key_bytes(
        encrypt.Length, 16 if _int(encrypt.V) == 4 else 5)
    return _file_key_r4(_password_bytes(password, revision),
                        _bytes(encrypt.O), _int(encrypt.P),
                        _bytes(doc.ID[0]) if doc.ID else b'', revision,
                        length, str(encrypt.EncryptMetadata) != 'false')


def create_user_hash(key, doc):
    """Create the user password hash (Algorithm 4/5)."""
    return _user_hash_r4(key, _bytes(doc.ID[0]) if doc.ID else b'',
                         _int(doc.Encrypt.R))


def check_user_password(key, doc):
    """Check that the user password is correct (Algorithm 6)."""
    return _user_hash_matches(key, _bytes(doc.Encrypt.U),
                              _bytes(doc.ID[0]) if doc.ID else b'',
                              _int(doc.Encrypt.R))


def decrypt_objects(objects, default_filter, filters):
    """Decrypt the streams of a list of indirect objects.

    The parameter default_filter specifies the default filter to use. The
    filters parameter is a dictionary of alternate filters to use when the
    object specifies an alternate filter locally.  Streams already
    decrypted are left alone.  `PdfReader` decrypts objects as it reads
    them, so it no longer calls this.
    """
    for obj in streamobjects(objects):
        if vars(obj).get('decrypted'):
            continue
        num, gen = obj.indirect
        _decrypt_stream(obj, num, gen, default_filter, filters)
