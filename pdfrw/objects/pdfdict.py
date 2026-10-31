# A part of pdfrw (https://github.com/pmaupin/pdfrw)
# Copyright (C) 2006-2015 Patrick Maupin, Austin, Texas
# MIT license -- See LICENSE.txt for details

from .pdfname import PdfName, BasePdfName
from .pdfindirect import PdfIndirect
from .pdfobject import PdfObject
from ._compare import pdf_equal
from ..py23_diffs import iteritems
from ..errors import PdfParseError


class _DictSearch(object):
    '''  Used to search for inheritable attributes.
    '''

    def __init__(self, basedict):
        self.basedict = basedict

    def __getattr__(self, name, PdfName=PdfName):
        if name[:2] == name[-2:] == '__':
            raise AttributeError(name)
        return self[PdfName(name)]

    def __getitem__(self, name, set=set, getattr=getattr, id=id):
        visited = set()
        mydict = self.basedict
        while 1:
            value = mydict[name]
            if value is not None:
                return value
            myid = id(mydict)
            assert myid not in visited
            visited.add(myid)
            mydict = mydict.Parent
            if mydict is None:
                return


class _Private(object):
    ''' Used to store private attributes (not output to PDF files)
        on PdfDict classes
    '''

    def __init__(self, pdfdict):
        vars(self)['pdfdict'] = pdfdict

    def __setattr__(self, name, value):
        vars(self.pdfdict)[name] = value


class PdfDict(dict):
    ''' PdfDict objects are subclassed dictionaries
        with the following features:

        - Every key in the dictionary starts with "/"

        - A dictionary item can be deleted by assigning it to None

        - Keys that (after the initial "/") conform to Python
          naming conventions can also be accessed (set and retrieved)
          as attributes of the dictionary.  E.g.  mydict.Page is the
          same thing as mydict['/Page']

        - Private attributes (not in the PDF space) can be set
          on the dictionary object attribute dictionary by using
          the private attribute:

                mydict.private.foo = 3
                mydict.foo = 5
                x = mydict.foo       # x will now contain 3
                y = mydict['/foo']   # y will now contain 5

          Most standard adobe dictionary keys start with an upper case letter,
          so to avoid conflicts, it is best to start private attributes with
          lower case letters.

        - PdfDicts have the following read-only properties:

            - private -- as discussed above, provides write access to
                         dictionary's attributes
            - inheritable -- this creates and returns a "view" attribute
                         that will search through the object hierarchy for
                         any desired attribute, such as /Rotate or /MediaBox

        - PdfDicts also have the following special attributes:
            - indirect is not stored in the PDF dictionary, but in the object's
              attribute dictionary
            - stream is also stored in the object's attribute dictionary
              and will also update the stream length.
            - _stream will store in the object's attribute dictionary without
              updating the stream length.

            It is possible, for example, to have a PDF name such as "/indirect"
            or "/stream", but you cannot access such a name as an attribute:

                mydict.indirect -- accesses object's attribute dictionary
                mydict["/indirect"] -- accesses actual PDF dictionary
    '''
    indirect = False
    stream = None

    _special = dict(indirect=('indirect', False),
                    stream=('stream', True),
                    _stream=('stream', False),
                    )

    def __setitem__(self, name, value, setter=dict.__setitem__,
                    BasePdfName=BasePdfName, isinstance=isinstance):
        if not isinstance(name, BasePdfName):
            raise PdfParseError('Dict key %s is not a PdfName' % repr(name))
        if value is not None:
            setter(self, name, value)
        elif name in self:
            del self[name]

    def __init__(self, *args, **kw):
        if args:
            if len(args) == 1:
                args = args[0]
            self.update(args)
            if isinstance(args, PdfDict):
                self.indirect = args.indirect
                self._stream = args.stream
        for key, value in iteritems(kw):
            setattr(self, key, value)

    def update(self, *args, **kw):
        ''' Like dict.update, but every key must be a PdfName, as for
            item assignment, and a value of None deletes its key.  Keyword
            arguments are set as attributes, as in the constructor, so
            d.update(Type=PdfName.Page) sets /Type.

            The keys are checked before anything changes, so a bad key
            leaves the dictionary as it was, instead of failing later
            when the file is written (#135).
        '''
        if len(args) > 1:
            raise TypeError('update expected at most 1 argument, got %d'
                            % len(args))
        if args:
            other, = args
            if isinstance(other, dict):
                # Raw values, so indirect objects stay unresolved.
                pairs = list(dict.items(other))
            elif hasattr(other, 'keys'):
                pairs = [(key, other[key]) for key in other.keys()]
            else:
                pairs = [tuple(pair) for pair in other]
                for pair in pairs:
                    if len(pair) != 2:
                        raise ValueError('dictionary update sequence '
                                         'element has length %d; 2 is '
                                         'required' % len(pair))
            for key, value in pairs:
                if not isinstance(key, BasePdfName):
                    raise PdfParseError('Dict key %s is not a PdfName'
                                        % repr(key))
            for key, value in pairs:
                self[key] = value
        for key, value in iteritems(kw):
            setattr(self, key, value)

    def setdefault(self, key, default=None):
        ''' Like dict.setdefault, but the key must be a PdfName, indirect
            objects are resolved, and a default of None is not stored
            (#135).
        '''
        value = self.get(key)
        if value is None:
            self[key] = value = default
        return value

    def __getattr__(self, name, PdfName=PdfName):
        ''' If the attribute doesn't exist on the dictionary object,
            try to slap a '/' in front of it and get it out
            of the actual dictionary itself.

            Names like __deepcopy__ are Python protocol lookups, not PDF
            names: they raise AttributeError, so that copy and pickle
            work (#141).
        '''
        if name[:2] == name[-2:] == '__':
            raise AttributeError(name)
        return self.get(PdfName(name))

    def __eq__(self, other, pdf_equal=pdf_equal):
        ''' Structural comparison that is safe for the cycles in a page
            tree (#212).  The streams of stream objects are compared too.
        '''
        if not isinstance(other, dict):
            return NotImplemented
        return pdf_equal(self, other)

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    __hash__ = None

    def get(self, key, dictget=dict.get, isinstance=isinstance,
            PdfIndirect=PdfIndirect):
        ''' Get a value out of the dictionary,
            after resolving any indirect objects.
        '''
        value = dictget(self, key)
        if isinstance(value, PdfIndirect):
            # We used to use self[key] here, but that does an
            # unwanted check on the type of the key (github issue #98).
            # Python will keep the old key object in the dictionary,
            # so that check is not necessary.
            value = value.real_value()
            if value is not None:
                dict.__setitem__(self, key, value)
            else:
                del self[key]
        return value

    def __getitem__(self, key):
        return self.get(key)

    def __setattr__(self, name, value, special=_special.get,
                    PdfName=PdfName, vars=vars):
        ''' Set an attribute on the dictionary.  Handle the keywords
            indirect, stream, and _stream specially (for content objects)
        '''
        info = special(name)
        if info is None:
            self[PdfName(name)] = value
        else:
            name, setlen = info
            vars(self)[name] = value
            if setlen:
                notnone = value is not None
                self.Length = notnone and PdfObject(len(value)) or None

    def iteritems(self, dictiter=iteritems,
                  isinstance=isinstance, PdfIndirect=PdfIndirect,
                  BasePdfName=BasePdfName):
        ''' Iterate over the dictionary, resolving any unresolved objects
        '''
        for key, value in list(dictiter(self)):
            if isinstance(value, PdfIndirect):
                self[key] = value = value.real_value()
            if value is not None:
                if not isinstance(key, BasePdfName):
                    raise PdfParseError('Dict key %s is not a PdfName' %
                                        repr(key))
                yield key, value

    def items(self):
        return list(self.iteritems())

    def itervalues(self):
        for key, value in self.iteritems():
            yield value

    def values(self):
        return list((value for key, value in self.iteritems()))

    def keys(self):
        return list((key for key, value in self.iteritems()))

    def __iter__(self):
        for key, value in self.iteritems():
            yield key

    def iterkeys(self):
        return iter(self)

    def copy(self):
        return type(self)(self)

    def pop(self, key, *default):
        ''' Like dict.pop: remove key and return its value, resolving an
            indirect object.  A missing key (or one whose indirect object
            resolves to null) returns default if one is given, and raises
            KeyError if not.
        '''
        if len(default) > 1:
            raise TypeError('pop expected at most 2 arguments, got %d'
                            % (len(default) + 1))
        value = self.get(key)
        if value is None:
            if default:
                return default[0]
            raise KeyError(key)
        dict.__delitem__(self, key)
        return value

    def popitem(self):
        ''' Like dict.popitem: remove and return a (key, value) pair,
            resolving an indirect object.  Entries whose indirect object
            resolves to null are dropped, as if they were never there.
            Raises KeyError when the dictionary is empty.
        '''
        while 1:
            key, value = dict.popitem(self)
            if isinstance(value, PdfIndirect):
                value = value.real_value()
            if value is not None:
                return key, value

    def inheritable(self):
        ''' Search through ancestors as needed for inheritable
            dictionary items.
            NOTE:  You might think it would be a good idea
            to cache this class, but then you'd have to worry
            about it pointing to the wrong dictionary if you
            made a copy of the object...
        '''
        return _DictSearch(self)
    inheritable = property(inheritable)

    def private(self):
        ''' Allows setting private metadata for use in
            processing (not sent to PDF file).
            See note on inheritable
        '''
        return _Private(self)
    private = property(private)


class IndirectPdfDict(PdfDict):
    ''' IndirectPdfDict is a convenience class.  You could
        create a direct PdfDict and then set indirect = True on it,
        or you could just create an IndirectPdfDict.
    '''
    indirect = True
