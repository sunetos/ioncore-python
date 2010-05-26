#!/usr/bin/env python

"""
@file ion/data/objstore.py
@author Michael Meisinger
@author David Stuebe
@brief storing immutable values (blobs, trees, commit) and storing structured
        mutable objects mapped to graphs of immutable values
"""

import hashlib
try:
    import json
except:
    import simplejson as json
import logging
import pickle
from twisted.internet import defer

from ion.data.dataobject import DataObject
from ion.data.store import IStore, Store
import ion.util.procutils as pu


class ValueRef(object):
    """
    Reference to a unique immutable value. May have a value type.
    """
    VTYPE_VALUE = 'B'
    VTYPE_TREE = 'T'
    VTYPE_COMMIT = 'C'
    VTYPE_REF = 'R'

    def __init__(self, identity, vtype=None):
        self.identity = identity
        self.vtype = vtype

    @classmethod
    def _secure_value_hash(cls, value=None):
        """
        Generate and return a unique, secure content value hash
        @param value  value to generate a secure content hash for
        @retval hash for value
        """
        # Encode the value (this might fail)
        enc_blob = json.dumps(value, sort_keys=True)
        # Create a secure unique hash of value and child references
        hash = hashlib.sha1(enc_blob).hexdigest()
        return hash

    def _value_ref(self):
        """
        Returns a new pure ValueRef instance with the identity of this value
        """
        return ValueRef(self.identity, self.vtype)

class ValueObject(ValueRef):
    """
    An instance of ValueObject represents an immutable value (blob) with an
    identifier, which is generated by secure hashing the value. This instance
    is not the actual value itself, but the "container" for the immutable,
    uniquely identified value. The value is a blob that can be anything.
    Specializations of this class may exist for more specific types of values
    with efficent strategies of storing and additional semantics (such as trees,
    commits, refs, etc.)
    """
    def __init__(self, value, vtype='B'):
        """
        Initializes an immutable value, which consists of an actual value
        structure.
        @param blob the actual value content (must exist and be JSON'able)
        """
        assert value != None
        self.value = value

        hash = self._value_hash()

        # Init the underlying ValueRef; use hash as identity
        ValueRef.__init__(self, hash, vtype)

    def _value_hash(self):
        """
        Generate, set and return secure content value hash for instance's value.
        @retval hash for instance's value
        """
        hash = ValueRef._secure_value_hash(self.value)
        return hash

class TreeValue(ValueObject):
    """
    A specialization of ValueObject for trees of blob and tree values. The
    entries in the tree are identified and referenced by their immutable hash,
    and may have value attributes with them.
    """
    def __init__(self, children=None):
        """
        Initializes an immutable value, which consists 0 or more entries for
        child values and attributes about the child values such as name.
        @param children None or iterable of TreeEntry instances
        """
        if not children:
            children = ()
        elif not getattr(children, '__iter__', False):
            children = (children,)
        assert hasattr(children, '__iter__')

        # @todo: Apply a cycle or uniqueness check similar to python mro
        # Create list of childref strs sort the list by hash
        value = {}
        crvalue = []
        for child in children:
            if isinstance(child, TreeEntry):
                crvalue.append(child.entry)
            else:
                crvalue.append(TreeEntry(child).entry)
        crvalue.sort(key=lambda c: c['ref'])
        value['vtype'] = 'T'
        value['children'] = crvalue

        ValueObject.__init__(self, value, 'T')

class TreeEntry(object):
    def __init__(self, childref, name=None, **kwargs):
        """
        Value object class for an entry in a tree value, identified by ref.
        Attributes are name and additional keyword attributes
        """
        assert childref
        childref = _reftostr(childref)
        if name == None:
            name = childref
        entry = {}
        entry.update(kwargs)
        entry['name'] = name
        entry['ref'] = childref
        self.entry = entry

    @classmethod
    def from_entry(cls, entry):
        """
        Factory method to recreate a TreeEntry from an entry dict
        @param entry  dict with entry
        @retval TreeEntry instance
        """
        assert type(entry) is dict
        entry = entry.copy()
        ref = entry.pop('ref')
        name = entry.pop('name')
        return cls(ref, name, **entry)

class CommitValue(ValueObject):
    """
    A specialization of ValueObject for commit values, which have commit
    attributes (such as timestamp, owner, committer) and one hard reference
    to an immutable root tree value.
    """
    def __init__(self, roottree=None, parents=None, **kwargs):
        """Initializes an immutable value, which consists of an actual value
        structure and 0 or more refs to child values; each value is logically
        based on other values.

        @param parents None, ValueRef or tuple of identities of preceeding values
        @param kwargs arbitrary keyword arguments for commit attributes
        """

        if not parents:
            parents = ()
        elif not getattr(parents, '__iter__', False):
            parents = (parents,)
        assert hasattr(parents, '__iter__')
        roottree = _reftostr(roottree)
        assert not roottree or type(roottree) is str

        # Save parents (immutable tuple of str)
        value = {}
        if kwargs:
            value.update(kwargs)
        value['vtype'] = 'C'
        value['parents'] = [_reftostr(parent) for parent in parents]
        value['roottree'] = roottree

        ValueObject.__init__(self, value, 'C')

class RefValue(ValueObject):
    """
    A specialization of ValueObject for soft links to anything outside of the
    immutable value. The actual value contains the reference. It is
    immutable. The target of the reference may change or vanish, similar to a
    symbolic link in the file system.
    """
    def __init__(self, ref):
        assert ref
        value = {}
        value['type'] = 'REF'
        value['ref'] = ref
        ValueObject.__init__(self, value, 'R')

def _reftostr(ref):
    """
    Convert value ref into a str.
    @param ref  Value with a content hash (as identity)
    """
    if not ref:
        return ref
    elif isinstance(ref, ValueRef):
        return ref.identity
    else:
        return str(ref)

class ValueStore(object):
    """
    Class to store and retrieve immutable values.
    The GIT distributed repository model is a strong design reference.
    Think GIT repository with commits, trees, blobs
    """
    def __init__(self, backend=None, backargs=None):
        """
        @param backend  Class object with a compliant Store or None for memory
        @param backargs arbitrary keyword arguments, for the backend
        """
        self.backend = backend if backend else Store
        self.backargs = backargs if backargs else {}
        assert issubclass(self.backend, IStore)
        assert type(self.backargs) is dict

        # KVS with value ID -> value
        self.objstore = None

    @defer.inlineCallbacks
    def init(self):
        """
        Initializes the ValueStore class
        @retval Deferred
        """
        self.objstore = yield self.backend.create_store(**self.backargs)
        logging.info("ValueStore initialized")

    def _num_values(self):
        try:
            return len(self.objstore.kvs)
        except:
            return 0

    @defer.inlineCallbacks
    def put_value(self, value):
        """
        Puts a value into the value store.
        @param value  value to be put into the store. Can be of different type.
        @retval  ValueRef of a value object
        """
        if isinstance(value, ValueObject):
            oldval = yield self.objstore.get(value.identity)
            if  oldval:
                logging.info("put: value was already in obj store "+str(value.identity))
            # Put value in object store
            yield self.objstore.put(value.identity, pickle.dumps(value))
        else:
            value = ValueObject(value)
            # Put value in object store
            yield self.objstore.put(value.identity, pickle.dumps(value))
        defer.returnValue(value._value_ref())

    @defer.inlineCallbacks
    def get_value(self, valid):
        valid = _reftostr(valid)
        val = yield self.objstore.get(valid)
        if val:
            val = pickle.loads(val)
        defer.returnValue(val)

    @defer.inlineCallbacks
    def exists_value(self, valid):
        val = yield self.get_value(valid)
        defer.returnValue(val != None)

    @defer.inlineCallbacks
    def get_value_type(self, valid):
        val = yield self.get_value(valid)
        defer.returnValue(val.vtype if val else None)

    @defer.inlineCallbacks
    def put_tree(self, childvalues):
        """
        Puts a tree of values into the value store.
        @param value  value to be put into the store. Can be of different type.
                If a list of values, create one value for each element.
        @retval  ValueRef of a tree value
        """
        if not getattr(childvalues, '__iter__', False):
            childvalues = (childvalues,)
        childrefs = []
        for child in childvalues:
            if isinstance(child, ValueObject):
                # This could be a value or a tree. Should not be a commit
                childvo = child
                # @todo Could omit the put here. Shall we?
                yield self.put_value(childvo)
            elif isinstance(child, ValueRef):
                # This is only a ValueRef without a value
                childvo = child
            else:
                # Any other value is put into the store
                # @todo should we encode it first?
                childvo = ValueObject(child)
                yield self.put_value(childvo)

            childrefs.append(childvo.identity)
        treevalue = TreeValue(childrefs)
        yield self.put_value(treevalue)
        defer.returnValue(treevalue._value_ref())

    @defer.inlineCallbacks
    def get_tree_entries(self, valid):
        """
        @retval list of TreeEntry entry dicts (not TreeEntry instances!)
        """
        val = yield self.get_value(valid)
        if not val:
            return
        elif val.vtype != 'T':
            raise RuntimeError("Value %s is not a tree" % (val.identity))
        children = val.value['children']
        defer.returnValue(children)

    @defer.inlineCallbacks
    def get_tree_entriesvalues(self, valid):
        """
        @retval list of TreeEntry instances with value attribute set to value
        """
        cvals = yield self.get_tree_entries(valid)
        if not cvals:
            return
        resvals = []
        for child in cvals:
            cval = yield self.get_value(child['ref'])
            tentry = TreeEntry.from_entry(child)
            tentry.value = cval
            resvals.append(tentry)
        defer.returnValue(resvals)

    @defer.inlineCallbacks
    def put_commit(self, roottreeref, parents=None, **kwargs):
        commit = CommitValue(roottreeref, parents, **kwargs)
        # Put commit value in object store
        cref = yield self.put_value(commit)
        defer.returnValue(cref)

    @defer.inlineCallbacks
    def get_commit(self, valid):
        val = yield self.get_value(valid)
        if not val:
            return
        elif val.vtype != 'C':
            raise RuntimeError("Value %s is not a commit" % (val.identity))
        # @todo Clone commit to avoid tampering
        defer.returnValue(val)

    @defer.inlineCallbacks
    def get_commit_root_entriesvalues(self, valid):
        """
        @retval list of TreeEntry instances with value attribute set to value
        """
        cval = yield self.get_commit(valid)
        if not cval:
            return
        vrvals = yield self.get_tree_entriesvalues(cval.value['roottree'])
        defer.returnValue(vrvals)

    @defer.inlineCallbacks
    def get_ancestors(self, commitref):
        """
        Returns a list of ancestors for the commit value
        @retval list of ancestor commit refs
        """
        resvalues = []
        cval = yield self.get_commit(commitref)
        yield self._get_ancestors(cval, {}, resvalues)
        defer.returnValue(resvalues)

    @defer.inlineCallbacks
    def _get_ancestors(self, cvalue, keys, resvalues):
        """
        Recursively get all ancestors of value, by traversing DAG
        @param cvalue commit value
        @param keys  dict of already found value identities
        @param resvalues list with resulting parent commits
        """
        if not cvalue:
            return
        for anc in cvalue.value['parents']:
            if not anc in keys:
                keys[anc] = 1
                cval = yield self.get_commit(anc)
                assert cval != None, "Ancestor value expected in store"
                resvalues.append(cval)
                self._get_ancestors(cval, keys, resvalues)


class ObjectStore(object):
    """
    Class to store and retrieve structured objects. Updating an object
    will modify the object's state but keep the state history in place.
    Behind the scenes, makes use of a ValueStore to store immutable commits,
    trees and blob values. It is always possible to get value objects.
    @see ValueStore
    """
    def __init__(self, backend=None, backargs=None):
        """
        Initializes object store
        @see ValueStore
        """
        self.vs = ValueStore(backend, backargs)
        # KVS with entity ID -> most recent value ID
        self.entityidx = None

    @defer.inlineCallbacks
    def init(self):
        """
        Initializes the ObjectStore class
        """
        yield self.vs.init()
        self.entityidx = yield self.vs.backend.create_store(**self.vs.backargs)
        logging.info("ObjectStore initialized")

    def _num_entities(self):
        try:
            return len(self.entityidx.kvs)
        except:
            return 0

    def _num_values(self):
        return self.vs._num_values()

    @defer.inlineCallbacks
    def put(self, key, value, parents=None, **kwargs):
        """
        Puts a structured object (called entity) into the object store.
        Equivalent to a git-commit, with a given working tree. Distringuishes
        different types of values.
        @param key the identity of a structured object (mutable entity)
        @param value  a value, which can be a DataObject instance or a
                ValueObject instance or an arbitrary value
        @param kwargs arbitrary keyword arguments for commit attributes
        @retvalue ValueRef of a commit value
        """
        roottreeref = None
        if isinstance(value, DataObject):
            # Got DataObject. Treat it as value, make tree
            vref = yield self.vs.put_value(value.encode())
            roottreeref = yield self.vs.put_tree(vref)
        elif isinstance(value, CommitValue):
            # Got CommitValue. Take the root tree for new commit
            roottreeref = value.value['roottree']
        elif isinstance(value, TreeValue):
            # Got TreeValue. Take as root tree for new commit
            roottreeref = value
        elif isinstance(value, ValueObject):
            # Got ValueObject. Make tree with value
            roottreeref = yield self.vs.put_tree(value)
        else:
            # Got any other value. Make it a value, create a tree
            # Note: of this is an iterator, multiple values will be created
            roottreeref = yield self.vs.put_tree(value)

        key = _reftostr(key)
        # Look into repo and get most recent entity commit. If no parent was
        # specified, set as parent (note some concurrent process might do the same)
        # @todo: is this the intended behavior? what if a client does not care?
        cref = yield self.get_entity(key)
        if cref:
            logging.info("Previous commit exists: "+str(cref))
            if parents == None:
                # No parents were specified but previous exists: set as parent
                parents = [cref]

        # Create commit and put in store
        cref = yield self.vs.put_commit(roottreeref, parents, ts=pu.currenttime_ms(), **kwargs)

        # Update HEAD ref for entity to new commit
        yield self.put_entity(key, cref)

        logging.debug("ObjStore put commit=%s, #entities=%s, #values=%s" % (cref.identity, self._num_entities(), self._num_values()))
        #logging.debug("ObjStore state: EI="+str(self.entityidx.kvs)+", OS="+str(self.objstore.kvs))

        # Return the new commit as ValueRef
        defer.returnValue(cref)

    @defer.inlineCallbacks
    def put_entity(self, key, commitref):
        # Update HEAD ref for entity
        key = _reftostr(key)
        commitref = _reftostr(commitref)
        yield self.entityidx.put(key, commitref)

    @defer.inlineCallbacks
    def get_entity(self, key):
        # Retrieve most recent commit for entity
        key = _reftostr(key)
        cref = yield self.entityidx.get(key)
        defer.returnValue(cref)

    @defer.inlineCallbacks
    def get_commitref(self, key):
        """
        @param key identifier of a mutable entity
        @retval commit ValueRef
        """
        if isinstance(key, ValueRef):
            key = key.identity
        cref = yield self.get_entity(key)
        defer.returnValue(cref)

    @defer.inlineCallbacks
    def get(self, key, commit=None):
        """
        @param key identifier of a mutable entity
        @retval hmmm what?
        @note Added commit kwarg to allow retrieval of a particular commit
        """
        key = _reftostr(key)
        cref = yield self.get_commitref(key)
        if commit:
                cref = commit
                # @Todo make sure commit is an ancestor of the head
        else:
            if not cref:
                return

        cvals = yield self.vs.get_commit_root_entriesvalues(cref)
        dobj = yield self._build_value(cvals, True)
        defer.returnValue(dobj)

    @defer.inlineCallbacks
    def _build_value(self, entries, deep=False):
        """
        Constructs a DataObject from list of tree entries
        @param entries  list of TreeEntry instances with values
        @param deep  boolean flag, indicates whether subtree value should be
                loaded or kept as ValueRef
        @retval a DataObject
        """
        if not entries:
            return
        dobj = DataObject()
        for entry in entries:
            valname = entry.entry['name']
            value = entry.value
            if isinstance(value, TreeValue):
                if deep:
                    tentries = yield self.vs.get_tree_entriesvalues(value)
                    # @todo Should this maybe a container DataObject?
                    vdo = self._build_value(tentries, deep)
                    if vdo:
                        dobj.set_attr(valname, vdo)
                else:
                    # Put only a the tree value object in
                    # @todo Check if this is OK in a DataObject
                    dobj.set_attr(valname, value)
            elif isinstance(value, ValueObject):
                if type(value.value) is dict:
                    # case where a DataObject was encoded
                    vdo = DataObject.from_encoding(value.value)
                    vdo.identity = value.identity
                else:
                    # case where value is a simple value
                    vdo = DataObject()
                    vdo.identity = value.identity
                    vdo.set_attr('value', value.value)

                if len(entries) == 1:
                    defer.returnValue(vdo)
                    return
                dobj.set_attr(valname, vdo)
            else:
                raise RuntimeError('Unknown value type in store: '+repr(value))

        defer.returnValue(dobj)

    @defer.inlineCallbacks
    def getmult(self, keys):
        """
        Return a list of objects
        """
        if not getattr(keys, '__iter__', False):
            keys = (keys,)
        res = []
        for key in keys:
            val = yield self.get(key)
            res.append(val)
        defer.returnValue(res)

    @defer.inlineCallbacks
    def remove(self, key):
        """
        @brief removes the entiti with the given key from the object store
        @param key identifier of a mutable entity
        @retval Deferred
        """
        key = _reftostr(key)
        yield self.entityidx.remove(key)
        defer.returnValue(dobj)

    @defer.inlineCallbacks
    def size(self):
        """
        @brief returns the number of structured objects in the store
        @param key identifier of a mutable entity
        @retval Deferred, for number of objects in store
        """
        defer.succeed(self._num_entities())
