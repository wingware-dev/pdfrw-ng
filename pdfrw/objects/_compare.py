# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

''' Structural equality for PDF objects that may contain cycles (#212).

A page's /Parent leads back through /Kids to the page itself, so the
built-in dict and list comparisons recurse until they hit the
interpreter's limit.  pdf_equal walks both objects with an explicit
stack, and treats a pair of containers it is already comparing as
equal: two objects are equal when no path through them reaches a
difference.
'''

from .pdfindirect import PdfIndirect


def _dict_items(obj, isinstance=isinstance, PdfIndirect=PdfIndirect):
    ''' The entries of a dict with indirect objects resolved and null
        (None) entries left out, which is what a PdfDict stores.
    '''
    items = {}
    get = obj.get       # PdfDict.get resolves (and caches) indirect objects
    for key in list(dict.keys(obj)):
        value = get(key)
        if isinstance(value, PdfIndirect):
            value = value.real_value()
        if value is not None:
            items[key] = value
    return items


def pdf_equal(a, b, isinstance=isinstance, dict=dict, list=list, id=id,
              len=len, getattr=getattr, zip=zip):
    ''' True if a and b hold the same PDF data.  A dict also compares its
        stream, if it has one.  Plain dicts and lists compare like
        PdfDicts and PdfArrays.
    '''
    seen = {}
    stack = [(a, b)]
    pop = stack.pop
    push = stack.append
    while stack:
        x, y = pop()
        if x is y:
            continue
        x_dict = isinstance(x, dict)
        x_list = isinstance(x, list)
        if x_dict or x_list or isinstance(y, (dict, list)):
            if not (x_dict and isinstance(y, dict) or
                    x_list and isinstance(y, list)):
                return False
            key = id(x), id(y)
            if key in seen:
                continue
            # Keep both alive so their ids cannot be reused meanwhile.
            seen[key] = x, y
            if x_dict:
                if getattr(x, 'stream', None) != getattr(y, 'stream', None):
                    return False
                x_items = _dict_items(x)
                y_items = _dict_items(y)
                if len(x_items) != len(y_items):
                    return False
                for name, value in x_items.items():
                    if name not in y_items:
                        return False
                    push((value, y_items[name]))
            else:
                x = list(x)
                y = list(y)
                if len(x) != len(y):
                    return False
                stack.extend(zip(x, y))
        elif not (x == y):
            return False
    return True
