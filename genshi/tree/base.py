# -*- coding: utf-8 -*-

from genshi.template import base
from genshi.template import interpolation
from genshi.template import eval as template_eval
from lxml import etree
import re
import types
import collections

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

def flatten_generate(l, template, ctxt, vars):
    if isinstance(l, (basestring, etree._Element)):
        l = [l]
    for el in l:
        if isinstance(el, collections.Iterable) and not isinstance(el, (basestring, etree._Element)):
            for sub in flatten_generate(el, template, ctxt, vars):
                yield sub
        elif isinstance(el, (BaseElement, Generator)):
            result = el.generate(template, ctxt, **vars)
            if isinstance(result, collections.Iterable) and not isinstance(result, (basestring, etree._Element)):
                for sub in flatten_generate(result, template, ctxt, vars):
                    yield sub
            else:
                yield result
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

    def select(self, xpath):
        return ElementList([item.xpath(xpath) for item in self])

    def __str__(self):
        return self.render()

    def __unicode__(self):
        return self.render(encoding=None)

    def __html__(self):
        return self

class Generator(object):
    def generate(self, template, ctxt, **vars):
        """Generates XML from this element. returns an Element, an iterable set of elements, or None"""
        raise NotImplementedError

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
        new_element = self.makeelement(self.tag, attrib, self.nsmap)
        new_element.text, new_element.tail = self.text, self.tail
        for item in self:
            new_item = item.generate(template, ctxt, **vars)
            if isinstance(new_item, types.GeneratorType):
                new_item = list(new_item)
            elif not isinstance(new_item, list):
                new_item = [new_item]
            for sub_item in flatten_generate(new_item, template, ctxt, vars):
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

