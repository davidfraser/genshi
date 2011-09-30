# -*- coding: utf-8 -*-

from genshi.template import base
from genshi.template import interpolation
from genshi.template import eval as template_eval
from genshi.tree import directives as tree_directives
from genshi.template import markup
from genshi import core
from lxml import etree
import re
import types
import collections
import weakref

# TODO: add support for <?python> PI, and ${} syntax
GENSHI_NAMESPACE = "http://genshi.edgewall.org/"
LOOKUP_CLASS_TAG = "{%s}classname" % GENSHI_NAMESPACE
LOOKUP_CLASSES = {}
REGEXP_NAMESPACE = "http://exslt.org/regular-expressions"
NAMESPACES = {"py": GENSHI_NAMESPACE, "pytree": "http://genshi.edgewall.org/tree/"}
directives_path = etree.XPath("//*[@py:*]|//py:*", namespaces=NAMESPACES)
pi_path = etree.XPath("//processing-instruction('python')", namespaces=NAMESPACES)
INTERPOLATION_RE = r"%(p)s{([^}]*)}|%(p)s([%(s)s][%(s)s]*)|%(p)s%(p)s" % {"p": '\\' + interpolation.PREFIX, "s": interpolation.NAMESTART, "c": interpolation.NAMECHARS}
interpolation_re = re.compile(INTERPOLATION_RE)
interpolation_path = etree.XPath("//text()[re:test(., '%(r)s')]|//@*[re:test(., '%(r)s')]" % {"r": INTERPOLATION_RE}, namespaces={'re': REGEXP_NAMESPACE})

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
        source = []
        for item in flatten(self):
            if isinstance(item, etree._Element):
                etree.cleanup_namespaces(item)
                source.append(etree.tostring(item))
            elif item:
                source.append(str(item))
        # TODO: work out how to strip out the namespaces
        return collapse_lines('\n', trim_trailing_space('', ''.join(source)))

    def __str__(self):
        return self.render()

    def __unicode__(self):
        return self.render(encoding=None)

    def __html__(self):
        return self

class BaseElement(etree.ElementBase):
    def _init(self):
        """Instantiates this element - can be called multiple times for the same libxml C object if it gets proxied to a new Python instance"""
        self.attrib.pop(LOOKUP_CLASS_TAG, None)
        self.lookup_attrib = [(LOOKUP_CLASS_TAG, type(self).__name__)]

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
        attrib = dict(self.attrib.items() + self.lookup_attrib)
        new_element = parser.makeelement(self.tag, attrib, self.nsmap)
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
                    raise ValueError("Unexpected type %s returned from generate: %r" % (type(sub_item), sub_item))
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

LOOKUP_CLASSES["BaseElement"] = BaseElement

class ContentElement(BaseElement):
    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(ContentElement, self)._init()
        self.dynamic_attrs = [(attr_name, attr_value) for attr_name, attr_value in self.items() if interpolation_re.search(attr_value)]
        self.static_attrs = dict([(attr_name, attr_value) for attr_name, attr_value in self.items() if attr_name not in self.dynamic_attrs])
        self.text_dynamic = bool(interpolation_re.search(self.text or ''))
        self.tail_dynamic = bool(interpolation_re.search(self.tail or ''))

    def interpolate_attrs(self, ctxt, vars):
        new_attrib = self.static_attrs.copy()
        for attr_name in self.dynamic_attrs:
            new_attrib[attr_name] = self.interpolate(self.attrib[attr_value], ctxt, vars)
        new_attrib.update(self.lookup_attrib)
        return new_attrib

    def generate(self, template, ctxt, **vars):
        """Generates XML from this element. returns an Element, an iterable set of elements, or None"""
        new_element = parser.makeelement(self.tag, self.interpolate_attrs(ctxt, vars), self.nsmap)
        if self.text_dynamic:
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
                    raise ValueError("Unexpected type %s returned from generate: %r" % (type(sub_item), sub_item))
        if self.tail_dynamic:
            new_element.tail = self.interpolate(self.text, ctxt, vars)
        else:
            new_element.tail = self.tail
        return new_element

LOOKUP_CLASSES["ContentElement"] = ContentElement

class DirectiveElement(ContentElement):
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
        for item in flatten(result):
            if item is None:
                continue
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
                raise ValueError("Unexpected type %s returned from _apply_directives: %r" % (type(item), item))
        if self.tail:
            final.append(self.tail)
        result = final
        return result

LOOKUP_CLASSES["DirectiveElement"] = DirectiveElement

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
        if LOOKUP_CLASS_TAG in element.attrib:
            class_name = element.attrib[LOOKUP_CLASS_TAG]
            return LOOKUP_CLASSES[class_name]
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
            result = ElementList(result)
        elif isinstance(result, etree._Element):
            result = ElementList([result])
        return result

