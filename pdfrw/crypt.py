# A part of pdfrw (https://github.com/pmaupin/pdfrw)
# Copyright (C) 2017  Jon Lund Steffensen
# MIT license -- See LICENSE.txt for details

"""Decryption for the PDF standard (password) security handler.

PDF 32000-2:2020 section 7.6.  Supported:

- RC4, 40 to 128 bits (/V 1, 2 and 4, revisions 2 to 4), built in.
- AES-128 (/AESV2, /V 4) and AES-256 (/AESV3, /V 5, revisions 5 and 6),
  which need pycryptodome: ``pip install 'pdfrw-ng[crypto]'``.

`PdfReader` makes a `SecurityHandler` from the file's /Encrypt
dictionary and password, and decrypts each object's strings and stream
as the object is read.  All the arithmetic here is on bytes.
"""

import hashlib

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None

try:
    from Crypto.Cipher import ARC4 as _ARC4
except ImportError:
    _ARC4 = None

from .errors import PdfDecryptionError, log
from .objects import PdfDict, PdfArray, PdfName, PdfString
from .py23_diffs import convert_load, convert_store

#: Whether pycryptodome is installed.  AES needs it; RC4 does not.
HAS_CRYPTO = AES is not None

_PASSWORD_PAD = (b'(\xbfN^Nu\x8aAd\x00NV\xff\xfa\x01\x08'
                 b'..\x00\xb6\xd0h>\x80/\x0c\xa9\xfedSiz')

_NEEDS_PYCRYPTODOME = ('This PDF is encrypted with AES, which needs '
                       'pycryptodome: pip install "pdfrw-ng[crypto]"')


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


def _password_bytes(password, revision):
    """The password as the security handler hashes it: PDFDocEncoding
    for revisions 2-4, UTF-8 (at most 127 bytes) for 5 and 6."""
    if password is None:
        password = b''
    if isinstance(password, (bytes, bytearray)):
        data = bytes(password)
    elif revision >= 5:
        data = password.encode('utf-8')
    else:
        try:
            data = password.encode('pdfdocencoding')
        except UnicodeEncodeError:
            data = password.encode('utf-8')
    return data[:127] if revision >= 5 else data


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


# -- crypt filters -------------------------------------------------------

class IdentityCryptFilter(object):
    """Identity crypt filter: the data is not encrypted."""
    needs_aes = False

    def decrypt_data(self, num, gen, data):
        return data


class RC4CryptFilter(object):
    """Crypt filter /V2 (and the RC4 of /V 1 and 2): RC4 with a key per
    object."""
    needs_aes = False

    def __init__(self, key):
        self._key = key

    def decrypt_data(self, num, gen, data):
        return rc4(_object_key(self._key, num, gen), data)


class AESCryptFilter(object):
    """Crypt filter /AESV2: AES-128 with a key per object."""
    needs_aes = True

    def __init__(self, key):
        self._key = key

    def decrypt_data(self, num, gen, data):
        return _aes_decrypt(_object_key(self._key, num, gen, b'sAlT'), data)


class AESV3CryptFilter(object):
    """Crypt filter /AESV3: AES-256 with the file key."""
    needs_aes = True

    def __init__(self, key):
        self._key = key

    def decrypt_data(self, num, gen, data):
        return _aes_decrypt(self._key, data)


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
    `encrypt_metadata`.
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

        password = _password_bytes(password, revision)
        if version == 5:
            key = _file_key_r6(password, encrypt, revision)
        else:
            key = self._file_key_r4(password, encrypt, file_id, revision,
                                    length)
        if key is None:
            if password:
                raise PdfDecryptionError(
                    'The password is wrong: it is neither the user nor the '
                    'owner password of this encrypted PDF')
            raise PdfDecryptionError(
                'This PDF is encrypted and needs a password: '
                'PdfReader(..., password="...")')
        self.key = key

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
