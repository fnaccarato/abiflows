# coding: utf-8
"""Object-Document mapper"""
from __future__ import print_function, division, unicode_literals

import os
import six
import collections

from abipy import abilab
from monty.json import MontyDecoder
from mongoengine import *
from mongoengine.fields import GridFSProxy
from mongoengine.base.datastructures import BaseDict

import logging
logger = logging.getLogger(__name__)


class AbiGridFSProxy(GridFSProxy):

    def abiopen(self):
        """Dump the gridfs data to a temporary file and use `abiopen` to open the file."""
        from tempfile import mkstemp
        _, filepath = mkstemp(suffix='.' + self.abiext, text=self.abiform == "t")

        with open(filepath , "w" + self.abiform) as fh:
            fh.write(self.read())

        return abilab.abiopen(filepath)


class AbiFileField(FileField):
    """
    Extend `FileField`. Use customized version of proxy_class so that
    we can use `abiopen` to construct the AbiPy object from the gridfs content.
    """
    proxy_class = AbiGridFSProxy

    def __init__(self, **kwargs):
        self.abiext = kwargs.pop("abiext")
        self.abiform = kwargs.pop("abiform")

        super(AbiFileField, self).__init__(**kwargs)

    def _monkey_patch_proxy(self, proxy):
        """
        Monkey patch the proxy adding `abiext` and `abiform`.
        so that we know how to open the file in `abiopen`.
        """
        proxy.abiext, proxy.abiform = self.abiext, self.abiform
        return proxy

    def get_proxy_obj(self, **kwargs):
        proxy = super(AbiFileField, self).get_proxy_obj(**kwargs)
        return self._monkey_patch_proxy(proxy)

    def to_python(self, value):
        if value is not None:
            proxy = super(AbiFileField, self).to_python(value)
            return self._monkey_patch_proxy(proxy)


class MongoFiles(EmbeddedDocument):
    """
    Document with the output files produced by the :class:`Task` 
    (references to GridFs files)
    """
    gsr = AbiFileField(abiext="GSR.nc", abiform="b")
    hist = AbiFileField(abiext="HIST", abiform="b")
    phbst = AbiFileField(abiext="PHBST.nc", abiform="b")
    phdos = AbiFileField(abiext="PHDOS.nc", abiform="b")
    sigres = AbiFileField(abiext="SIGRES.nc", abiform="b")
    mdf = AbiFileField(abiext="MDF.nc", abiform="b")

    ddb = AbiFileField(abiext="DDB", abiform="t")
    output_file = AbiFileField(abiext="abo", abiform="t")

    @classmethod
    def from_node(cls, node):
        """Add to GridFs the files produced in the `outdir` of the node."""
        new = cls()

        for key, field in cls._fields.items():
            if not isinstance(field, AbiFileField): continue
            ext, form = field.abiext, field.abiform

            path = node.outdir.has_abiext(ext)
            if path:
                with open(path, "r" + form) as f:
                    # Example: new.gsr.put(f)
                    fname = ext.replace(".nc", "").lower()
                    proxy = getattr(new, fname)
                    proxy.put(f)
        
        # Special treatment of the main output 
        # (the file is not located in node.outdir)
        if hasattr(node, "output_file"):
            #print("in out")
            new.output_file.put(node.output_file.read())

        return new

    def delete(self):
        """Delete gridFs files"""
        for field in self._fields.values():
            if not isinstance(field, AbiFileField): continue
            value = getattr(self, field.name)
            if hasattr(value, "delete"):
                print("Deleting %s" % field.name)
                value.delete()


class MSONDict(BaseDict):
    def to_mgobj(self):
        return MontyDecoder().process_decoded(self)


class MSONField(DictField):

    def __get__(self, instance, owner):
        """Descriptor for retrieving a value from a field in a document.
        """
        value = super(MSONField, self).__get__(instance, owner)
        if isinstance(value, BaseDict):
            value.__class__ = MSONDict
        
        print("value:", type(value))
        return value

    #def to_python(self, value):
    #    #print("to value:", type(value))
    #    if isinstance(value, collections.Mapping) and "@module" in value:
    #        value = MontyDecoder().process_decoded(value)
    #    else:
    #        value = super(MSONField, self).to_python(value)

    #    print("to value:", type(value))
    #    return value

    #def to_mongo(self, value):
    #    #print(value.as_dict())
    #    return value.as_dict()


class MongoTaskResults(EmbeddedDocument):
    """Document with the most important results produced by the :class:`Task`"""

    #meta = {'allow_inheritance': True}

    #: The initial input structure for the calculation in the pymatgen json representation
    #initial_structure = DictField(required=True)
    initial_structure = MSONField(required=True)

    #: The final relaxed structure in a dict format. 
    final_structure = DictField(required=True)

    @classmethod
    def from_task(cls, task):
        # TODO Different Documents depending on task.__class__ or duck typing?
        #initial_structure = MSONField().to_mongo(task.input.structure.as_dict())
        initial_structure = task.input.structure.as_dict()
        #print(type(initial_structure))
        final_structure = initial_structure

        if hasattr(task, "open_gsr"):
            with task.open_gsr() as gsr:
                final_structure = gsr.structure.as_dict()

        new = cls(
            initial_structure=initial_structure,
            final_structure=final_structure,
        )
        return new


class MongoNode(Document):

    meta = {'allow_inheritance': True}
    #meta = {'meta': True}

    node_id = LongField(required=True)
    node_class = StringField(required=True)
    status = StringField(required=True)
    workdir = StringField(required=True)

    #date_modified = DateTimeField(default=datetime.datetime.now)

    @classmethod
    def from_node(cls, node):
        return cls(
            node_class=node.__class__.__name__,
            node_id=node.node_id,
            status=str(node.status),
            workdir=node.workdir,
        )


class MongoEmbeddedNode(EmbeddedDocument):

    meta = {'allow_inheritance': True}
    #meta = {'meta': True}

    node_id = LongField(required=True)

    node_class = StringField(required=True)

    status = StringField(required=True)

    workdir = StringField(required=True)

    #date_modified = DateTimeField(default=datetime.datetime.now)

    @classmethod
    def from_node(cls, node):
        return cls(
            node_class=node.__class__.__name__,
            node_id=node.node_id,
            status=str(node.status),
            workdir=node.workdir,
        )


class MongoTask(MongoEmbeddedNode):
    """Document associated to a :class:`Task`"""

    input = DictField(required=True)
    input_str = StringField(required=True)

    # Abinit events.
    report = DictField(required=True)
    num_warnings = IntField(required=True, help_text="Number of warnings")
    num_errors = IntField(required=True, help_text="Number of errors")
    num_comments =  IntField(required=True, help_text="Number of comments")

    #: Total CPU time taken.
    #cpu_time = FloatField(required=True)
    #: Total wall time taken.
    #wall_time = FloatField(required=True)

    results = EmbeddedDocumentField(MongoTaskResults)

    outfiles = EmbeddedDocumentField(MongoFiles)

    #@property
    #def num_warnings(self):
    #    """Number of warnings reported."""
    #    return self.input.num_warnings

    #@property
    #def num_errors(self):
    #    """Number of errors reported."""
    #    return self.input.num_error

    #@property
    #def num_comments(self):
    #    """Number of comments reported."""
    #    return len(self.comments)

    #@property
    #def is_paw(self):
    #    print("in is paw")
    #    return True

    @classmethod
    def from_task(cls, task):
        """Build the document from a :class:`Task` instance."""
        new = cls.from_node(task)

        new.input = task.input.as_dict()
        new.input_str = str(task.input)

        # TODO: Handle None!
        report = task.get_event_report()
        for a in ("num_errors", "num_comments", "num_warnings"):
            setattr(new, a, getattr(report, a))
        new.report = report.as_dict()

        new.results = MongoTaskResults.from_task(task)
        new.outfiles = MongoFiles.from_node(task)

        return new


class MongoWork(MongoEmbeddedNode):
    """Document associated to a :class:`Work`"""
    
    #: List of tasks.
    tasks = ListField(EmbeddedDocumentField(MongoTask), required=True)

    #: Output files produced by the work.
    outfiles = EmbeddedDocumentField(MongoFiles)

    @classmethod
    def from_work(cls, work):
        """Build and return the document from a :class:`Work` instance."""
        new = cls.from_node(work)
        new.tasks = [MongoTask.from_task(task) for task in work]
        new.outfiles = MongoFiles.from_node(work)
        return new

    def __getitem__(self, name):
        try:
            # Dictionary-style field of super
            return super(MongoWork, self).__getitem__(name)
        except KeyError:
            # Assume int or slice
            try:
                return self.tasks[name]
            except IndexError:
                raise


class MongoFlow(MongoNode):
    """
    Document associated to a :class:`Flow`

    Assumptions:
        All the tasks must have the same list of pseudos, 
        same chemical formula.
    """

    #: List of works
    works = ListField(EmbeddedDocumentField(MongoWork), required=True)

    #: Output files produced by the flow.
    outfiles = EmbeddedDocumentField(MongoFiles)

    meta = {
        "collection": "flowdata",
        #"indexes": ["status", "priority", "created"],
    }

    @classmethod
    def from_flow(cls, flow):
        """Build and return the document from a :class:`Flow` instance."""
        new = cls.from_node(flow)
        new.works = [MongoWork.from_work(work) for work in flow]
        new.outfiles = MongoFiles.from_node(flow)
        return new

    def __getitem__(self, name):
        try:
            # Dictionary-style field of super
            return super(MongoFlow, self).__getitem__(name)
        except KeyError:
            # Assume int or slice
            try:
                return self.works[name]
            except IndexError:
                raise

    def pickle_load(self):
        """
        Load the pickle file from the working directory of the flow.

        Return:
            :class:`Flow` instance.
        """
        flow = abilab.Flow.pickle_load(self.workdir)
        #flow.set_mongo_id(self.id)
        return flow 

    def delete(self):
        # Remove GridFs files.
        for work in self.works:
            work.outfiles.delete()
            #work.delete()
            for task in work:
                #task.delete()
                task.outfiles.delete()

        self.delete()

    @queryset_manager
    def completed(doc_cls, queryset):
        return queryset.filter(status="Completed")

    #@queryset_manager
    #def running(doc_cls, queryset):
    #    return queryset.filter(status__in=["AbiCritical", "QCritical", "Error",])

    #@queryset_manager
    #def paw_flows(doc_cls, queryset):
    #    return queryset.filter(is_paw=True)

    #@queryset_manager
    #def nc_flows(doc_cls, queryset):
    #    return queryset.filter(is_nc=True)

