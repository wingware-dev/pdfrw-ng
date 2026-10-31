# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Regression tests for pdfrw.objects: PdfDict, PdfArray, PdfName and
PdfString."""

import copy
import io
import pickle

import pytest

from pdfrw import PdfReader, PdfWriter, PdfDict, IndirectPdfDict, \
    PdfArray, PdfName, PdfObject, PdfString
from pdfrw.errors import PdfParseError
from pdfrw.objects import PdfIndirect

from .pdfgen import make_pdf, page_label
from .validate import assert_valid


# -- #135: update() and setdefault() check their keys ----------------------

def test_update_rejects_str_key():
    d = PdfDict()
    with pytest.raises(PdfParseError):
        d.update({'Title': PdfString.encode('x')})
    assert dict(d) == {}


def test_update_rejects_str_key_in_pairs():
    with pytest.raises(PdfParseError):
        PdfDict().update([('/Title', 1)])


def test_setdefault_rejects_str_key():
    d = PdfDict()
    with pytest.raises(PdfParseError):
        d.setdefault('/Title', 1)
    assert dict(d) == {}


def test_update_accepts_names_mappings_pairs_and_keywords():
    d = PdfDict()
    d.update({PdfName.A: 1}, B=2)
    d.update([(PdfName.C, 3)])
    d.update(PdfDict(D=4))
    assert d == {PdfName.A: 1, PdfName.B: 2, PdfName.C: 3, PdfName.D: 4}
    assert all(type(k) is type(PdfName.A) for k in dict.keys(d))


def test_update_keywords_match_constructor():
    d = PdfDict()
    d.update(indirect=True, Type=PdfName.Page)
    assert d.indirect is True
    assert d == {PdfName.Type: PdfName.Page}


def test_update_with_none_deletes():
    d = PdfDict(A=1, B=2)
    d.update({PdfName.A: None})
    assert d == {PdfName.B: 2}


def test_update_keeps_values_unresolved():
    ref = PdfIndirect((5, 0))
    ref._loader = lambda ref: pytest.fail('resolved too early')
    src = PdfDict()
    dict.__setitem__(src, PdfName.A, ref)
    d = PdfDict()
    d.update(src)
    assert dict.__getitem__(d, PdfName.A) is ref
    assert dict.__getitem__(PdfDict(src), PdfName.A) is ref


def test_setdefault():
    d = PdfDict(A=1)
    assert d.setdefault(PdfName.A, 2) == 1
    assert d.setdefault(PdfName.B, 3) == 3
    assert d.setdefault(PdfName.C) is None
    assert d == {PdfName.A: 1, PdfName.B: 3}


def test_setdefault_resolves_indirect():
    ref = PdfIndirect((5, 0))
    ref.value = PdfObject('42')
    d = PdfDict()
    dict.__setitem__(d, PdfName.A, ref)
    assert d.setdefault(PdfName.A, 1) == '42'


# -- pop() and popitem() behave like dict's ---------------------------------

def indirect(value):
    ref = PdfIndirect((5, 0))
    ref.value = value
    return ref


def test_pop():
    d = PdfDict(A=PdfObject('1'))
    assert d.pop(PdfName.A) == '1'
    assert dict(d) == {}
    with pytest.raises(KeyError):
        d.pop(PdfName.A)
    assert d.pop(PdfName.A, 'default') == 'default'
    assert d.pop(PdfName.A, None) is None
    with pytest.raises(TypeError):
        d.pop(PdfName.A, 1, 2)


def test_pop_resolves_indirect():
    d = PdfDict()
    dict.__setitem__(d, PdfName.A, indirect(PdfObject('42')))
    assert d.pop(PdfName.A) == '42'
    assert dict(d) == {}


def test_pop_null_indirect_counts_as_missing():
    d = PdfDict()
    dict.__setitem__(d, PdfName.A, indirect(None))
    assert d.pop(PdfName.A, 'default') == 'default'
    assert dict(d) == {}
    dict.__setitem__(d, PdfName.A, indirect(None))
    with pytest.raises(KeyError):
        d.pop(PdfName.A)


def test_popitem():
    d = PdfDict()
    dict.__setitem__(d, PdfName.A, indirect(PdfObject('42')))
    assert d.popitem() == (PdfName.A, '42')
    with pytest.raises(KeyError):
        d.popitem()


def test_popitem_skips_null_indirect():
    d = PdfDict(B=PdfObject('2'))
    dict.__setitem__(d, PdfName.A, indirect(None))   # popped first (LIFO)
    assert d.popitem() == (PdfName.B, '2')
    assert dict(d) == {}


# -- #141: dunder attributes, copy and pickle ------------------------------

def test_dunder_attributes_are_not_pdf_keys():
    d = PdfDict()
    assert not hasattr(d, '__setstate__')
    assert not hasattr(d, '__deepcopy__')
    assert not hasattr(d.inheritable, '__deepcopy__')
    with pytest.raises(AttributeError):
        PdfName.__deepcopy__
    # Ordinary names still read the dictionary.
    assert d.Missing is None
    assert PdfName.Foo == '/Foo'


def sample_dict():
    name = PdfName('A B')            # needs an encoded form
    return IndirectPdfDict(
        Type=PdfName.XObject,
        Kids=PdfArray([PdfDict(N=PdfObject('1')), name]),
        Title=PdfString.encode('t'),
        stream='q Q',
    )


def check_copy(orig, other):
    assert other is not orig
    assert type(other) is type(orig)
    assert other == orig
    assert other.indirect is True
    assert other.stream == 'q Q'
    assert other.Length == orig.Length
    name = other.Kids[1]
    assert type(name) is type(orig.Kids[1])
    assert name == '/A B'
    assert name.encoded == '/A#20B'
    assert type(other.Kids) is PdfArray
    assert type(other.Kids[0]) is PdfDict


def test_deepcopy_pdfdict():
    orig = sample_dict()
    other = copy.deepcopy(orig)
    check_copy(orig, other)
    assert other.Kids is not orig.Kids


def test_copy_pdfdict():
    orig = sample_dict()
    other = copy.copy(orig)
    check_copy(orig, other)
    assert other.Kids is orig.Kids


@pytest.mark.parametrize('protocol', range(2, pickle.HIGHEST_PROTOCOL + 1))
def test_pickle_pdfdict(protocol):
    orig = sample_dict()
    check_copy(orig, pickle.loads(pickle.dumps(orig, protocol)))


def test_deepcopy_page_from_reader_writes_valid_pdf():
    reader = PdfReader(fdata=make_pdf(2))
    pages = [copy.deepcopy(p) for p in reader.pages]
    out = io.BytesIO()
    PdfWriter(out).addpages(pages).write()
    assert_valid(out.getvalue(), texts=[page_label(0), page_label(1)])


def test_pickle_page_from_reader_writes_valid_pdf():
    reader = PdfReader(fdata=make_pdf(2))
    pages = pickle.loads(pickle.dumps(list(reader.pages)))
    assert pages[0] == reader.pages[0]
    assert pages[0].indirect
    assert not hasattr(pages[0].indirect, '_loader')
    out = io.BytesIO()
    PdfWriter(out).addpages(pages).write()
    assert_valid(out.getvalue(), texts=[page_label(0), page_label(1)])


def test_pickle_pdfarray():
    arr = PdfArray([PdfObject('1'), PdfArray([PdfName.X])])
    arr.indirect = True
    other = pickle.loads(pickle.dumps(arr))
    assert other == arr and type(other[1]) is PdfArray
    assert other.indirect is True


# -- #212: equality must not recurse forever -------------------------------

def test_pages_of_same_file_compare_without_recursion():
    data = make_pdf(3)
    a = PdfReader(fdata=data).pages
    b = PdfReader(fdata=data).pages
    assert a[0] == b[0]
    assert not (a[0] != b[0])
    assert a[0] != a[1]          # different content streams
    assert a[0] == a[0]


def test_cyclic_structures_compare():
    a = PdfDict(Name=PdfName.A)
    a.Self = a
    b = PdfDict(Name=PdfName.A)
    b.Self = b
    assert a == b
    b.Name = PdfName.B
    assert a != b

    x = PdfArray([PdfObject('1')])
    x.append(x)
    y = PdfArray([PdfObject('1')])
    y.append(y)
    assert x == y


def test_deep_chain_compares():
    def chain(n):
        head = node = PdfDict()
        for _ in range(n):
            node.Next = PdfDict()
            node = node.Next
        return head
    assert chain(50000) == chain(50000)
    assert chain(50000) != chain(50001)


def test_equality_with_plain_containers():
    assert PdfDict(A=PdfObject('1')) == {PdfName.A: '1'}
    assert {PdfName.A: '1'} == PdfDict(A=PdfObject('1'))
    assert PdfDict(A=1) != {PdfName.A: 2}
    assert PdfDict() != []
    assert PdfDict() != 'x'
    assert PdfArray([1, [2]]) == [1, [2]]
    assert [1, [2]] == PdfArray([1, [2]])
    assert PdfArray([1]) != [2]
    assert PdfArray([1]) != (1,)


def test_streams_take_part_in_equality():
    assert PdfDict(stream='a') == PdfDict(stream='a')
    assert PdfDict(stream='a') != PdfDict(stream='b')
    assert PdfDict(stream='a') != PdfDict(Length=PdfObject('1'))


def test_pdfdict_and_pdfarray_stay_unhashable():
    with pytest.raises(TypeError):
        hash(PdfDict())
    with pytest.raises(TypeError):
        hash(PdfArray())


# -- PdfString.decode_hex: odd-length strings -------------------------------

@pytest.mark.parametrize('source, expected', [
    ('<414>', b'A@'),
    ('<4>', b'@'),
    ('<41 4>', b'A@'),
    ('<4142>', b'AB'),
    ('<>', b''),
])
def test_decode_hex_odd_length(source, expected):
    assert PdfString(source).to_bytes() == expected


# -- #147: CR in literal strings --------------------------------------------

@pytest.mark.parametrize('raw', [b'a\rb', b'a\r\nb', b'\r', b'(\r)\\'])
def test_literal_cr_roundtrip(raw):
    s = PdfString.from_bytes(raw, bytes_encoding='literal')
    assert '\r' not in s
    assert s.to_bytes() == raw
