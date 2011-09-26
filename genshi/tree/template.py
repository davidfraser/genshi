# -*- coding: utf-8 -*-

from genshi.template import base
from genshi.template import eval as template_eval
from genshi.tree import directives as tree_directives
from genshi.template import markup
from genshi import core
from lxml import etree
import copy
import types

# TODO: add support for <?python> PI, and ${} syntax
GENSHI_NAMESPACE = "http://genshi.edgewall.org/"
NAMESPACES = {"py": GENSHI_NAMESPACE, "pytree": "http://genshi.edgewall.org/tree/"}
directives_path = etree.XPath("//*[@py:*]|//py:*", namespaces=NAMESPACES)
placeholders_path = etree.XPath("//pytree:placeholder", namespaces=NAMESPACES)

class ElementWrapper(object):
    def __init__(self, element):
       self.element = element

    def render(self, method=None, encoding=None, out=None, **kwargs):
        # TODO: handle args
        source = etree.tostring(self.element)
        # TODO: work out how to strip out the namespaces
        return source.replace(' xmlns:py="http://genshi.edgewall.org/"', '')

    def __str__(self):
        return self.render()

    def __unicode__(self):
        return self.render(encoding=None)

    def __html__(self):
        return self

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
        source_tree = etree.parse(source)
        return source_tree

    def add_directives(self, namespace, factory):
        # currently ignores parameters
        for directive in directives_path(self._stream):
            placeholder = self.make_placeholder(directive)
            directive.getparent().replace(directive, placeholder)

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
        return ElementWrapper(self.replace_placeholders(self._stream, [], ctxt, level=0))

    def replace_placeholders(self, tree, directives, ctxt, **vars):
        level_str = " "*vars["level"]*4
        vars["level"] += 1
        # print #gclevel_str, "start", tree
        if isinstance(tree, (list, etree.ElementChildIterator)):
            return [self.replace_placeholders(child, directives, ctxt, **vars) if isinstance(child, etree._Element) else child for child in tree]
        if isinstance(tree, etree._ElementTree):
            # TODO: make this proper
            tree = tree.getroot()
            tree.nsmap.pop("py", None)
        generated_tree = copy.deepcopy(tree)
        directives_dict = dict(("{%s}%s" % (GENSHI_NAMESPACE, tag), cls) for tag, cls in self.directives)
        number_conv = self._number_conv
        for placeholder in placeholders_path(generated_tree):
            target = self._placeholders[int(placeholder.attrib['id'])]
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
                        if directive is not None:
                            directives.append(directive)
            if isinstance(substream, template_eval.Expression):
                substream = [base._eval_expr(substream, ctxt, vars)]
            directives.append(self.replace_placeholders)
            # print #gclevel_str, "directives", directives, substream
            result = tree_directives._apply_directives(substream, directives, ctxt, vars)
            # print #gclevel_str, "done"
            parent = placeholder.getparent()
            position = parent.index(placeholder)
            # print #gclevel_str, "result", result
            parent[position:position+1] = []
            if isinstance(result, types.GeneratorType):
                result = list(result)
            elif not isinstance(result, list):
                result = [result]
            for item in result:
                # print #gclevel_str, " :item", item
                if isinstance(item, template_eval.Expression):
                    item = base._eval_expr(item, ctxt, vars)
                if isinstance(item, (int, float, long)):
                    item = number_conv(item)
                if isinstance(item, core.Markup):
                    item = etree.fromstring(u"<xml>%s</xml>" % unicode(item))
                if isinstance(item, etree._Element):
                    # print #gclevel_str, "     = ", etree.tostring(item)
                    parent.insert(position, item)
                    position += 1
                else:
                    if not isinstance(item, basestring):
                        item = unicode(item)
                    if position == 0:
                        parent.text = (parent.text or "") + item
                    else:
                        parent[position-1].tail = (parent[position-1].tail or "") + item
            # print #gclevel_str, "parent", etree.tostring(parent)
        return generated_tree

