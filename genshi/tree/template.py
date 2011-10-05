# -*- coding: utf-8 -*-

from genshi.template import base
from genshi.template import eval as template_eval
from genshi.tree import base as tree_base
from genshi.tree import directives as tree_directives
from genshi.tree import interpolation
from genshi.template import markup
from genshi import core
from lxml import etree
import re
import types
import collections

class PythonProcessingInstruction(tree_base.BaseElement, etree._ProcessingInstruction):
    def generate(self, template, ctxt, **vars):
        # TODO: execute the instructions in the context
        suite = template_eval.Suite(self.text)
        base._exec_suite(suite, ctxt, vars)
        return [self.tail]

class GenshiElementClassLookup(etree.PythonElementClassLookup):
    def lookup(self, document, element):
        if tree_base.LOOKUP_CLASS_TAG in element.attrib:
            class_name = element.attrib[tree_base.LOOKUP_CLASS_TAG]
            return tree_base.LOOKUP_CLASSES[class_name]
        directives_found = []
        if element.tag in tree_directives.DirectiveElement.directive_tags:
            directives_found.append(tree_directives.DirectiveElement.directive_class_lookup[element.tag])
        elif element.tag in tree_directives.DirectiveElement.directive_attrs:
            raise base.TemplateSyntaxError('The %s directive can not be used as an element' % element.tag[:element.tag.find('}')+1])
        attribs = set(element.keys()).intersection(tree_directives.DirectiveElement.directive_attrs)
        if attribs:
            for directive_name in tree_directives.DirectiveElement.directive_names:
                if directive_name in attribs:
                    directives_found.append(tree_directives.DirectiveElement.directive_class_lookup[directive_name])
        if directives_found:
            return tree_directives.DirectiveElement
        for key, value in element.items():
            if tree_base.interpolation_re.search(value):
                return interpolation.ContentElement
        if (element.text and tree_base.interpolation_re.search(element.text)) or (element.tail and tree_base.interpolation_re.search(element.tail)):
            return interpolation.ContentElement
        return tree_base.BaseElement

class GenshiPILookup(etree.CustomElementClassLookup):
    def lookup(self, node_type, document, namespace, name):
        if node_type == "PI" and name == "python":
            return PythonProcessingInstruction
        if node_type == "comment":
            return etree._Comment

parser = etree.XMLParser()
parser.set_element_class_lookup(GenshiPILookup(GenshiElementClassLookup()))

class TreeTemplate(markup.MarkupTemplate):
    directives = [(directive_tag, getattr(tree_directives, "%sDirective" % directive_tag.title(), directive_cls)) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives]
    def __init__(self, source, filepath=None, filename=None, loader=None,
                 encoding=None, lookup='strict', allow_exec=True):
        self._placeholders = {}
        markup.MarkupTemplate.__init__(self, source, filepath, filename, loader,
                                       encoding, lookup, allow_exec)
        self.node_cache = list(self._stream.getroot().iter())

    def make_placeholder(self, target):
        ph_id = len(self._placeholders) + 1
        ph = etree.SubElement(target.getparent(), "{http://genshi.edgewall.org/tree/}placeholder", id=str(ph_id), nsmap=NAMESPACES)
        self._placeholders[ph_id] = target
        return ph

    def _parse(self, source, encoding):
        source_tree = etree.parse(source, parser)
        return source_tree

    def add_directives(self, namespace, factory):
        pass

    def generate(self, *args, **kwargs):
        """Apply the template to the given context data.
        
        Any keyword arguments are made available to the template as context
        data.
        
        Only one positional argument is accepted: if it is provided, it must be
        an instance of the `Context` class, and keyword arguments are ignored.
        This calling style is used for internal processing.
        
        :return: a markup event stream representing the result of applying
                 the template to the context data.
        """
        vars = {}
        if args:
            assert len(args) == 1
            ctxt = args[0]
            if ctxt is None:
                ctxt = base.Context(**kwargs)
            else:
                vars = kwargs
            assert isinstance(ctxt, base.Context)
        else:
            ctxt = base.Context(**kwargs)
        root = self._stream.getroot()
        result = root.generate(self, ctxt)
        if isinstance(result, list):
            result = tree_base.ElementList(result)
        elif isinstance(result, etree._Element):
            result = tree_base.ElementList([result])
        return result

