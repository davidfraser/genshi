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

class DirectiveElement(interpolation.ContentElement):
    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(DirectiveElement, self)._init()
        self.directive_classes = []
        if self.tag in GenshiElementClassLookup.directive_tags:
            directive_cls = GenshiElementClassLookup.directive_classes[self.tag]
            directive_value = dict(self.attrib.items())
            self.directive_classes.append((directive_cls, directive_value))
        directive_attribs = set(self.keys()).intersection(GenshiElementClassLookup.directive_attrs)
        if directive_attribs:
            self.dynamic_attrs = [(attr_name, attr_value) for (attr_name, attr_value) in self.dynamic_attrs if attr_name not in directive_attribs]
            sorted_attribs = sorted(directive_attribs, key=GenshiElementClassLookup.directive_names.index)
            for directive_qname in sorted_attribs:
                self.static_attrs.pop(directive_qname, None)
                directive_cls = GenshiElementClassLookup.directive_classes[directive_qname]
                directive_value = self.attrib[directive_qname]
                self.directive_classes.append((directive_cls, directive_value))

    def __repr__(self):
        return etree.ElementBase.__repr__(self).replace("<Element", "<DirectiveElement", 1)

    def generate(self, template, ctxt, **vars):
        # FIXME: Content and Directive Elements
        substream = self
        directives = []
        for directive_cls, directive_value in self.directive_classes:
            directive, substream = directive_cls.attach(template, substream, directive_value, substream.nsmap, ("<string>", 1, 1))
            if directive is None:
                break
            else:
                directives.append(directive)
        if directives:
            result = tree_directives._apply_directives(substream, directives, ctxt, vars)
        else:
            result = substream
        if result is None:
            # In this case, we don't return the tail
            return result
        final = []
        if not isinstance(result, (types.GeneratorType, list)):
            result = [result]
        for item in tree_base.flatten_generate(result, template, ctxt, vars):
            if item is None:
                continue
            elif isinstance(item, tree_base.BaseElement):
                final.append(item.generate(template, ctxt, **vars))
            elif isinstance(item, template_eval.Expression):
                final.append(self.eval_expr(item, ctxt, vars))
            elif isinstance(item, interpolation.InterpolationString):
                final.append(item.interpolate(template, ctxt, vars))
            elif isinstance(item, basestring):
                # TODO: check if we ever get this rather than an InterpolationString
                if tree_base.interpolation_re.search(item):
                    final.append(self.interpolate(item, ctxt, vars))
                else:
                    final.append(item)
            else:
                raise ValueError("Unexpected type %s returned from _apply_directives: %r" % (type(item), item))
        if self.tail_dynamic:
            final.append(self.tail_dynamic.interpolate(template, ctxt, vars))
        elif self.tail:
            final.append(self.tail)
        result = final
        return result

tree_base.LOOKUP_CLASSES["DirectiveElement"] = DirectiveElement

class PythonProcessingInstruction(tree_base.BaseElement, etree._ProcessingInstruction):
    def generate(self, template, ctxt, **vars):
        # TODO: execute the instructions in the context
        suite = template_eval.Suite(self.text)
        base._exec_suite(suite, ctxt, vars)
        return [self.tail]

class GenshiElementClassLookup(etree.PythonElementClassLookup):
    directive_classes = dict([("{%s}%s" % (tree_base.GENSHI_NAMESPACE, directive_tag), getattr(tree_directives, "%sDirective" % directive_tag.title(), directive_cls)) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives])
    directive_names = ["{%s}%s" % (tree_base.GENSHI_NAMESPACE, directive_tag) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives]
    directive_tags = set([directive_tag for directive_tag in directive_names if directive_tag[directive_tag.find("}")+1:] not in ("content", "attrs", "strip")])
    directive_attrs = set(directive_names)
    def lookup(self, document, element):
        if tree_base.LOOKUP_CLASS_TAG in element.attrib:
            class_name = element.attrib[tree_base.LOOKUP_CLASS_TAG]
            return tree_base.LOOKUP_CLASSES[class_name]
        directives_found = []
        if element.tag in self.directive_tags:
            directives_found.append(self.directive_classes[element.tag])
        elif element.tag in self.directive_attrs:
            raise base.TemplateSyntaxError('The %s directive can not be used as an element' % element.tag[:element.tag.find('}')+1])
        attribs = set(element.keys()).intersection(self.directive_attrs)
        if attribs:
            for directive_name, directive_cls in markup.MarkupTemplate.directives:
                if "{%s}%s" % (tree_base.GENSHI_NAMESPACE, directive_name) in attribs:
                    directives_found.append(directive_cls)
        if directives_found:
            return DirectiveElement
        for key, value in element.items():
            if tree_base.interpolation_re.search(value):
                return interpolation.ContentElement
        if (element.text and tree_base.interpolation_re.search(element.text)) or (element.tail and tree_base.interpolation_re.search(element.tail)):
            return interpolation.ContentElement
        return tree_base.BaseElement

# TODO: find a cleaner way to do this
for directive_qname, directive_cls in GenshiElementClassLookup.directive_classes.items():
    setattr(directive_cls, "qname", directive_qname)

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

