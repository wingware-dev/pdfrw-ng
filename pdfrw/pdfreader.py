# A part of pdfrw (https://github.com/pmaupin/pdfrw)
# Copyright (C) 2006-2015 Patrick Maupin, Austin, Texas
# Copyright (C) 2012-2015 Nerijus Mika
# MIT license -- See LICENSE.txt for details

'''
The PdfReader class reads an entire PDF file into memory and
parses the top-level container objects.  (It does not parse
into streams.)  The object subclasses PdfDict, and the
document pages are stored in a list in the pages attribute
of the object.
'''
import gc
import binascii
import bisect
import itertools
import re

from .errors import PdfParseError, log
from .tokens import PdfTokens
from .objects import PdfDict, PdfArray, PdfName, PdfObject, PdfIndirect
from .uncompress import uncompress
from . import crypt
from .py23_diffs import convert_load, convert_store, iteritems


class PdfReader(PdfDict):

    def findindirect(self, objnum, gennum, PdfIndirect=PdfIndirect, int=int):
        ''' Return a previously loaded indirect object, or create
            a placeholder for it.
        '''
        key = int(objnum), int(gennum)
        result = self.indirect_objects.get(key)
        if result is None:
            self.indirect_objects[key] = result = PdfIndirect(key)
            self.deferred_objects.add(key)
            result._loader = self.loadindirect
        return result

    def readarray(self, source, PdfArray=PdfArray):
        ''' Found a [ token.  Parse the tokens after that.
        '''
        specialget = self.special.get
        result = []
        pop = result.pop
        append = result.append

        for value in source:
            if value in ']R':
                if value == ']':
                    break
                generation = pop()
                value = self.findindirect(pop(), generation)
            else:
                func = specialget(value)
                if func is not None:
                    value = func(source)
            append(value)
        return PdfArray(result)

    def readdict(self, source, PdfDict=PdfDict):
        ''' Found a << token.  Parse the tokens after that.
        '''
        specialget = self.special.get
        result = PdfDict()
        next = source.next

        tok = next()
        while tok != '>>':
            if not tok.startswith('/'):
                source.error('Expected PDF /name object')
                tok = next()
                continue
            key = tok
            value = next()
            func = specialget(value)
            if func is not None:
                value = func(source)
                tok = next()
            else:
                tok = next()
                if value.isdigit() and tok.isdigit():
                    tok2 = next()
                    if tok2 != 'R':
                        source.error('Expected "R" following two integers')
                        tok = tok2
                        continue
                    value = self.findindirect(value, tok)
                    tok = next()
            result[key] = value
        return result

    def empty_obj(self, source, PdfObject=PdfObject):
        ''' Some silly git put an empty object in the
            file.  Back up so the caller sees the endobj.
        '''
        source.floc = source.tokstart

    def badtoken(self, source):
        ''' Didn't see that coming.
        '''
        source.exception('Unexpected delimiter')

    def findstream(self, obj, tok, source, len=len):
        ''' Figure out if there is a content stream
            following an object, and return the start
            pointer to the content stream if so.

            (We can't read it yet, because we might not
            know how long it is, because Length might
            be an indirect object.)
        '''

        fdata = source.fdata
        startstream = source.tokstart + len(tok)
        gotcr = fdata[startstream:startstream + 1] == '\r'
        startstream += gotcr
        gotlf = fdata[startstream:startstream + 1] == '\n'
        startstream += gotlf
        if not gotlf:
            if not gotcr:
                source.error(r'stream keyword not followed by \n')
            else:
                source.warning(r"stream keyword terminated "
                               r"by \r without \n")
        return startstream

    def readstream(self, obj, startstream, source, exact_required=False,
                   streamending='endstream endobj'.split(), int=int):
        fdata = source.fdata
        maxstream = len(fdata)
        try:
            length = int(obj.Length)
        except (TypeError, ValueError):
            length = None
        if length is None or length < 0 or startstream + length > maxstream:
            # A missing or unusable /Length, or one that runs past the
            # end of the file (#199): find the stream's end instead.
            if exact_required:
                source.exception('Invalid stream /Length %r', obj.Length)
            source.error('stream /Length %s is invalid or runs past the '
                         'end of the file -- searching for endstream',
                         obj.Length)
            endstream = fdata.find('endstream', startstream)
            if endstream < 0:
                source.error('Could not find endstream')
                obj.stream = fdata[startstream:]
                source.floc = maxstream
                return
            end = endstream
            if fdata[end - 1:end] == '\n':
                end -= 1
            if fdata[end - 1:end] == '\r':
                end -= 1
            obj.stream = fdata[startstream:end]
            source.floc = endstream + len('endstream')
            if source.next_default() != 'endobj':
                source.error('Expected endobj after endstream')
            return
        source.floc = target_endstream = startstream + length
        endit = source.multiple(2)
        obj._stream = fdata[startstream:target_endstream]
        if endit == streamending:
            return

        if exact_required:
            source.exception('Expected endstream endobj')

        # The length attribute does not match the distance between the
        # stream and endstream keywords.
        endstream = fdata.find('endstream', startstream, maxstream)
        source.floc = startstream
        room = endstream - startstream
        if endstream < 0:
            source.error('Could not find endstream')
            return
        if (length == room + 1 and
                fdata[startstream - 2:startstream] == '\r\n'):
            source.warning(r"stream keyword terminated by \r without \n")
            obj._stream = fdata[startstream - 1:target_endstream - 1]
            return
        source.floc = endstream
        if length > room:
            source.error('stream /Length attribute (%d) appears to '
                         'be too big (size %d) -- adjusting',
                         length, room)
            obj.stream = fdata[startstream:endstream]
            return
        if fdata[target_endstream:endstream].rstrip():
            source.error('stream /Length attribute (%d) appears to '
                         'be too small (size %d) -- adjusting',
                         length, room)
            obj.stream = fdata[startstream:endstream]
            return
        endobj = fdata.find('endobj', endstream, maxstream)
        if endobj < 0:
            source.error('Could not find endobj after endstream')
            return
        if fdata[endstream:endobj].rstrip() != 'endstream':
            source.error('Unexpected data between endstream and endobj')
            return
        source.error('Illegal endstream/endobj combination')

    def loadindirect(self, key):
        ''' Load indirect object `key`, a (number, generation) pair.

            An object that cannot be parsed, such as one cut off by the
            end of the file (#145), logs an error and reads as None (or
            as far as it was parsed), instead of failing the whole read.

            In an encrypted file the object is decrypted as it is read
            (#48, #123).
        '''
        pending = isinstance(self.indirect_objects.get(key), PdfIndirect)
        try:
            result = self._loadindirect(key)
        except (PdfParseError, StopIteration) as exc:
            log.error('Could not read PDF object %d %d: %s', key[0], key[1],
                      exc or 'unexpected end of file')
            self.deferred_objects.discard(key)
            result = self.indirect_objects.get(key)
            if isinstance(result, PdfIndirect):
                return None
        handler = self.crypt_handler
        if pending and result is not None and handler is not None:
            key = tuple(key)
            decrypted = handler.decrypt_object(result, key)
            if decrypted is not result:
                decrypted.indirect = key
                self.indirect_objects[key] = result = decrypted
        return result

    def _loadindirect(self, key, PdfDict=PdfDict, isinstance=isinstance):
        result = self.indirect_objects.get(key)
        if not isinstance(result, PdfIndirect):
            return result
        source = self.source
        offset = int(self.source.obj_offsets.get(key, '0'))
        if not offset:
            source.warning("Did not find PDF object %s", key)
            return None

        # Read the object header and validate it
        objnum, gennum = key
        source.floc = offset
        objid = source.multiple(3)
        ok = len(objid) == 3
        ok = ok and objid[0].isdigit() and int(objid[0]) == objnum
        ok = ok and objid[1].isdigit() and int(objid[1]) == gennum
        ok = ok and objid[2] == 'obj'
        if not ok:
            source.floc = offset
            source.next()
            objheader = '%d %d obj' % (objnum, gennum)
            fdata = source.fdata
            offset2 = (fdata.find('\n' + objheader) + 1 or
                       fdata.find('\r' + objheader) + 1)
            if (not offset2 or
                    fdata.find(fdata[offset2 - 1] + objheader, offset2) > 0):
                source.warning("Expected indirect object '%s'", objheader)
                return None
            source.warning("Indirect object %s found at incorrect "
                           "offset %d (expected offset %d)",
                           objheader, offset2, offset)
            source.floc = offset2 + len(objheader)

        # Read the object, and call special code if it starts
        # an array or dictionary
        obj = source.next()
        func = self.special.get(obj)
        if func is not None:
            obj = func(source)

        self.indirect_objects[key] = obj
        self.deferred_objects.remove(key)

        # Mark the object as indirect, and
        # just return it if it is a simple object.
        obj.indirect = key
        tok = source.next()
        if tok == 'endobj':
            return obj

        # Should be a stream.  Either that or it's broken.
        isdict = isinstance(obj, PdfDict)
        if isdict and tok == 'stream':
            self.readstream(obj, self.findstream(obj, tok, source), source)
            return obj

        # Houston, we have a problem, but let's see if it
        # is easily fixable.  Leaving out a space before endobj
        # is apparently an easy mistake to make on generation
        # (Because it won't be noticed unless you are specifically
        # generating an indirect object that doesn't end with any
        # sort of delimiter.)  It is so common that things like
        # okular just handle it.

        if isinstance(obj, PdfObject) and obj.endswith('endobj'):
            source.error('No space or delimiter before endobj')
            obj = PdfObject(obj[:-6])
        else:
            source.error("Expected 'endobj'%s token",
                         isdict and " or 'stream'" or '')
            obj = PdfObject('')

        obj.indirect = key
        self.indirect_objects[key] = obj
        return obj

    def read_all(self):
        deferred = self.deferred_objects
        prev = set()
        while 1:
            new = deferred - prev
            if not new:
                break
            prev |= deferred
            for key in new:
                self.loadindirect(key)

    def decrypt_all(self):
        ''' Read every object.  Objects are decrypted as they are read,
            so this only makes sure that all of them have been.
        '''
        self.read_all()

    def uncompress(self):
        self.read_all()

        uncompress(self.indirect_objects.values())

    def load_stream_objects(self, object_streams):
        ''' Load the members of object streams.

            `object_streams` maps the number of each object stream to a
            list of ``(objnum, index)`` pairs: the members the merged
            cross-reference data says live in that stream.  Only those
            are loaded, so a member left over from an older revision
            never replaces a newer version of the object (#121).
        '''
        for num in sorted(object_streams):
            members = object_streams[num]
            obj = self.findindirect(num, 0)
            if isinstance(obj, PdfIndirect):
                obj = obj.real_value()
            if not isinstance(obj, PdfDict) or obj.Type != PdfName.ObjStm:
                log.warning('Object %d is not an object stream; cannot '
                            'load objects %s from it', num,
                            ', '.join(str(n) for n, _ in members))
                continue

            # The stream was decrypted when it was read; the objects in
            # it are not encrypted themselves.

            # Decompress
            if not uncompress([obj]):
                log.warning('Could not decompress object stream %d', num)
                continue

            objsource = PdfTokens(obj.stream, 0, False)
            next = objsource.next
            header = {}
            try:
                firstoffset = int(obj.First)
                count = int(obj.N) if obj.N is not None else firstoffset
                for _ in range(count):
                    if objsource.floc >= firstoffset:
                        break
                    member = int(next())
                    header.setdefault(member, firstoffset + int(next()))
            except (TypeError, ValueError, StopIteration):
                log.warning('Damaged header in object stream %d; read %d '
                            'of its objects', num, len(header))
            for objnum, index in members:
                offset = header.get(objnum)
                if offset is None:
                    log.warning('Object %d is not in object stream %d',
                                objnum, num)
                    continue
                # Read the object, and call special code if it starts
                # an array or dictionary
                objsource.floc = offset
                try:
                    sobj = next()
                    func = self.special.get(sobj)
                    if func is not None:
                        sobj = func(objsource)
                except (PdfParseError, StopIteration) as exc:
                    log.error('Could not read object %d from object '
                              'stream %d: %s', objnum, num,
                              exc or 'unexpected end of stream')
                    continue

                key = (objnum, 0)
                self.indirect_objects[key] = sobj
                self.deferred_objects.discard(key)

                # Mark the object as indirect
                sobj.indirect = key

    _startxref = re.compile(r'startxref[\x00\t\n\f\r ]*([0-9]+)')

    def findxref(self, fdata):
        ''' Find the cross reference section at the end of a file.

            Uses the last ``startxref`` followed by a number, even one
            glued to it (#211).  Raises PdfParseError when there is none
            or the number is not an offset in the file (#210), so the
            caller can reconstruct the cross-reference data instead.
        '''
        end = len(fdata)
        while 1:
            startloc = fdata.rfind('startxref', 0, end)
            if startloc < 0:
                raise PdfParseError('Did not find "startxref" followed by '
                                    'a table location')
            match = self._startxref.match(fdata, startloc)
            if match is not None:
                break
            end = startloc
        tableloc = match.group(1)
        if len(tableloc) > 20 or int(tableloc) >= startloc:
            raise PdfParseError('startxref location %s is not in the file '
                                '(%d bytes before it)'
                                % (tableloc[:30], startloc))
        return startloc, PdfTokens(fdata, int(tableloc), True, self.verbose)

    def parse_xref_stream(self, source, entries=None, int=int, range=range,
                          enumerate=enumerate, islice=itertools.islice,
                          hexlify=binascii.hexlify):
        ''' Parse (one of) the cross-reference file section(s)

            Each entry goes into `entries`, keyed by object number, as
            an xref stream row: ``(1, offset, gen)`` for an object in the
            file, ``(2, objstm_num, index)`` for one in an object stream,
            or ``(0, 0, gen)`` for a free entry.  Within one section the
            first entry for a number wins.
        '''

        def readint(s, lengths):
            offset = 0
            for length in itertools.cycle(lengths):
                next = offset + length
                yield int(hexlify(s[offset:next]), 16) if length else None
                offset = next

        if entries is None:
            entries = {}
        setdefault = entries.setdefault
        next = source.next
        # check for xref stream object
        objid = source.multiple(3)
        ok = len(objid) == 3
        ok = ok and objid[0].isdigit()
        ok = ok and objid[1] == 'obj'
        ok = ok and objid[2] == '<<'
        if not ok:
            source.exception('Expected xref stream start')
        obj = self.readdict(source)
        if obj.Type != PdfName.XRef:
            source.exception('Expected dict type of /XRef')
        tok = next()
        self.readstream(obj, self.findstream(obj, tok, source), source, True)
        old_strm = obj.stream
        if not uncompress([obj], True):
            source.exception('Could not decompress Xref stream')
        stream = obj.stream
        # Fix for issue #76 -- goofy compressed xref stream
        # that is NOT ACTUALLY COMPRESSED
        stream = stream if stream is not old_strm else convert_store(old_strm)
        num_pairs = obj.Index or PdfArray(['0', obj.Size])
        num_pairs = [int(x) for x in num_pairs]
        num_pairs = zip(num_pairs[0::2], num_pairs[1::2])
        entry_sizes = [int(x) for x in obj.W]
        if len(entry_sizes) != 3:
            source.exception('Invalid entry size')
        get = readint(stream, entry_sizes)
        for objnum, size in num_pairs:
            for cnt in range(size):
                xtype, p1, p2 = islice(get, 3)
                if xtype in (1, None):
                    if p1:
                        setdefault(objnum, (1, p1, p2 or 0))
                elif xtype == 2:
                    setdefault(objnum, (2, p1, p2 or 0))
                elif xtype == 0:
                    setdefault(objnum, (0, 0, p2 or 0))
                objnum += 1

        return obj

    def parse_xref_table(self, source, entries=None, int=int, range=range):
        ''' Parse (one of) the cross-reference file section(s)

            Entries go into `entries` as `parse_xref_stream` describes.
        '''
        if entries is None:
            entries = {}
        setdefault = entries.setdefault
        next = source.next
        # plain xref table
        start = source.floc
        try:
            while 1:
                tok = next()
                if tok == 'trailer':
                    return
                startobj = int(tok)
                for objnum in range(startobj, startobj + int(next())):
                    offset = int(next())
                    generation = int(next())
                    inuse = next()
                    if inuse == 'n':
                        if offset != 0:
                            setdefault(objnum, (1, offset, generation))
                    elif inuse == 'f':
                        setdefault(objnum, (0, 0, generation))
                    else:
                        raise ValueError
        except Exception:
            pass
        try:
            # Table formatted incorrectly.
            # See if we can figure it out anyway.
            end = source.fdata.rindex('trailer', start)
            table = source.fdata[start:end].splitlines()
            for line in table:
                tokens = line.split()
                if len(tokens) == 2:
                    objnum = int(tokens[0])
                elif len(tokens) == 3:
                    offset, generation, inuse = (int(tokens[0]),
                                                 int(tokens[1]), tokens[2])
                    if offset != 0 and inuse == 'n':
                        setdefault(objnum, (1, offset, generation))
                    elif inuse == 'f':
                        setdefault(objnum, (0, 0, generation))
                    objnum += 1
                elif tokens:
                    log.error('Invalid line in xref table: %s' %
                              repr(line))
                    raise ValueError
            log.warning('Badly formatted xref table')
            source.floc = end
            next()
        except Exception:
            source.floc = start
            source.exception('Invalid table format')

    def parsexref(self, source, entries=None):
        ''' Parse (one of) the cross-reference file section(s)

            Returns ``(trailer, is_stream)``, and adds the section's
            entries to `entries` (see `parse_xref_stream`).
        '''
        next = source.next
        try:
            tok = next()
        except StopIteration:
            tok = ''
        if tok.isdigit():
            return self.parse_xref_stream(source, entries), True
        elif tok == 'xref':
            self.parse_xref_table(source, entries)
            tok = next()
            if tok != '<<':
                source.exception('Expected "<<" starting catalog')
            return self.readdict(source), False
        else:
            source.exception('Expected "xref" keyword or xref stream object')

    # Keys that describe one xref section rather than the document; they
    # are never copied into the merged trailer.
    _xref_section_keys = frozenset(PdfName(name) for name in (
        'Prev', 'XRefStm', 'Type', 'W', 'Index', 'Length', 'Filter',
        'DecodeParms', 'F', 'FFilter', 'FDecodeParms', 'DL'))

    def read_xref_sections(self, source, damaged=False):
        ''' Read every cross-reference section, newest first.

            Starts at `source`'s position (the newest section) and
            follows /Prev, and in hybrid-reference files each table's
            /XRefStm stream.  An object number takes its entry from the
            newest section that lists it in use, whether as an offset
            or as an object stream member; free entries are ignored.
            Within a hybrid section the table comes before its /XRefStm
            stream, as PDF 32000-1 7.5.8.4 says.

            Returns ``(offsets, object_streams, trailer)``:
            `offsets` maps ``(objnum, gen)`` to a file offset;
            `object_streams` maps an object stream's number to the
            ``(objnum, index)`` pairs that live in it; `trailer` is a
            PdfDict of the document's trailer entries, each from the
            newest trailer that has it.

            When a section cannot be read, or a /Prev is not an offset in
            the file, or `damaged` is true (no usable startxref), the file
            is also scanned for ``N G obj`` headers and trailers, and what
            the scan finds fills in, at the lowest priority, whatever the
            readable sections do not list (#168, #210).
        '''
        merged = {}
        trailers = []
        seen = set()
        fdata = source.fdata
        while not damaged:
            loc = source.floc
            if loc in seen:
                source.warning('Cross-reference sections loop back to '
                               'offset %d; ignoring the rest', loc)
                break
            seen.add(loc)
            source.obj_offsets = {}
            entries = {}
            try:
                trailer, is_stream = self.parsexref(source, entries)
            except (PdfParseError, StopIteration) as exc:
                log.warning('Cannot read the cross-reference section at '
                            'offset %d (%s); reconstructing it from the '
                            'objects in the file', loc,
                            exc or 'unexpected end of file')
                damaged = True
                break
            prev = trailer.Prev
            if prev is None and not trailers:
                token = source.next_default()
                if token != 'startxref':
                    source.warning('Expected "startxref" '
                                   'at end of xref table')
            if not is_stream and trailer.XRefStm is not None:
                self._read_xref_stm(source, trailer.XRefStm, entries)
            for objnum, entry in iteritems(entries):
                # A free entry does not hide an older revision's object:
                # PDFium and pypdf read it too, and a stray free entry
                # would otherwise lose content (qpdf reads null instead).
                if entry[0]:
                    merged.setdefault(objnum, entry)
            trailers.append(trailer)
            if prev is None:
                break
            try:
                prev = int(prev) if len(prev) <= 20 else -1
            except (TypeError, ValueError):
                prev = -1
            if not 0 < prev < len(fdata):
                log.warning('/Prev %s is not an offset in the file; '
                            'reconstructing the older cross-reference '
                            'sections from the objects in the file',
                            str(trailer.Prev)[:30])
                damaged = True
                break
            source.floc = prev

        scan = None
        if damaged:
            scan = self._scan_objects(source)
            source.obj_offsets = scan.offsets
            for objnum, entry in iteritems(scan.entries):
                merged.setdefault(objnum, entry)
            trailers.extend(scan.trailers)
            if not any(PdfName.Encrypt in t for t in trailers):
                for objnum, entry in self._scan_object_streams(scan):
                    merged.setdefault(objnum, entry)
            else:
                # Encrypted object streams can be scanned only once
                # decryption is set up: see `_add_scanned_object_streams`.
                self.private.encrypted_scan = scan

        offsets = {}
        object_streams = {}
        for objnum, (xtype, field2, field3) in iteritems(merged):
            if xtype == 1:
                offsets[(objnum, field3)] = field2
            elif xtype == 2 and objnum:
                object_streams.setdefault(field2, []).append(
                    (objnum, field3))
        for members in object_streams.values():
            members.sort(key=lambda member: member[1])

        skip = self._xref_section_keys
        result = PdfDict()
        for trailer in reversed(trailers):
            for key, value in dict.items(trailer):
                if key not in skip and value is not None:
                    result[key] = value

        if PdfName.Root not in result:
            if scan is None:
                scan = self._scan_objects(source)
            if scan.catalogs:
                num, gen = scan.catalogs[-1]
                log.warning('No /Root in the trailer; using the catalog, '
                            'object %d %d', num, gen)
                result.Root = self.findindirect(num, gen)
        return offsets, object_streams, result

    # Patterns for scanning a damaged file.  `fdata` is a latin-1 str.
    _ws = r'[\x00\t\n\f\r ]'
    _end_of_token = r'(?=[\x00\t\n\f\r ()<>\[\]{}/%]|$)'
    _objheader = re.compile(r'(?<![0-9])([0-9]{1,10})%s+([0-9]{1,5})%s+obj%s'
                            % (_ws, _ws, _end_of_token))
    _trailer_start = re.compile(r'trailer%s*<<' % _ws)
    _scan_types = re.compile(r'/Type%s*/(Catalog|ObjStm|XRef)%s'
                             % (_ws, _end_of_token))

    class _Scan(object):
        ''' What `_scan_objects` found. '''

    def _scan_objects(self, source):
        ''' Reconstruct cross-reference data by scanning the whole file.

            Returns a `_Scan` with: `entries`, xref rows (see
            `parse_xref_stream`) for each ``N G obj`` header, the last
            one in the file winning for each number; `offsets`, the same
            as ``(num, gen) -> offset``; `trailers`, the dictionaries
            after each ``trailer`` keyword and of each xref stream, newest
            first; `catalogs` and `objstms`, the ``(num, gen)`` of
            objects with that /Type, in file order.
        '''
        fdata = source.fdata
        scan = self._Scan()
        entries = scan.entries = {}
        headers = []
        for match in self._objheader.finditer(fdata):
            num, gen = int(match.group(1)), int(match.group(2))
            entries[num] = (1, match.start(), gen)
            headers.append((match.start(), num, gen))
        scan.offsets = dict(((num, gen), offset)
                            for num, (_, offset, gen) in iteritems(entries))
        log.warning('Reconstructed cross-reference data: found %d objects',
                    len(entries))

        # Which object each /Type belongs to: the nearest header before
        # it, if that is the copy of the object in use.
        positions = [header[0] for header in headers]
        typed = {'Catalog': [], 'ObjStm': [], 'XRef': []}
        for match in self._scan_types.finditer(fdata):
            index = bisect.bisect_right(positions, match.start()) - 1
            if index < 0:
                continue
            offset, num, gen = headers[index]
            found = typed[match.group(1)]
            if entries[num] == (1, offset, gen) and (num, gen) not in found:
                found.append((num, gen))
        scan.catalogs = typed['Catalog']
        scan.objstms = typed['ObjStm']

        # Trailer dictionaries, from trailer keywords and xref streams.
        found = []
        floc = source.floc
        starts = [match.end() for match in
                  self._trailer_start.finditer(fdata)]
        for num, gen in typed['XRef']:
            source.floc = entries[num][1]
            if source.multiple(4)[2:] == ['obj', '<<']:
                starts.append(source.floc)
        for start in starts:
            source.floc = start
            try:
                found.append((start, self.readdict(source)))
            except (PdfParseError, StopIteration):
                continue
        source.floc = floc
        found.sort(key=lambda item: item[0], reverse=True)
        scan.trailers = [trailer for _, trailer in found]
        return scan

    def _scan_object_streams(self, scan):
        ''' Yield ``(objnum, (2, objstm_num, index))`` for each member
            of each object stream the scan found.
        '''
        for num, gen in scan.objstms:
            obj = self.findindirect(num, gen)
            if isinstance(obj, PdfIndirect):
                obj = obj.real_value()
            if not isinstance(obj, PdfDict) or obj.First is None:
                continue
            copy = PdfDict(obj)
            if not uncompress([copy]):
                continue
            objsource = PdfTokens(copy.stream, 0, False)
            try:
                first = int(copy.First)
                index = 0
                while objsource.floc < first:
                    member = int(objsource.next())
                    objsource.next()
                    yield member, (2, num, index)
                    index += 1
            except (ValueError, TypeError, StopIteration):
                log.warning('Cannot read the header of object stream %d',
                            num)

    def _add_scanned_object_streams(self, scan, offsets, object_streams):
        ''' Add the members of the object streams that `scan` found to
            `object_streams`, for object numbers that nothing else
            lists.  For a damaged encrypted file, whose object streams
            can be read only after decryption is set up.
        '''
        known = set(num for num, _ in offsets)
        for members in object_streams.values():
            known.update(num for num, _ in members)
        for objnum, (_, stmnum, index) in self._scan_object_streams(scan):
            if objnum and objnum not in known:
                known.add(objnum)
                object_streams.setdefault(stmnum, []).append(
                    (objnum, index))
        for members in object_streams.values():
            members.sort(key=lambda member: member[1])

    def _read_xref_stm(self, source, location, entries):
        ''' Add the entries of a hybrid file's /XRefStm stream to
            `entries`, without overriding the table's own.
        '''
        floc = source.floc
        stm_entries = {}
        try:
            source.floc = int(location)
            trailer, is_stream = self.parsexref(source, stm_entries)
            if not is_stream:
                source.exception('Expected an xref stream')
        except (PdfParseError, ValueError, StopIteration) as exc:
            source.warning('Ignoring /XRefStm at %s: %s', location,
                           exc or 'unexpected end of file')
            return
        finally:
            source.floc = floc
        for objnum, entry in iteritems(stm_entries):
            entries.setdefault(objnum, entry)

    def readpages(self, node):
        ''' Return the document's pages, in order, from the page tree
            under `node` (the catalog, or a /Pages node).

            A bad node costs only itself, with a warning, never the whole
            tree (as PDFium, pypdf and qpdf read it):
              - a kid that is not a dictionary, such as a reference to a
                missing object, is skipped;
              - a node with /Kids but no /Type is a /Pages node, and a
                kid with neither is a /Page;
              - a kid with some other /Type and no /Kids is skipped;
              - a /Pages node that is its own ancestor is skipped.
            The tree is repaired to match: skipped kids are dropped from
            /Kids and missing /Type entries are added, so a copy written
            from this reader shows the same pages.
        '''
        pagename = PdfName.Page
        pagesname = PdfName.Pages
        catalogname = PdfName.Catalog
        kidsname = PdfName.Kids

        def describe(obj):
            indirect = getattr(obj, 'indirect', None)
            if isinstance(indirect, tuple):
                return 'object %d %d' % indirect
            text = repr(obj)
            return text if len(text) <= 60 else text[:57] + '...'

        result = []
        if not isinstance(node, PdfDict):
            log.error('Invalid page tree: no catalog or /Pages '
                      'dictionary (got %s)', describe(node))
            return result

        # Each stack entry is (node, ids of its /Pages ancestors).
        stack = [(node, frozenset())]
        is_root = True
        while stack:
            node, ancestors = stack.pop()
            nodetype = node.Type
            kids = node[kidsname]

            if is_root and kids is None and (
                    nodetype == catalogname or
                    (nodetype is None and node.Pages is not None)):
                is_root = False
                pages = node[pagesname]
                if not isinstance(pages, PdfDict):
                    log.error('Invalid page tree: catalog /Pages is %s',
                              describe(pages))
                    return result
                stack.append((pages, ancestors))
                continue
            is_root = False

            if nodetype == pagename:
                result.append(node)
                continue

            if kids is None:
                if nodetype is None:
                    log.warning('Page tree node %s has no /Type; reading '
                                'it as a /Page', describe(node))
                    node.Type = pagename
                    result.append(node)
                else:
                    log.warning('Skipping page tree node %s: /Type is %s, '
                                'not /Page or /Pages', describe(node),
                                nodetype)
                continue

            if nodetype != pagesname:
                log.warning('Page tree node %s has /Kids but /Type %s; '
                            'reading it as /Pages', describe(node), nodetype)
                node.Type = pagesname
            if not isinstance(kids, list):
                log.warning('Skipping /Kids of page tree node %s: not an '
                            'array', describe(node))
                continue

            ancestors = ancestors | frozenset([id(node)])
            good = []
            for kid in kids:
                if not isinstance(kid, PdfDict):
                    log.warning('Skipping page tree kid of %s that is not '
                                'a dictionary: %s', describe(node),
                                describe(kid))
                elif id(kid) in ancestors:
                    log.warning('Skipping page tree kid %s of %s: it is '
                                'its own ancestor (a loop)', describe(kid),
                                describe(node))
                elif (kid[kidsname] is None and kid.Type is not None and
                        kid.Type not in (pagename, pagesname)):
                    log.warning('Skipping page tree node %s: /Type is %s, '
                                'not /Page or /Pages', describe(kid),
                                kid.Type)
                else:
                    good.append(kid)
            if len(good) != len(kids):
                node[kidsname] = PdfArray(good)
            stack.extend((kid, ancestors) for kid in reversed(good))
        return result

    def _parse_encrypt_info(self, source, password, trailer):
        ''' Check the password and set up decryption.

            Raises PdfDecryptionError when the password is neither the
            user nor the owner password (an empty password opens files
            that have an empty user password), or when the encryption
            is not supported.  Objects read until now -- the /Encrypt
            dictionary and anything it refers to -- are not encrypted
            and are left as they are; every object read after this is
            decrypted as it is read.
        '''
        handler = crypt.SecurityHandler(trailer.Encrypt, trailer.ID,
                                        password)
        private = self.private
        private.crypt_filters = handler.filters
        private.stream_crypt_filter = handler.stream_filter
        private.string_crypt_filter = handler.string_filter
        private.crypt_handler = handler

    def __init__(self, fname=None, fdata=None, decompress=False,
                 decrypt=False, password='', disable_gc=True, verbose=True):
        self.private.verbose = verbose

        # Runs a lot faster with GC off.
        disable_gc = disable_gc and gc.isenabled()
        if disable_gc:
            gc.disable()

        try:
            if fname is not None:
                assert fdata is None
                # Allow reading preexisting streams like pyPdf
                if hasattr(fname, 'read'):
                    fdata = fname.read()
                else:
                    try:
                        f = open(fname, 'rb')
                        fdata = f.read()
                        f.close()
                    except IOError:
                        raise PdfParseError('Could not read PDF file %s' %
                                            fname)

            assert fdata is not None
            fdata = convert_load(fdata)

            if not fdata.startswith('%PDF-'):
                startloc = fdata.find('%PDF-')
                if startloc >= 0:
                    # Offsets in the file count from the header, as the
                    # file was written before the junk was prepended
                    # (#242).  If they count from the true start, the
                    # xref fails to parse and is reconstructed.
                    log.warning('PDF header not at beginning of file; '
                                'ignoring the %d bytes before it', startloc)
                    fdata = fdata[startloc:]
                else:
                    lines = fdata.lstrip().splitlines()
                    if not lines:
                        raise PdfParseError('Empty PDF file!')
                    raise PdfParseError('Invalid PDF header: %s' %
                                        repr(lines[0]))

            self.private.version = fdata[5:8]

            endloc = fdata.rfind('%EOF')
            if endloc < 0:
                # Truncated, or the writer left it out (#168).
                log.warning('EOF mark not found: %s', repr(fdata[-20:]))
            else:
                endloc += 6
                junk = fdata[endloc:]
                fdata = fdata[:endloc]
                # Trailing NULs are padding, not junk (#136).
                if junk.rstrip('\00').strip():
                    log.warning('Extra data at end of file')

            private = self.private
            private.indirect_objects = {}
            private.deferred_objects = set()
            private.special = {'<<': self.readdict,
                               '[': self.readarray,
                               'endobj': self.empty_obj,
                               }
            for tok in r'\ ( ) < > { } ] >> %'.split():
                self.special[tok] = self.badtoken

            try:
                startloc, source = self.findxref(fdata)
                damaged = False
            except PdfParseError as exc:
                log.warning('%s; reconstructing the cross-reference data '
                            'from the objects in the file', exc)
                source = PdfTokens(fdata, 0, True, self.verbose)
                damaged = True
            private.source = source

            # Merge every xref section, newest first, before loading
            # any object, so that each object comes from the newest
            # revision that lists it (#121, #177, #188, #223, #237, #181).
            offsets, object_streams, trailer = self.read_xref_sections(
                source, damaged)
            source.obj_offsets = offsets

            # Handle document encryption, from the newest trailer (#179),
            # before object streams are read, since they may need
            # decrypting.  An encrypted file is always decrypted, whatever
            # `decrypt` says, as reading it without decrypting gave
            # objects and streams of ciphertext, which a copy wrote out
            # as plaintext: blank pages (#48).  Without the password it
            # raises PdfDecryptionError instead.
            private.crypt_filters = None
            private.crypt_handler = None
            if PdfName.Encrypt in trailer:
                self._parse_encrypt_info(source, password, trailer)
                scan = vars(self).pop('encrypted_scan', None)
                if scan is not None and self.crypt_handler is not None:
                    self._add_scanned_object_streams(scan, offsets,
                                                     object_streams)

            self.load_stream_objects(object_streams)

            if (trailer.Version and
                    float(trailer.Version) > float(self.version)):
                self.private.version = trailer.Version

            if self.crypt_handler is not None:
                # Every object is decrypted as it is read, so a copy is
                # written unencrypted.
                trailer.Encrypt = None
            if decrypt:
                self.decrypt_all()

            self.update(trailer)

            # self.read_all_indirect(source)
            private.pages = self.readpages(self.Root)
            if decompress:
                self.uncompress()

            # For compatibility with pyPdf
            private.numPages = len(self.pages)
        finally:
            if disable_gc:
                gc.enable()

    # For compatibility with pyPdf
    def getPage(self, pagenum):
        return self.pages[pagenum]
