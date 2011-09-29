# -*- coding: utf-8 -*-

from genshi.template import base
from genshi.template import interpolation
from genshi.template import eval as template_eval
from genshi.tree import directives as tree_directives
from genshi.template import markup
from genshi import core
from lxml import etree
import copy
import re
import types
import collections

# TODO: add support for <?python> PI, and ${} syntax
GENSHI_NAMESPACE = "http://genshi.edgewall.org/"
REGEXP_NAMESPACE = "http://exslt.org/regular-expressions"
NAMESPACES = {"py": GENSHI_NAMESPACE, "pytree": "http://genshi.edgewall.org/tree/"}
directives_path = etree.XPath("//*[@py:*]|//py:*", namespaces=NAMESPACES)
pi_path = etree.XPath("//processing-instruction('python')", namespaces=NAMESPACES)
INTERPOLATION_RE = r"%(p)s{([^}]*)}|%(p)s([%(s)s][%(s)s]*)|%(p)s%(p)s" % {"p": '\\' + interpolation.PREFIX, "s": interpolation.NAMESTART, "c": interpolation.NAMECHARS}
interpolation_re = re.compile(INTERPOLATION_RE)
interpolation_path = etree.XPath("//text()[re:test(., '%(r)s')]|//@*[re:test(., '%(r)s')]" % {"r": INTERPOLATION_RE}, namespaces={'re': REGEXP_NAMESPACE})
placeholders_path = etree.XPath("//pytree:placeholder", namespaces=NAMESPACES)

def flatten(l):
    for el in l:
        if isinstance(el, collections.Iterable) and not isinstance(el, (basestring, etree._Element)):
            for sub in flatten(el):
                yield sub
        else:
            yield el

collapse_lines = re.compile('\n{2,}').sub
trim_trailing_space = re.compile('[ \t]+(?=\n)').sub

class ElementList(list):
    def render(self, method=None, encoding=None, out=None, **kwargs):
        # TODO: handle args
        source = [etree.tostring(item) if isinstance(item, etree._Element) else str(item) if item else '' for item in flatten(self)]
        # TODO: work out how to strip out the namespaces
        return collapse_lines('\n', trim_trailing_space('', ''.join(source).replace(' xmlns:py="http://genshi.edgewall.org/"', '')))

    def __str__(self):
        return self.render()

    def __unicode__(self):
        return self.render(encoding=None)

    def __html__(self):
        return self

class BaseElement(etree.ElementBase):
    def eval_expr(self, expr, ctxt, vars):
        """Returns the result of an expression"""
        result = base._eval_expr(expr, ctxt, vars)
        if isinstance(result, (int, float, long)):
            result = unicode(result)
        return result

    def interpolate(self, text, ctxt, vars):
        """Interpolates any special variables in the given text"""
        start = 0
        result = []
        while True:
            m = interpolation_re.search(text, start)
            if m:
                new_start, end = m.span()
                result.append(text[start:new_start])
                expression, varname = m.groups()
                expression = varname if expression is None else expression
                if expression is not None:
                    expr = template_eval.Expression(expression)
                    value = self.eval_expr(expr, ctxt, vars)
                    if isinstance(value, tuple):
                        value = ''.join(value)
                    result.append(value)
                else:
                    # escaped prefix
                    result.append(interpolation.PREFIX)
                start = end
            else:
                result.append(text[start:])
                break
        return ''.join(result)

    def generate(self, template, ctxt, **vars):
        """Generates XML from this element. returns an Element, an iterable set of elements, or None"""
        new_element = parser.makeelement(self.tag, self.attrib, self.nsmap)
        new_element.text, new_element.tail = self.text, self.tail
        for item in self:
            new_item = item.generate(template, ctxt, **vars)
            if isinstance(new_item, types.GeneratorType):
                new_item = list(new_item)
            elif not isinstance(new_item, list):
                new_item = [new_item]
            for sub_item in flatten(new_item):
                if sub_item is None:
                    continue
                elif isinstance(sub_item, etree._Element):
                    new_element.append(sub_item)
                elif isinstance(sub_item, basestring):
                    if len(new_element) == 0:
                        new_element.text = (new_element.text or "") + sub_item
                    else:
                        new_element[-1].tail = (new_element[-1].tail or "") + sub_item
                else:
                    import pdb ; pdb.set_trace()
        return new_element

    def render(self, method=None, encoding=None, out=None, **kwargs):
        # TODO: handle args
        source = etree.tostring(self)
        return source

    def __str__(self):
        return self.render()

    def __unicode__(self):
        return self.render(encoding=None)

    def __html__(self):
        return self

class ContentElement(BaseElement):
    def generate(self, template, ctxt, **vars):
        """Generates XML from this element. returns an Element, an iterable set of elements, or None"""
        new_attrib = {}
        for attr_name, attr_value in self.items():
            if interpolation_re.search(attr_value):
                new_attrib[attr_name] = self.interpolate(attr_value, ctxt, vars)
            else:
                new_attrib[attr_name] = attr_value
        new_element = parser.makeelement(self.tag, new_attrib, self.nsmap)
        if self.text and interpolation_re.search(self.text):
            new_element.text = self.interpolate(self.text, ctxt, vars)
        else:
            new_element.text = self.text
        for item in self:
            new_item = item.generate(template, ctxt, **vars)
            if not isinstance(new_item, (list, types.GeneratorType)):
                new_item = [new_item]
            for sub_item in flatten(new_item):
                if sub_item is None:
                    continue
                elif isinstance(sub_item, etree._Element):
                    new_element.append(sub_item)
                elif isinstance(sub_item, basestring):
                    if len(new_element) == 0:
                        new_element.text = (new_element.text or "") + sub_item
                    else:
                        new_element[-1].tail = (new_element[-1].tail or "") + sub_item
                else:
                    import pdb ; pdb.set_trace()
        if self.tail and interpolation_re.search(self.tail):
            new_element.tail = self.interpolate(self.text, ctxt, vars)
        else:
            new_element.tail = self.tail
        return new_element

class DirectiveElement(ContentElement):
    def __repr__(self):
        return etree.ElementBase.__repr__(self).replace("<Element", "<DirectiveElement", 1)

    def generate(self, template, ctxt, **vars):
        # TODO: cache directives for each node in _init
        directives = []
        # FIXME: Content and Directive Elements
        substream = self
        if self.tag in GenshiElementClassLookup.directive_tags:
            directive_cls = GenshiElementClassLookup.directive_classes[self.tag]
            directive, substream = directive_cls.attach(template, substream, dict(self.attrib.items()), substream.nsmap, ("<string>", 1, 1))
            if directive is not None:
                directives.append(directive)
        directive_attribs = set(self.keys()).intersection(GenshiElementClassLookup.directive_attrs)
        if directive_attribs:
            sorted_attribs = [name for name in GenshiElementClassLookup.directive_names if name in directive_attribs]
            for directive_qname in sorted_attribs:
                directive_cls = GenshiElementClassLookup.directive_classes[directive_qname]
                directive_value = substream.attrib[directive_qname]
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
        for item in flatten(result):
            if item is None:
                continue
            elif item is self:
                final.append(ContentElement.generate(self, template, ctxt, **vars))
            elif isinstance(item, BaseElement):
                final.append(item.generate(template, ctxt, **vars))
            elif isinstance(item, template_eval.Expression):
                final.append(self.eval_expr(item, ctxt, vars))
            elif isinstance(item, basestring):
                if interpolation_re.search(item):
                    final.append(self.interpolate(item, ctxt, vars))
                else:
                    final.append(item)
            else:
                import pdb ; pdb.set_trace()
        if self.tail:
            final.append(self.tail)
        result = final
        return result

class PythonProcessingInstruction(BaseElement, etree._ProcessingInstruction):
    def generate(self, template, ctxt, **vars):
        # TODO: execute the instructions in the context
        suite = template_eval.Suite(self.text)
        base._exec_suite(suite, ctxt, vars)
        return [self.tail]

class GenshiElementClassLookup(etree.PythonElementClassLookup):
    directive_classes = dict([("{%s}%s" % (GENSHI_NAMESPACE, directive_tag), getattr(tree_directives, "%sDirective" % directive_tag.title(), directive_cls)) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives])
    directive_names = ["{%s}%s" % (GENSHI_NAMESPACE, directive_tag) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives]
    directive_tags = set([directive_tag for directive_tag in directive_names if directive_tag[directive_tag.find("}")+1:] not in ("content", "attrs", "strip")])
    directive_attrs = set(directive_names)
    def lookup(self, document, element):
        directives_found = []
        if element.tag in self.directive_tags:
            directives_found.append(self.directive_classes[element.tag])
        elif element.tag in self.directive_attrs:
            raise base.TemplateSyntaxError('The %s directive can not be used as an element' % element.tag[:element.tag.find('}')+1])
        attribs = set(element.keys()).intersection(self.directive_attrs)
        if attribs:
            for directive_name, directive_cls in markup.MarkupTemplate.directives:
                if "{%s}%s" % (GENSHI_NAMESPACE, directive_name) in attribs:
                    directives_found.append(directive_cls)
        if directives_found:
            return DirectiveElement
        for key, value in element.items():
            if interpolation_re.search(value):
                return ContentElement
        if (element.text and interpolation_re.search(element.text)) or (element.tail and interpolation_re.search(element.tail)):
            return ContentElement
        return BaseElement

# TODO: find a cleaner way to do this
for directive_qname, directive_cls in GenshiElementClassLookup.directive_classes.items():
    setattr(directive_cls, "qname", directive_qname)

class GenshiPILookup(etree.CustomElementClassLookup):
    def lookup(self, node_type, document, namespace, name):
        if node_type == "PI" and name == "python":
            return PythonProcessingInstruction

parser = etree.XMLParser()
parser.set_element_class_lookup(GenshiPILookup(GenshiElementClassLookup()))

class TreeTemplate(markup.MarkupTemplate):
    directives = [(directive_tag, getattr(tree_directives, "%sDirective" % directive_tag.title(), directive_cls)) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives]
    def __init__(self, source, filepath=None, filename=None, loader=None,
                 encoding=None, lookup='strict', allow_exec=True):
        self._placeholders = {}
        markup.MarkupTemplate.__init__(self, source, filepath, filename, loader,
                                       encoding, lookup, allow_exec)

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
            result = ElementList(result)
        elif isinstance(result, etree._Element):
            result = ElementList([result])
        return result

