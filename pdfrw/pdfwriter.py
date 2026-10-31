# A part of pdfrw (https://github.com/pmaupin/pdfrw)
# Copyright (C) 2006-2015 Patrick Maupin, Austin, Texas
# MIT license -- See LICENSE.txt for details

'''
The PdfWriter class writes an entire PDF file out to disk.

The writing process is not at all optimized or organized.

An instance of the PdfWriter class has two methods:
    addpage(page)
and
    write(fname)

addpage() assumes that the pages are part of a valid
tree/forest of PDF objects.
'''
import gc
import io

from .objects import (PdfName, PdfArray, PdfDict, IndirectPdfDict,
                      PdfObject, PdfString)
from .compress import compress as do_compress
from .crypt import Encryption
from .errors import PdfOutputError, log
from .py23_diffs import iteritems, convert_store

NullObject = PdfObject('null')
NullObject.indirect = True
NullObject.Type = 'Null object'


def user_fmt(obj, isinstance=isinstance, float=float, str=str,
             basestring=(type(u''), type(b'')), encode=PdfString.encode):
    ''' This function may be replaced by the user for
        specialized formatting requirements.
    '''

    if isinstance(obj, basestring):
        return encode(obj)

    # PDF booleans and null are lower case (#37, #127).  Test bool before
    # float/int, since bool is a subclass of int.
    if obj is True:
        return 'true'
    if obj is False:
        return 'false'
    if obj is None:
        return 'null'

    # PDFs don't handle exponent notation
    if isinstance(obj, float):
            return ('%.9f' % obj).rstrip('0').rstrip('.')

    return str(obj)


def FormatObjects(f, trailer, version='1.3', compress=True, killobj=(),
                  user_fmt=user_fmt, do_compress=do_compress,
                  convert_store=convert_store, iteritems=iteritems,
                  id=id, isinstance=isinstance, getattr=getattr, len=len,
                  sum=sum, set=set, str=str, hasattr=hasattr, repr=repr,
                  enumerate=enumerate, list=list, dict=dict, tuple=tuple,
                  PdfArray=PdfArray, PdfDict=PdfDict, PdfObject=PdfObject,
                  encryption=None):
    ''' FormatObjects performs the actual formatting and disk write.
        Should be a class, was a class, turned into nested functions
        for performace (to reduce attribute lookups).

        `encryption`, a `crypt.EncryptionWriter`, encrypts the strings
        and streams of each indirect object, and adds its /Encrypt and
        /ID to (a copy of) the trailer.
    '''

    def f_write(s):
        f.write(convert_store(s))

    def add(obj):
        ''' Add an object to our list, if it's an indirect
            object.  Just format it if not.
        '''
        # Can't hash dicts, so just hash the object ID
        objid = id(obj)

        # Automatically set stream objects to indirect
        if isinstance(obj, PdfDict):
            indirect = obj.indirect or (obj.stream is not None)
        else:
            indirect = getattr(obj, 'indirect', False)

        if not indirect:
            if objid in visited:
                log.warning('Replicating direct %s object, '
                            'should be indirect for optimal file size' %
                            type(obj))
                obj = type(obj)(obj)
                objid = id(obj)
            visiting(objid)
            result = format_obj(obj)
            leaving(objid)
            return result

        objnum = indirect_dict_get(objid)

        # If we haven't seen the object yet, we need to
        # add it to the indirect object list.
        if objnum is None:
            swapped = swapobj(objid)
            if swapped is not None:
                old_id = objid
                obj = swapped
                objid = id(obj)
                objnum = indirect_dict_get(objid)
                if objnum is not None:
                    indirect_dict[old_id] = objnum
                    return '%s 0 R' % objnum
            objnum = len(objlist) + 1
            objlist_append(None)
            indirect_dict[objid] = objnum
            deferred.append((objnum - 1, obj))
        return '%s 0 R' % objnum

    def format_array(myarray, formatter):
        # Format array data into semi-readable ASCII
        if sum([len(x) for x in myarray]) <= 70:
            return formatter % space_join(myarray)
        return format_big(myarray, formatter)

    def format_big(myarray, formatter):
        bigarray = []
        count = 1000000
        for x in myarray:
            lenx = len(x) + 1
            count += lenx
            if count > 71:
                subarray = []
                bigarray.append(subarray)
                count = lenx
            subarray.append(x)
        return formatter % lf_join([space_join(x) for x in bigarray])

    def format_obj(obj):
        ''' format PDF object data into semi-readable ASCII.
            May mutually recurse with add() -- add() will
            return references for indirect objects, and add
            the indirect object to the list.
        '''
        while 1:
            if isinstance(obj, (list, dict, tuple)):
                if isinstance(obj, PdfArray):
                    myarray = [add(x) for x in obj]
                    return format_array(myarray, '[%s]')
                elif isinstance(obj, PdfDict):
                    if compress and obj.stream:
                        do_compress([obj])
                    pairs = [(getattr(x, 'encoded', None) or x, y)
                             for (x, y) in obj.iteritems()]
                    stream = obj.stream
                    num = crypt_num
                    if num is not None:
                        if stream is not None:
                            stream = encryption.encrypt_stream(num, obj,
                                                               stream)
                            pairs = [x for x in pairs if x[0] != '/Length']
                            pairs.append(('/Length', PdfObject(len(stream))))
                        # A signature's /Contents is not encrypted.
                        signature = (dict.get(obj, PdfName.Type) ==
                                     PdfName.Sig or PdfName.ByteRange in obj)
                    pairs.sort()
                    myarray = []
                    for key, value in pairs:
                        myarray.append(key)
                        if num is not None and signature and \
                                key == '/Contents':
                            set_crypt_num(None)
                            myarray.append(add(value))
                            set_crypt_num(num)
                        else:
                            myarray.append(add(value))
                    result = format_array(myarray, '<<%s>>')
                    if stream is not None:
                        result = ('%s\nstream\n%s\nendstream' %
                                  (result, stream))
                    return result
                obj = (PdfArray, PdfDict)[isinstance(obj, dict)](obj)
                continue

            # We assume that an object with an indirect
            # attribute knows how to represent itself to us.
            if crypt_num is not None and (
                    isinstance(obj, PdfString) or
                    (isinstance(obj, basestring) and
                     not hasattr(obj, 'indirect'))):
                return str(encryption.encrypt_string(crypt_num, obj))
            if hasattr(obj, 'indirect'):
                return str(getattr(obj, 'encoded', None) or obj)
            return user_fmt(obj)

    def set_crypt_num(num):
        nonlocal crypt_num
        crypt_num = num

    def format_deferred():
        while deferred:
            index, obj = deferred.pop()
            if encryption is not None and obj is not encrypt_dict:
                set_crypt_num(index + 1)
            objlist[index] = format_obj(obj)
            set_crypt_num(None)

    indirect_dict = {}
    indirect_dict_get = indirect_dict.get
    objlist = []
    objlist_append = objlist.append
    visited = set()
    visiting = visited.add
    leaving = visited.remove
    space_join = ' '.join
    lf_join = '\n  '.join

    deferred = []

    # The number of the indirect object being formatted, when its strings
    # and stream are to be encrypted.
    crypt_num = None
    basestring = (str, bytes)
    encrypt_dict = None
    if encryption is not None:
        encrypt_dict = encryption.encrypt_dict
        trailer = PdfDict(trailer)
        trailer.Encrypt = encrypt_dict
        trailer.ID = encryption.file_id

    # Don't reference old catalog or pages objects --
    # swap references to new ones.
    type_remap = {PdfName.Catalog: trailer.Root,
               PdfName.Pages: trailer.Root.Pages, None: trailer}.get
    swapobj = [(objid, type_remap(obj.Type) if new_obj is None else new_obj)
               for objid, (obj, new_obj) in iteritems(killobj)]
    swapobj = dict((objid, obj is None and NullObject or obj)
                   for objid, obj in swapobj).get

    for objid in killobj:
        assert swapobj(objid) is not None

    # The first format of trailer gets all the information,
    # but we throw away the actual trailer formatting.
    format_obj(trailer)
    # Keep formatting until we're done.
    # (Used to recurse inside format_obj for this, but
    #  hit system limit.)
    format_deferred()
    # Now we know the size, so we update the trailer dict
    # and get the formatted data.
    trailer.Size = PdfObject(len(objlist) + 1)
    trailer = format_obj(trailer)

    # Now we have all the pieces to write out to the file.
    # Keep careful track of the counts while we do it so
    # we can correctly build the cross-reference.

    header = '%%PDF-%s\n%%\xe2\xe3\xcf\xd3\n' % version
    f_write(header)
    offset = len(header)
    offsets = [(0, 65535, 'f')]
    offsets_append = offsets.append

    for i, x in enumerate(objlist):
        objstr = '%s 0 obj\n%s\nendobj\n' % (i + 1, x)
        offsets_append((offset, 0, 'n'))
        offset += len(objstr)
        f_write(objstr)

    f_write('xref\n0 %s\n' % len(offsets))
    for x in offsets:
        f_write('%010d %05d %s\r\n' % x)
    f_write('trailer\n\n%s\nstartxref\n%s\n%%%%EOF\n' % (trailer, offset))


def _later_version(version, minimum):
    ''' The later of two PDF versions, such as '1.3' and '2.0'. '''
    def key(value):
        try:
            return tuple(int(x) for x in str(value).split('.'))
        except ValueError:
            return ()
    return version if key(version) >= key(minimum) else minimum


class PdfWriter(object):

    _trailer = None
    canonicalize = False
    fname = None
    encrypt = None

    def __init__(self, fname=None, version='1.3', compress=False,
                 encrypt=None, **kwargs):
        """
            Parameters:
                fname -- Output file name, or file-like binary object
                         with a write method
                version -- PDF version to target.  Currently only 1.3
                           supported.
                compress -- True to do compression on output.  Currently
                            compresses stream objects.
                encrypt -- None (the default) to write the file
                           unencrypted, or a `pdfrw.Encryption` giving
                           the passwords, method and permissions to
                           encrypt it with.
        """

        # Legacy support:  fname is new, was added in front
        if fname is not None:
            try:
                float(fname)
            except (ValueError, TypeError):
                pass
            else:
                if version != '1.3':
                    assert compress == False
                    compress = version
                version = fname
                fname = None

        self.fname = fname
        self.version = version
        self.compress = compress
        if encrypt is not None and not isinstance(encrypt, Encryption):
            raise TypeError('encrypt must be None or a pdfrw.Encryption, '
                            'not %s' % type(encrypt).__name__)
        self.encrypt = encrypt

        if kwargs:
            for name, value in iteritems(kwargs):
                if name not in self.replaceable:
                    raise ValueError("Cannot set attribute %s "
                                     "on PdfWriter instance" % name)
                setattr(self, name, value)

        self.pagearray = PdfArray()
        self.killobj = {}

    def addpage(self, page):
        self._trailer = None
        if page.Type != PdfName.Page:
            raise PdfOutputError('Bad /Type:  Expected %s, found %s'
                                 % (PdfName.Page, page.Type))
        inheritable = page.inheritable  # searches for resources
        self.pagearray.append(
            IndirectPdfDict(
                page,
                Resources=inheritable.Resources,
                MediaBox=inheritable.MediaBox,
                CropBox=inheritable.CropBox,
                Rotate=inheritable.Rotate,
            )
        )

        # Add parents in the hierarchy to objects we
        # don't want to output
        killobj = self.killobj
        obj, new_obj = page, self.pagearray[-1]
        while obj is not None:
            objid = id(obj)
            if objid in killobj:
                break
            killobj[objid] = obj, new_obj
            obj = obj.Parent
            new_obj = None
        return self

    addPage = addpage  # for compatibility with pyPdf

    def addpages(self, pagelist):
        for page in pagelist:
            self.addpage(page)
        return self

    def _get_trailer(self):
        trailer = self._trailer
        if trailer is not None:
            return trailer

        if self.canonicalize:
            self.make_canonical()

        # Create the basic object structure of the PDF file
        trailer = PdfDict(
            Root=IndirectPdfDict(
                Type=PdfName.Catalog,
                Pages=IndirectPdfDict(
                    Type=PdfName.Pages,
                    Count=PdfObject(len(self.pagearray)),
                    Kids=self.pagearray
                )
            )
        )
        # Make all the pages point back to the page dictionary and
        # ensure they are indirect references
        pagedict = trailer.Root.Pages
        for page in pagedict.Kids:
            page.Parent = pagedict
            page.indirect = True
        self._trailer = trailer
        return trailer

    def _set_trailer(self, trailer):
        self._trailer = trailer

    trailer = property(_get_trailer, _set_trailer)

    def write(self, fname=None, trailer=None, user_fmt=user_fmt,
              disable_gc=True):

        trailer = trailer or self.trailer

        # Support fname for legacy applications
        if (fname is not None) == (self.fname is not None):
            raise PdfOutputError(
                "PdfWriter fname must be specified exactly once")

        fname = fname or self.fname

        # Format the whole file in memory first, so that an error while
        # formatting never truncates or half-writes the target file
        # (#135, #160).  We either have a filename or a preexisting
        # file object.
        version = self.version
        encryption = None
        if self.encrypt is not None:
            encryption = self.encrypt.start(trailer.ID)
            version = _later_version(version, self.encrypt.pdf_version)

        buf = io.BytesIO()
        if disable_gc:
            gc.disable()
        try:
            FormatObjects(buf, trailer, version, self.compress,
                          self.killobj, user_fmt=user_fmt,
                          encryption=encryption)
        finally:
            if disable_gc:
                gc.enable()
        data = buf.getvalue()
        del buf

        if hasattr(fname, 'write'):
            fname.write(data)
        else:
            with open(fname, 'wb') as f:
                f.write(data)

    def make_canonical(self):
        ''' Canonicalizes a PDF.  Assumes everything
            is a Pdf object already.
        '''
        visited = set()
        workitems = list(self.pagearray)
        while workitems:
            obj = workitems.pop()
            objid = id(obj)
            if objid in visited:
                continue
            visited.add(objid)
            obj.indirect = False
            if isinstance(obj, (PdfArray, PdfDict)):
                obj.indirect = True
                if isinstance(obj, PdfArray):
                    workitems += obj
                else:
                    workitems += obj.values()

    replaceable = set(vars())