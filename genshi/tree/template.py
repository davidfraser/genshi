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
                expr = template_eval.Expression(m.group(1))
                result.append(self.eval_expr(expr, ctxt, vars))
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
            for sub_item in new_item:
                if isinstance(sub_item, etree._Element):
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
        # TODO: work out how to strip out the namespaces
        return source.replace(' xmlns:py="http://genshi.edgewall.org/"', '')

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
        for position, item in enumerate(self):
            new_item = item.generate(template, ctxt, **vars)
            if not isinstance(new_item, (list, types.GeneratorType)):
                new_item = [new_item]
            for sub_item in new_item:
                if isinstance(sub_item, etree._Element):
                    new_element.append(sub_item)
                elif isinstance(sub_item, basestring):
                    if position == 0:
                        new_element.text = (new_element.text or "") + sub_item
                    else:
                        new_element[position-1].tail = (new_element[position-1].tail or "") + sub_item
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
            directive, substream = directive_cls.attach(template, substream, dict(self.attrib.items()), substream.nsmap, (None, None, None))
            if directive is not None:
                directives.append(directive)
        directive_attribs = set(self.keys()).intersection(GenshiElementClassLookup.directive_attrs)
        if directive_attribs:
            sorted_attribs = [name for name in GenshiElementClassLookup.directive_names if name in directive_attribs]
            for directive_qname in sorted_attribs:
                directive_cls = GenshiElementClassLookup.directive_classes[directive_qname]
                directive_value = substream.attrib.pop(directive_qname)
                directive, substream = directive_cls.attach(template, substream, directive_value, substream.nsmap, (None, None, None))
                if directive is None:
                    break
                else:
                    directives.append(directive)
        if directives:
            final = []
            result = tree_directives._apply_directives(substream, directives, ctxt, vars)
            if not isinstance(result, (types.GeneratorType, list)):
                result = [result]
            for item in result:
                if item is self:
                    final.append(ContentElement.generate(self, template, ctxt, **vars))
                elif isinstance(item, BaseElement):
                    final.append(item.generate(template, ctxt, **vars))
                elif isinstance(item, basestring):
                    final.append(item)
                else:
                    import pdb ; pdb.set_trace()
            result = final
        else:
            result = substream
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
        return root.generate(self, ctxt)
        return self.replace_placeholders(self._stream, [], ctxt, level=0)

    def replace_placeholders(self, tree, directives, ctxt, **vars):
        level_str = " "*vars["level"]*4
        vars["level"] += 1
        # print level_str, "start", tree
        if isinstance(tree, (list, etree.ElementChildIterator)):
            return [self.replace_placeholders(child, directives, ctxt, **vars) if isinstance(child, etree._Element) else child for child in tree]
        if isinstance(tree, etree._ElementTree):
            # TODO: make this proper
            tree = tree.getroot()
            tree.nsmap.pop("py", None)
        generated_tree = copy.deepcopy(tree)
        directives_dict = dict(("{%s}%s" % (GENSHI_NAMESPACE, tag), cls) for tag, cls in self.directives)
        number_conv = self._number_conv
        for target in directives_path(generated_tree):
            directives = []
            if target.tag in directives_dict:
                directive_cls = directives_dict[target.tag]
                directive, substream = directive_cls.attach(self, copy.deepcopy(target), dict(target.attrib.items()), target.nsmap, (None, None, None))
                if directive is not None:
                    directives.append(directive)
                # substream = substream.getchildren()
            else:
                substream = copy.deepcopy(target)
                for directive_name, directive_cls in self.directives:
                    directive_qname = '{%s}%s' % (GENSHI_NAMESPACE, directive_name)
                    # TODO: move the directive construction to the parse phase, alongside placeholding
                    if directive_qname in substream.attrib:
                        directive_value = substream.attrib.pop(directive_qname)
                        directive, substream = directive_cls.attach(self, substream, directive_value, substream.nsmap, (None, None, None))
                        if directive is None:
                            break
                        else:
                            directives.append(directive)
            if isinstance(substream, template_eval.Expression):
                substream = [base._eval_expr(substream, ctxt, vars)]
            if directives:
                directives.append(self.replace_placeholders)
                # print level_str, "directives", directives, substream
                result = tree_directives._apply_directives(substream, directives, ctxt, vars)
            else:
                result = substream
            # print level_str, "done"
            parent = target.getparent()
            if not parent:
                continue
            position = parent.index(target)
            # print level_str, "result", result
            parent[position:position+1] = []
            if isinstance(result, types.GeneratorType):
                result = list(result)
            elif not isinstance(result, list):
                result = [result]
            for item in result:
                # print level_str, " :item", item
                if isinstance(item, template_eval.Expression):
                    item = base._eval_expr(item, ctxt, vars)
                if isinstance(item, (int, float, long)):
                    item = number_conv(item)
                if isinstance(item, core.Markup):
                    item = etree.fromstring(u"<xml>%s</xml>" % unicode(item))
                if isinstance(item, etree._Element):
                    # print level_str, "     = ", etree.tostring(item)
                    parent.insert(position, item)
                    position += 1
                else:
                    if not isinstance(item, basestring):
                        item = unicode(item)
                    if position == 0:
                        parent.text = (parent.text or "") + item
                    else:
                        parent[position-1].tail = (parent[position-1].tail or "") + item
            # print level_str, "parent", etree.tostring(parent)
        # TODO: combine the interpolation and placeholders thing
        for expression in interpolation_path(generated_tree):
            expression_text = expression
            replace_parts = []
            for expression_part in interpolation_re.findall(expression):
                if expression_part.startswith(interpolation.PREFIX + "{"):
                    expression_code = expression_part[2:-1]
                elif expression_part.startswith(interpolation.PREFIX + interpolation.PREFIX):
                    replace_parts.append((expression_part, interpolation.PREFIX))
                    continue
                else: # PREFIX alone
                    expression_code = expression_part[1:]
                value = base._eval_expr(template_eval.Expression(expression_code), ctxt, vars)
                replace_parts.append((expression_part, value))
            result = expression_text
            for expression_part, replace_part in replace_parts:
                if isinstance(replace_part, (int, float, long)):
                    replace_part = number_conv(replace_part)
                result = result.replace(expression_part, replace_part, 1)
            parent = expression.getparent()
            if expression.is_text:
                parent.text = parent.text.replace(expression, result)
            elif expression.is_tail:
                parent.tail = parent.tail.replace(expression, result)
            elif expression.is_attribute:
                parent.attrib[expression.attrname] = parent.attrib[expression.attrname].replace(expression, result)
        return generated_tree

