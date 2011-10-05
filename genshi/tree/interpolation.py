# -*- coding: utf-8 -*-

from genshi.template import base
from genshi.template import interpolation
from genshi.template import eval as template_eval
from genshi.tree import base as tree_base
from genshi.template import markup
from genshi import core
from lxml import etree
import re
import types
import collections

class InterpolationString(tree_base.Generator):
    _cache = {}
    def __new__(cls, text):
        if isinstance(text, list):
            return super(InterpolationString, cls).__new__(cls, text)
        if text in cls._cache:
            return cls._cache[text]
        cls._cache[text] = obj = super(InterpolationString, cls).__new__(cls, text)
        return obj

    def __init__(self, text):
        """Constructs an object which will any special variables in the given text; text can also be a list of static text or expressions"""
        start = 0
        if isinstance(text, list):
            self.parts = text
            return
        self.parts = []
        while True:
            m = tree_base.interpolation_re.search(text, start)
            if m:
                new_start, end = m.span()
                self.parts.append(text[start:new_start])
                expression, varname = m.groups()
                expression = varname if expression is None else expression
                if expression is not None:
                    expr = template_eval.Expression(expression)
                    self.parts.append(expr)
                else:
                    # escaped prefix
                    self.parts.append(interpolation.PREFIX)
                start = end
            else:
                self.parts.append(text[start:])
                break

    def eval_expr(self, expr, ctxt, vars):
        """Returns the result of an expression"""
        result = base._eval_expr(expr, ctxt, vars)
        if isinstance(result, (int, float, long)):
            result = unicode(result)
        return result

    def interpolate(self, template, ctxt, vars):
        all_strings = True
        parts = []
        for item in self.parts:
            if isinstance(item, template_eval.Expression):
                item = self.eval_expr(item, ctxt, vars)
                if isinstance(item, (list, types.GeneratorType)):
                    item = tree_base.flatten_generate(item, template, ctxt, vars)
                    all_strings = False
                elif isinstance(item, etree._Element) and all_strings:
                    all_strings = False
            parts.append(item)
        if all_strings:
            return ''.join(parts)
        return parts

    def generate(self, template, ctxt, **vars):
        """Generates XML from this element. returns an string, an iterable set of elements and strings, or None"""
        return self.interpolate(template, ctxt, vars)

class ContentElement(tree_base.BaseElement):
    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(ContentElement, self)._init()
        self.dynamic_attrs = [(attr_name, InterpolationString(attr_value)) for attr_name, attr_value in self.items() if tree_base.interpolation_re.search(attr_value)]
        self.static_attrs = dict([(attr_name, attr_value) for attr_name, attr_value in self.items() if attr_name not in self.dynamic_attrs])
        self.text_dynamic = InterpolationString(self.text) if tree_base.interpolation_re.search(self.text or '') else False
        self.tail_dynamic = InterpolationString(self.tail) if tree_base.interpolation_re.search(self.tail or '') else False

    def interpolate_attrs(self, template, ctxt, vars):
        new_attrib = self.static_attrs.copy()
        for attr_name, attr_value in self.dynamic_attrs:
            new_attrib[attr_name] = attr_value.interpolate(template, ctxt, vars)
        # since we're not copying for directives now, but generating, the target needn't be a ContentElement
        new_attrib[tree_base.LOOKUP_CLASS_TAG] = 'BaseElement'
        return new_attrib

    def generate(self, template, ctxt, **vars):
        """Generates XML from this element. returns an Element, an iterable set of elements, or None"""
        new_element = self.makeelement(self.tag, self.interpolate_attrs(template, ctxt, vars), self.nsmap)
        if self.text_dynamic:
            new_element.text = self.text_dynamic.interpolate(template, ctxt, vars)
        else:
            new_element.text = self.text
        for item in self:
            new_item = item.generate(template, ctxt, **vars)
            if not isinstance(new_item, (list, types.GeneratorType)):
                new_item = [new_item]
            for sub_item in tree_base.flatten_generate(new_item, template, ctxt, vars):
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
            new_element.tail = self.tail_dynamic.interpolate(template, ctxt, vars)
        else:
            new_element.tail = self.tail
        return new_element

tree_base.LOOKUP_CLASSES["ContentElement"] = ContentElement

