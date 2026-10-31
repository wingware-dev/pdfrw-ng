# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

''' Drop the references a document holds to a page that has left its
    page tree, so that a copy written from it does not carry the page
    along as an orphan object.  PdfReader.remove_page uses this.

    A destination names a page in one of these ways, and each is
    followed:
      - an explicit destination, an array whose first item is the page;
      - a named destination: a string looked up in the /Names /Dests
        name tree of the catalog, or a name looked up in the catalog's
        /Dests dictionary (PDF 1.1), whose value is such an array or a
        dictionary with the array as /D;
      - a /GoTo action, whose /D is either of the above.

    What is cleaned:
      - named destinations to the page are deleted, and empty name tree
        nodes are removed, with /Limits corrected;
      - outline items (bookmarks) that go to the page are unlinked, with
        /Count corrected, unless they have children: then they stay,
        without a destination, to keep their children;
      - link annotations that go to the page are removed from the other
        pages' /Annots, and a /GoTo action to the page is dropped from
        any other annotation;
      - an /OpenAction that goes to the page is dropped.
'''

from .objects import PdfArray, PdfDict, PdfName, PdfObject, PdfString
from .objects.pdfname import BasePdfName

__all__ = ['drop_page_refs']


def drop_page_refs(root, page, pages):
    ''' Drop what in the catalog `root`, and on each page of `pages`
        (the pages still in the tree), refers to `page`, as the module
        docstring describes.
    '''
    _PageRefs(root, page).run(pages)


def _count(value):
    ''' An outline /Count as an int, or None if absent or not a number.
    '''
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _PageRefs(object):

    def __init__(self, root, page):
        self.root = root
        self.page = page
        self.gone_names = set()     # ('string', bytes) or ('name', name)

    # -- what goes to the page ---------------------------------------------

    def explicit_gone(self, dest):
        return (isinstance(dest, list) and len(dest) > 0 and
                dest[0] is self.page)

    def target_gone(self, dest):
        ''' Whether destination `dest`, explicit or named, goes to the
            page.
        '''
        if isinstance(dest, PdfString):
            return ('string', dest.to_bytes()) in self.gone_names
        if isinstance(dest, BasePdfName):
            return ('name', dest) in self.gone_names
        return self.explicit_gone(dest)

    def action_gone(self, action):
        return (isinstance(action, PdfDict) and
                action.S == PdfName.GoTo and self.target_gone(action.D))

    def named_value_gone(self, value):
        if isinstance(value, PdfDict):
            value = value.D
        return self.explicit_gone(value)

    def link_gone(self, obj):
        ''' Whether the outline item or annotation `obj` goes to the page
            through its /Dest or its /A action.
        '''
        if obj.Dest is not None:
            return self.target_gone(obj.Dest)
        return self.action_gone(obj.A)

    @staticmethod
    def unlink_target(obj):
        obj.Dest = None
        obj.A = None

    # -- the cleanup -------------------------------------------------------

    def run(self, pages):
        root = self.root
        if not isinstance(root, PdfDict):
            return
        # Named destinations first: outlines and links may use the names.
        self.clean_dests_dict(root.Dests)
        names = root.Names
        if isinstance(names, PdfDict) and isinstance(names.Dests, PdfDict):
            self.clean_name_tree(names.Dests, frozenset())
        if isinstance(root.Outlines, PdfDict):
            self.clean_outline(root.Outlines)
        for other in pages:
            self.clean_annotations(other)
        action = root.OpenAction
        if self.explicit_gone(action) or self.action_gone(action):
            root.OpenAction = None

    def clean_dests_dict(self, dests):
        if not isinstance(dests, PdfDict):
            return
        for key, value in list(dests.items()):
            if self.named_value_gone(value):
                dests[key] = None
                self.gone_names.add(('name', key))

    def clean_name_tree(self, node, ancestors):
        ''' Drop the entries under name tree `node` that go to the page.
            Return (changed, low, high): whether anything under `node`
            changed, and its least and greatest keys as (bytes, key)
            pairs, None if it has no keys.
        '''
        ancestors = ancestors | frozenset([id(node)])
        changed = False
        keys = []
        names = node.Names
        if isinstance(names, list):
            keep = []
            for index in range(0, len(names) - 1, 2):
                key, value = names[index], names[index + 1]
                if isinstance(key, PdfString):
                    keybytes = key.to_bytes()
                    if self.named_value_gone(value):
                        self.gone_names.add(('string', keybytes))
                        changed = True
                        continue
                    keys.append((keybytes, key))
                keep.extend((key, value))
            if changed:
                if len(names) % 2:
                    keep.append(names[-1])
                names[:] = keep

        kids = node.Kids
        if isinstance(kids, list):
            keep = []
            kids_changed = False
            for kid in kids:
                if isinstance(kid, PdfDict) and id(kid) not in ancestors:
                    kid_changed, low, high = self.clean_name_tree(
                        kid, ancestors)
                    if kid_changed:
                        kids_changed = True
                        if low is None:
                            continue        # Emptied: drop it.
                    if low is not None:
                        keys.extend((low, high))
                keep.append(kid)
            if kids_changed:
                kids[:] = keep
                changed = True

        if not keys:
            return changed, None, None
        low, high = min(keys), max(keys)
        if changed and node.Limits is not None:
            node.Limits = PdfArray([low[1], high[1]])
        return changed, low, high

    def clean_outline(self, top):
        parents = {}        # id(item) -> the node it is listed under
        touched = []        # nodes that lost a child
        seen = set([id(top)])
        stack = [top]
        while stack:
            parent = stack.pop()
            item = parent.First
            while isinstance(item, PdfDict) and id(item) not in seen:
                seen.add(id(item))
                parents[id(item)] = parent
                following = item.Next
                has_kids = isinstance(item.First, PdfDict)
                if self.link_gone(item):
                    self.unlink_target(item)
                    if not has_kids:
                        self.unlink_item(parent, item)
                        touched.append(parent)
                if has_kids:
                    stack.append(item)
                item = following

        # Recount every node above a removed item.
        recount = []
        done = set()
        for node in touched:
            while node is not None and id(node) not in done:
                done.add(id(node))
                recount.append(node)
                node = parents.get(id(node))
        for node in recount:
            self.recount_outline(node, node is top)

    @staticmethod
    def unlink_item(parent, item):
        before, after = item.Prev, item.Next
        if isinstance(before, PdfDict):
            before.Next = after
        else:
            parent.First = after
        if isinstance(after, PdfDict):
            after.Prev = before
        else:
            parent.Last = before

    @staticmethod
    def visible_items(node):
        ''' The number of outline items shown under `node` when it is
            open: its children, and theirs under each open child.
        '''
        total = 0
        seen = set([id(node)])
        stack = [node]
        while stack:
            item = stack.pop().First
            while isinstance(item, PdfDict) and id(item) not in seen:
                seen.add(id(item))
                total += 1
                count = _count(item.Count)
                if count is not None and count > 0:
                    stack.append(item)
                item = item.Next
        return total

    def recount_outline(self, node, is_top):
        if not isinstance(node.First, PdfDict):
            node.Count = None
            return
        total = self.visible_items(node)
        if is_top:
            node.Count = PdfObject(total)
            return
        old = _count(node.Count)
        if old is not None:     # Keep it open or closed as it was.
            node.Count = PdfObject(total if old > 0 else -total)

    def clean_annotations(self, page):
        annots = page.Annots
        if not isinstance(annots, list):
            return
        keep = []
        for annot in annots:
            if isinstance(annot, PdfDict):
                if annot.Subtype == PdfName.Link:
                    if self.link_gone(annot):
                        # Clear it too, in case something else (such as
                        # the structure tree) still lists it.
                        self.unlink_target(annot)
                        continue
                elif self.action_gone(annot.A):
                    annot.A = None
            keep.append(annot)
        if len(keep) != len(annots):
            annots[:] = keep
