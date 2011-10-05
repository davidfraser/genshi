# -*- coding: utf-8 -*-
#
# Copyright (C) 2006-2009 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://genshi.edgewall.org/wiki/License.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://genshi.edgewall.org/log/.

"""Implementation of the various template directives, adapted to a tree structure."""

from genshi.core import QName, Stream
from genshi.path import Path
from genshi.template import markup
from genshi.template import directives as template_directives
from genshi.template.base import TemplateRuntimeError, TemplateSyntaxError, \
                                 EXPR, _apply_directives, _eval_expr
from genshi.template.eval import Expression, ExpressionASTTransformer, \
                                 _ast, _parse
from genshi.tree import interpolation
from genshi.tree import base as tree_base
import types

__all__ = ['AttrsDirective', 'ChooseDirective', 'ContentDirective',
           'DefDirective', 'ForDirective', 'IfDirective', 'MatchDirective',
           'OtherwiseDirective', 'ReplaceDirective', 'StripDirective',
           'WhenDirective', 'WithDirective']
__docformat__ = 'restructuredtext en'


def _apply_directives(tree, directives, ctxt, vars):
    """Apply the given directives to the tree.
    
    :param tree: the tree the directives should be applied to
    :param directives: the list of directives to apply
    :param ctxt: the `Context`
    :param vars: additional variables that should be available when Python
                 code is executed
    :return: the tree with the given directives applied
    """
    if directives:
        if isinstance(tree, (types.GeneratorType, list)):
            result = []
            for item in tree:
                if item is None:
                    continue
                elif isinstance(item, basestring):
                    result.append(item)
                elif isinstance(item, Expression):
                    item = _eval_expr(item, ctxt, vars)
                    if isinstance(item, (int, float, long)):
                        item = unicode(item)
                    result.append(item)
                else:
                    result.append(_apply_directives(item, directives, ctxt, vars))
            return result
        else:
            return directives[0](tree, directives[1:], ctxt, **vars)
    return tree

class DirectiveElement(interpolation.ContentElement):
    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(DirectiveElement, self)._init()
        self.directive_classes = []
        if self.tag in DIRECTIVE_TAGS:
            directive_cls = DIRECTIVE_CLASS_LOOKUP[self.tag]
            directive_value = dict(self.attrib.items())
            self.directive_classes.append((directive_cls, directive_value))
        directive_attribs = set(self.keys()).intersection(DIRECTIVE_ATTRS)
        if directive_attribs:
            self.dynamic_attrs = [(attr_name, attr_value) for (attr_name, attr_value) in self.dynamic_attrs if attr_name not in directive_attribs]
            sorted_attribs = sorted(directive_attribs, key=DIRECTIVE_NAMES.index)
            for directive_qname in sorted_attribs:
                self.static_attrs.pop(directive_qname, None)
                directive_cls = DIRECTIVE_CLASS_LOOKUP[directive_qname]
                directive_value = self.attrib[directive_qname]
                self.directive_classes.append((directive_cls, directive_value))

    @classmethod
    def has_directives(cls, element):
        """Returns a list of directives that are present on the given (read-only) element"""
        directives_found = []
        if element.tag in DIRECTIVE_TAGS:
            return True
        elif element.tag in DIRECTIVE_ATTRS:
            raise TemplateSyntaxError('The %s directive can not be used as an element' % element.tag[:element.tag.find('}')+1])
        attribs = set(element.keys()).intersection(DIRECTIVE_ATTRS)
        return bool(attribs)

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
            result = _apply_directives(substream, directives, ctxt, vars)
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
            elif isinstance(item, Expression):
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

#    directives = [('def', DefDirective),                # returns generator
#                  ('match', MatchDirective),            # returns empty list
#                  ('when', WhenDirective),              # returns standard, None or empty list
#                  ('otherwise', OtherwiseDirective),    # returns standard or None
#                  ('for', ForDirective),                # returns generator
#                  ('if', IfDirective),                  # returns standard or None
#                  ('choose', ChooseDirective),          # returns generator
#                  ('with', WithDirective),              # returns generator
#                  ('replace', ReplaceDirective),        # special - no directive
#                  ('content', ContentDirective),        # returns standard
#                  ('attrs', AttrsDirective),            # returns standard
#                  ('strip', StripDirective)]            # returns standard

class Directive(object):
    """Abstract base class for template directives.
    
    A directive is basically a callable that takes three positional arguments:
    ``ctxt`` is the template data context, ``tree`` is an lxml element or tree
    that the directive applies to, and ``directives`` is is a list of
    other directives on the same tree that need to be applied.
    
    Directives can be "anonymous" or "registered". Registered directives can be
    applied by the template author using an XML attribute with the
    corresponding name in the template. Such directives should be subclasses of
    this base class that can  be instantiated with the value of the directive
    attribute as parameter.
    
    Anonymous directives are simply functions conforming to the protocol
    described above, and can only be applied programmatically (for example by
    template filters).
    """
    __slots__ = ['expr']

    include_tail = False

    def __init__(self, value, template=None, namespaces=None, lineno=-1,
                 offset=-1):
        self.expr = self._parse_expr(value, template, lineno, offset)

    def undirectify(self, tree):
        if tree.tag == self.qname:
            result = ([tree.text_dynamic if tree.text_dynamic else tree.text] if tree.text else []) + tree.getchildren()
        else:
            attrib = dict(tree.attrib.items())
            attrib.pop(self.qname, None)
            attrib["{http://genshi.edgewall.org/}classname"] = "ContentElement"
            result = tree.makeelement(tree.tag, attrib, tree.nsmap)
            result.text = tree.text
            result.extend(tree.getchildren())
            result._init()
            if self.include_tail:
                result.tail = tree.tail
        return result

    @classmethod
    def attach(cls, template, tree, value, namespaces, pos):
        """Called after the template tree has been completely parsed.
        
        :param template: the `Template` object
        :param tree: the lxml tree associated with the directive
        :param value: the argument value for the directive; if the directive was
                      specified as an element, this will be an `Attrs` instance
                      with all specified attributes, otherwise it will be a
                      `unicode` object with just the attribute value
        :param namespaces: a mapping of namespace URIs to prefixes
        :param pos: a ``(filename, lineno, offset)`` tuple describing the
                    location where the directive was found in the source
        
        This class method should return a ``(directive, tree)`` tuple. If
        ``directive`` is not ``None``, it should be an instance of the `Directive`
        class, and gets added to the list of directives applied to the subtree
        at runtime. `tree` is an lxml tree that replaces the original
        tree associated with the directive.
        """
        return cls(value, template, namespaces, *pos[1:]), tree

    def __call__(self, tree, directives, ctxt, **vars):
        """Apply the directive to the given tree.
        
        :param tree: the lxml tree
        :param directives: a list of the remaining directives that should
                           process the tree
        :param ctxt: the context data
        :param vars: additional variables that should be made available when
                     Python code is executed
        """
        raise NotImplementedError

    def __repr__(self):
        expr = ''
        if getattr(self, 'expr', None) is not None:
            expr = ' "%s"' % self.expr.source
        return '<%s%s>' % (type(self).__name__, expr)

    @classmethod
    def _parse_expr(cls, expr, template, lineno=-1, offset=-1):
        """Parses the given expression, raising a useful error message when a
        syntax error is encountered.
        """
        try:
            return expr and Expression(expr, template.filepath, lineno,
                                       lookup=template.lookup) or None
        except SyntaxError, err:
            err.msg += ' in expression "%s" of "%s" directive' % (expr,
                                                                  cls.tagname)
            raise TemplateSyntaxError(err, template.filepath, lineno,
                                      offset + (err.offset or 0))

class AttrsDirective(Directive):
    """Implementation of the ``py:attrs`` template directive.
    
    The value of the ``py:attrs`` attribute should be a dictionary or a sequence
    of ``(name, value)`` tuples. The items in that dictionary or sequence are
    added as attributes to the element:
    
    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<ul xmlns:py="http://genshi.edgewall.org/">
    ...   <li py:attrs="foo">Bar</li>
    ... </ul>''')
    >>> print(tmpl.generate(foo={'class': 'collapse'}))
    <ul>
      <li class="collapse">Bar</li>
    </ul>
    >>> print(tmpl.generate(foo=[('class', 'collapse')]))
    <ul>
      <li class="collapse">Bar</li>
    </ul>
    
    If the value evaluates to ``None`` (or any other non-truth value), no
    attributes are added:
    
    >>> print(tmpl.generate(foo=None))
    <ul>
      <li>Bar</li>
    </ul>
    """
    __slots__ = []
    tagname = 'attrs'

    def __call__(self, tree, directives, ctxt, **vars):
        result = self.undirectify(tree)
        attrs = _eval_expr(self.expr, ctxt, vars)
        if attrs:
            if isinstance(attrs, Stream):
                try:
                    attrs = iter(attrs).next()
                except StopIteration:
                    attrs = []
            elif not isinstance(attrs, list): # assume it's a dict
                attrs = attrs.items()
            del_attrs = [n for n, v in attrs if v is None]
            attrs = [(n, unicode(v).strip()) for n, v in attrs if v is not None]
            result.attrib.update(attrs)
            for attr in del_attrs:
                result.attrib.pop(attr, None)
            if hasattr(result, "_init"):
                result._init()
        return _apply_directives(result, directives, ctxt, vars)


class ContentDirective(Directive):
    """Implementation of the ``py:content`` template directive.
    
    This directive replaces the content of the element with the result of
    evaluating the value of the ``py:content`` attribute:
    
    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<ul xmlns:py="http://genshi.edgewall.org/">
    ...   <li py:content="bar">Hello</li>
    ... </ul>''')
    >>> print(tmpl.generate(bar='Bye'))
    <ul>
      <li>Bye</li>
    </ul>
    """
    __slots__ = ["number_conv"]
    tagname = 'content'

    @classmethod
    def attach(cls, template, tree, value, namespaces, pos):
        if type(value) is dict:
            raise TemplateSyntaxError('The content directive can not be used '
                                      'as an element', template.filepath,
                                      *pos[1:])
        directive, tree = super(ContentDirective, cls).attach(template, tree, value, namespaces, pos)
        directive.number_conv = template._number_conv
        return directive, tree

    def undirectify(self, tree):
        lookup_attrib = [(tree.lookup_attrib[0][0], 'BaseElement')]
        result = tree.makeelement(tree.tag, dict(tree.attrib.items() + lookup_attrib), tree.nsmap)
        result.attrib.pop(self.qname, None)
        return result

    def __call__(self, tree, directives, ctxt, **vars):
        result = self.undirectify(tree)
        content = _eval_expr(self.expr, ctxt, vars)
        if isinstance(content, (int, float, long)):
            content = self.number_conv(content)
        result.text = content
        return _apply_directives(result, directives, ctxt, vars)

class DefDirective(Directive):
    """Implementation of the ``py:def`` template directive.
    
    This directive can be used to create "Named Template Functions", which
    are template snippets that are not actually output during normal
    processing, but rather can be expanded from expressions in other places
    in the template.
    
    A named template function can be used just like a normal Python function
    from template expressions:
    
    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/">
    ...   <p py:def="echo(greeting, name='world')" class="message">
    ...     ${greeting}, ${name}!
    ...   </p>
    ...   ${echo('Hi', name='you')}
    ... </div>''')
    >>> print(tmpl.generate(bar='Bye'))
    <div>
      <p class="message">
        Hi, you!
      </p>
    </div>
    
    If a function does not require parameters, the parenthesis can be omitted
    in the definition:
    
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/">
    ...   <p py:def="helloworld" class="message">
    ...     Hello, world!
    ...   </p>
    ...   ${helloworld()}
    ... </div>''')
    >>> print(tmpl.generate(bar='Bye'))
    <div>
      <p class="message">
        Hello, world!
      </p>
    </div>
    """
    __slots__ = ['name', 'args', 'star_args', 'dstar_args', 'defaults']
    tagname = 'def'

    def __init__(self, args, template, namespaces=None, lineno=-1, offset=-1):
        Directive.__init__(self, None, template, namespaces, lineno, offset)
        ast = _parse(args).body
        self.args = []
        self.star_args = None
        self.dstar_args = None
        self.defaults = {}
        if isinstance(ast, _ast.Call):
            self.name = ast.func.id
            for arg in ast.args:
                # only names
                self.args.append(arg.id)
            for kwd in ast.keywords:
                self.args.append(kwd.arg)
                exp = Expression(kwd.value, template.filepath,
                                 lineno, lookup=template.lookup)
                self.defaults[kwd.arg] = exp
            if getattr(ast, 'starargs', None):
                self.star_args = ast.starargs.id
            if getattr(ast, 'kwargs', None):
                self.dstar_args = ast.kwargs.id
        else:
            self.name = ast.id

    @classmethod
    def attach(cls, template, stream, value, namespaces, pos):
        if type(value) is dict:
            value = value.get('function')
        return super(DefDirective, cls).attach(template, stream, value,
                                               namespaces, pos)

    def __call__(self, tree, directives, ctxt, **vars):

        body = self.undirectify(tree)
        def function(*args, **kwargs):
            scope = {}
            args = list(args) # make mutable
            for name in self.args:
                if args:
                    scope[name] = args.pop(0)
                else:
                    if name in kwargs:
                        val = kwargs.pop(name)
                    else:
                        val = _eval_expr(self.defaults.get(name), ctxt, vars)
                    scope[name] = val
            if not self.star_args is None:
                scope[self.star_args] = args
            if not self.dstar_args is None:
                scope[self.dstar_args] = kwargs
            ctxt.push(scope)
            for event in _apply_directives(body, directives, ctxt, vars):
                yield event
            ctxt.pop()
        function.__name__ = self.name

        # Store the function reference in the bottom context frame so that it
        # doesn't get popped off before processing the template has finished
        # FIXME: this makes context data mutable as a side-effect
        ctxt.frames[-1][self.name] = function

        return []

    def __repr__(self):
        return '<%s "%s">' % (type(self).__name__, self.name)


class ForDirective(Directive):
    """Implementation of the ``py:for`` template directive for repeating an
    element based on an iterable in the context data.
    
    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<ul xmlns:py="http://genshi.edgewall.org/">
    ...   <li py:for="item in items">${item}</li>
    ... </ul>''')
    >>> print(tmpl.generate(items=[1, 2, 3]))
    <ul>
      <li>1</li><li>2</li><li>3</li>
    </ul>
    """
    __slots__ = ['assign', 'filename']
    tagname = 'for'

    def __init__(self, value, template, namespaces=None, lineno=-1, offset=-1):
        if ' in ' not in value:
            raise TemplateSyntaxError('"in" keyword missing in "for" directive',
                                      template.filepath, lineno, offset)
        assign, value = value.split(' in ', 1)
        ast = _parse(assign, 'exec')
        value = 'iter(%s)' % value.strip()
        self.assign = template_directives._assignment(ast.body[0].value)
        self.filename = template.filepath
        Directive.__init__(self, value, template, namespaces, lineno, offset)

    @classmethod
    def attach(cls, template, stream, value, namespaces, pos):
        if type(value) is dict:
            value = value.get('each')
        return super(ForDirective, cls).attach(template, stream, value,
                                               namespaces, pos)

    def __call__(self, tree, directives, ctxt, **vars):
        iterable = _eval_expr(self.expr, ctxt, vars)
        if iterable is None:
            return

        assign = self.assign
        scope = {}
        tail = None
        repeatable = self.undirectify(tree)
        for item in iterable:
            assign(scope, item)
            ctxt.push(scope)
            result = _apply_directives(repeatable, directives, ctxt, vars)
            if result is not None:
                yield result
            ctxt.pop()

    def __repr__(self):
        return '<%s>' % type(self).__name__

class IfDirective(Directive):
    """Implementation of the ``py:if`` template directive for conditionally
    excluding elements from being output.
    
    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/">
    ...   <b py:if="foo">${bar}</b>
    ... </div>''')
    >>> print(tmpl.generate(foo=True, bar='Hello'))
    <div>
      <b>Hello</b>
    </div>
    """
    __slots__ = []
    tagname = 'if'

    include_tail = True

    @classmethod
    def attach(cls, template, stream, value, namespaces, pos):
        if type(value) is dict:
            value = value.get('test')
        return super(IfDirective, cls).attach(template, stream, value,
                                              namespaces, pos)

    def __call__(self, tree, directives, ctxt, **vars):
        value = _eval_expr(self.expr, ctxt, vars)
        if value:
            return _apply_directives(self.undirectify(tree), directives, ctxt, vars)
        return None


class MatchDirective(Directive):
    """Implementation of the ``py:match`` template directive.

    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/">
    ...   <span py:match="greeting">
    ...     Hello ${select('@name')}
    ...   </span>
    ...   <greeting name="Dude" />
    ... </div>''')
    >>> print(tmpl.generate())
    <div>
      <span>
        Hello Dude
      </span>
    </div>
    """
    __slots__ = ['path', 'namespaces', 'hints']
    tagname = 'match'

    def __init__(self, value, template, hints=None, namespaces=None,
                 lineno=-1, offset=-1):
        Directive.__init__(self, None, template, namespaces, lineno, offset)
        self.path = Path(value, template.filepath, lineno)
        self.namespaces = namespaces or {}
        self.hints = hints or ()

    @classmethod
    def attach(cls, template, tree, value, namespaces, pos):
        hints = []
        if type(value) is dict:
            if value.get('buffer', '').lower() == 'false':
                hints.append('not_buffered')
            if value.get('once', '').lower() == 'true':
                hints.append('match_once')
            if value.get('recursive', '').lower() == 'false':
                hints.append('not_recursive')
            value = value.get('path')
        return cls(value, template, frozenset(hints), namespaces, *pos[1:]), \
               tree

    def undirectify(self, tree):
        return ([tree.text_dynamic if tree.text_dynamic else tree.text] if tree.text else []) + tree.getchildren()

    def __call__(self, tree, directives, ctxt, **vars):
        ctxt._match_templates.append((self.path.test(ignore_context=True),
                                      self.path, self.undirectify(tree), self.hints,
                                      self.namespaces, directives))
        return []


    def __repr__(self):
        return '<%s "%s">' % (type(self).__name__, self.path.source)

class ReplaceDirective(Directive):
    """Implementation of the ``py:replace`` template directive.
    
    This directive replaces the element with the result of evaluating the
    value of the ``py:replace`` attribute:
    
    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/">
    ...   <span py:replace="bar">Hello</span>
    ... </div>''')
    >>> print(tmpl.generate(bar='Bye'))
    <div>
      Bye
    </div>
    
    This directive is equivalent to ``py:content`` combined with ``py:strip``,
    providing a less verbose way to achieve the same effect:
    
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/">
    ...   <span py:content="bar" py:strip="">Hello</span>
    ... </div>''')
    >>> print(tmpl.generate(bar='Bye'))
    <div>
      Bye
    </div>
    """
    __slots__ = []
    tagname = 'replace'

    @classmethod
    def attach(cls, template, tree, value, namespaces, pos):
        if type(value) is dict:
            value = value.get('value')
        if not value:
            raise TemplateSyntaxError('missing value for "replace" directive',
                                      template.filepath, *pos[1:])
        directive, tree = super(ReplaceDirective, cls).attach(template, tree, value, namespaces, pos)
        return None, [directive.expr, tree.tail_dynamic if tree.tail_dynamic else tree.tail]

class StripDirective(Directive):
    """Implementation of the ``py:strip`` template directive.
    
    When the value of the ``py:strip`` attribute evaluates to ``True``, the
    element is stripped from the output
    
    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/">
    ...   <div py:strip="True"><b>foo</b></div>
    ... </div>''')
    >>> print(tmpl.generate())
    <div>
      <b>foo</b>
    </div>
    
    Leaving the attribute value empty is equivalent to a truth value.
    
    This directive is particulary interesting for named template functions or
    match templates that do not generate a top-level element:
    
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/">
    ...   <div py:def="echo(what)" py:strip="">
    ...     <b>${what}</b>
    ...   </div>
    ...   ${echo('foo')}
    ... </div>''')
    >>> print(tmpl.generate())
    <div>
        <b>foo</b>
    </div>
    """
    __slots__ = []
    tagname = 'def'

    def __call__(self, tree, directives, ctxt, **vars):
        if not self.expr or _eval_expr(self.expr, ctxt, vars):
            return _apply_directives([tree.text_dynamic if tree.text_dynamic else tree.text] + list(tree.getchildren()), directives, ctxt, vars)
        else:
            return _apply_directives(self.undirectify(tree), directives, ctxt, vars)


class ChooseDirective(Directive):
    """Implementation of the ``py:choose`` directive for conditionally selecting
    one of several body elements to display.
    
    If the ``py:choose`` expression is empty the expressions of nested
    ``py:when`` directives are tested for truth.  The first true ``py:when``
    body is output. If no ``py:when`` directive is matched then the fallback
    directive ``py:otherwise`` will be used.
    
    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/"
    ...   py:choose="">
    ...   <span py:when="0 == 1">0</span>
    ...   <span py:when="1 == 1">1</span>
    ...   <span py:otherwise="">2</span>
    ... </div>''')
    >>> print(tmpl.generate())
    <div>
      <span>1</span>
    </div>
    
    If the ``py:choose`` directive contains an expression, the nested
    ``py:when`` directives are tested for equality to the ``py:choose``
    expression:
    
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/"
    ...   py:choose="2">
    ...   <span py:when="1">1</span>
    ...   <span py:when="2">2</span>
    ... </div>''')
    >>> print(tmpl.generate())
    <div>
      <span>2</span>
    </div>
    
    Behavior is undefined if a ``py:choose`` block contains content outside a
    ``py:when`` or ``py:otherwise`` block.  Behavior is also undefined if a
    ``py:otherwise`` occurs before ``py:when`` blocks.
    """
    __slots__ = ['matched', 'value']
    tagname = 'choose'

    def undirectify(self, tree):
        result = super(ChooseDirective, self).undirectify(tree)
        if tree.tag != self.qname and len(result):
            for option in result[:-1]:
                option.tail = result[-1].tail
        return result

    @classmethod
    def attach(cls, template, stream, value, namespaces, pos):
        if type(value) is dict:
            value = value.get('test')
        return super(ChooseDirective, cls).attach(template, stream, value,
                                                  namespaces, pos)

    def __call__(self, tree, directives, ctxt, **vars):
        info = [False, bool(self.expr), None]
        if self.expr:
            info[2] = _eval_expr(self.expr, ctxt, vars)
        ctxt._choice_stack.append(info)
        yield _apply_directives(self.undirectify(tree), directives, ctxt, vars)
        ctxt._choice_stack.pop()


class WhenDirective(Directive):
    """Implementation of the ``py:when`` directive for nesting in a parent with
    the ``py:choose`` directive.
    
    See the documentation of the `ChooseDirective` for usage.
    """
    __slots__ = ['filename']
    tagname = 'when'

    def __init__(self, value, template, namespaces=None, lineno=-1, offset=-1):
        Directive.__init__(self, value, template, namespaces, lineno, offset)
        self.filename = template.filepath

    @classmethod
    def attach(cls, template, stream, value, namespaces, pos):
        if type(value) is dict:
            value = value.get('test')
        return super(WhenDirective, cls).attach(template, stream, value,
                                                namespaces, pos)

    def __call__(self, tree, directives, ctxt, **vars):
        info = ctxt._choice_stack and ctxt._choice_stack[-1]
        if not info:
            raise TemplateRuntimeError('"when" directives can only be used '
                                       'inside a "choose" directive',
                                       self.filename)
        if info[0]:
            return []
        if not self.expr and not info[1]:
            raise TemplateRuntimeError('either "choose" or "when" directive '
                                       'must have a test expression',
                                       self.filename)
        if info[1]:
            value = info[2]
            if self.expr:
                matched = value == _eval_expr(self.expr, ctxt, vars)
            else:
                matched = bool(value)
        else:
            matched = bool(_eval_expr(self.expr, ctxt, vars))
        info[0] = matched
        if not matched:
            return None
        return _apply_directives(self.undirectify(tree), directives, ctxt, vars)


class OtherwiseDirective(Directive):
    """Implementation of the ``py:otherwise`` directive for nesting in a parent
    with the ``py:choose`` directive.
    
    See the documentation of `ChooseDirective` for usage.
    """
    __slots__ = ['filename']
    tagname = 'otherwise'

    def __init__(self, value, template, namespaces=None, lineno=-1, offset=-1):
        Directive.__init__(self, None, template, namespaces, lineno, offset)
        self.filename = template.filepath

    def __call__(self, tree, directives, ctxt, **vars):
        info = ctxt._choice_stack and ctxt._choice_stack[-1]
        if not info:
            raise TemplateRuntimeError('an "otherwise" directive can only be '
                                       'used inside a "choose" directive',
                                       self.filename)
        if info[0]:
            return None
        info[0] = True

        return _apply_directives(self.undirectify(tree), directives, ctxt, vars)


class WithDirective(Directive):
    """Implementation of the ``py:with`` template directive, which allows
    shorthand access to variables and expressions.
    
    >>> from genshi.tree import TreeTemplate
    >>> tmpl = TreeTemplate('''<div xmlns:py="http://genshi.edgewall.org/">
    ...   <span py:with="y=7; z=x+10">$x $y $z</span>
    ... </div>''')
    >>> print(tmpl.generate(x=42))
    <div>
      <span>42 7 52</span>
    </div>
    """
    __slots__ = ['vars']
    tagname = 'with'

    include_tail = True

    def __init__(self, value, template, namespaces=None, lineno=-1, offset=-1):
        Directive.__init__(self, None, template, namespaces, lineno, offset)
        self.vars = []
        value = value.strip()
        try:
            ast = _parse(value, 'exec')
            for node in ast.body:
                if not isinstance(node, _ast.Assign):
                    raise TemplateSyntaxError('only assignment allowed in '
                                              'value of the "with" directive',
                                              template.filepath, lineno, offset)
                self.vars.append(([template_directives._assignment(n) for n in node.targets],
                                  Expression(node.value, template.filepath,
                                             lineno, lookup=template.lookup)))
        except SyntaxError, err:
            err.msg += ' in expression "%s" of "%s" directive' % (value,
                                                                  self.tagname)
            raise TemplateSyntaxError(err, template.filepath, lineno,
                                      offset + (err.offset or 0))

    @classmethod
    def attach(cls, template, stream, value, namespaces, pos):
        if type(value) is dict:
            value = value.get('vars')
        return super(WithDirective, cls).attach(template, stream, value,
                                                namespaces, pos)

    def __call__(self, tree, directives, ctxt, **vars):
        frame = {}
        ctxt.push(frame)
        for targets, expr in self.vars:
            value = _eval_expr(expr, ctxt, vars)
            for assign in targets:
                assign(frame, value)
        yield _apply_directives(self.undirectify(tree), directives, ctxt, vars)
        ctxt.pop()

    def __repr__(self):
        return '<%s>' % (type(self).__name__)

DIRECTIVE_CLASS_LOOKUP = dict([("{%s}%s" % (tree_base.GENSHI_NAMESPACE, directive_tag), locals().get("%sDirective" % directive_tag.title(), directive_cls)) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives])
DIRECTIVE_NAMES = ["{%s}%s" % (tree_base.GENSHI_NAMESPACE, directive_tag) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives]
DIRECTIVE_TAGS = set([directive_tag for directive_tag in DIRECTIVE_NAMES if directive_tag[directive_tag.find("}")+1:] not in ("content", "attrs", "strip")])
DIRECTIVE_ATTRS = set(DIRECTIVE_NAMES)

# TODO: find a cleaner way to do this
for directive_qname, directive_cls in DIRECTIVE_CLASS_LOOKUP.items():
    setattr(directive_cls, "qname", directive_qname)

