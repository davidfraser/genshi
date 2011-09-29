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
from genshi.template import directives as template_directives
from genshi.template.base import TemplateRuntimeError, TemplateSyntaxError, \
                                 EXPR, _apply_directives, _eval_expr
from genshi.template.eval import Expression, ExpressionASTTransformer, \
                                 _ast, _parse
import copy
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

class Directive(template_directives.Directive):
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

class AttrsDirective(template_directives.AttrsDirective):
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

    def __call__(self, tree, directives, ctxt, **vars):
        result = copy.copy(tree)
        result.attrib.pop(self.qname)
        result.tail = None
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
        return _apply_directives(result, directives, ctxt, vars)


class ContentDirective(template_directives.ContentDirective):
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

    @classmethod
    def attach(cls, template, tree, value, namespaces, pos):
        if type(value) is dict:
            raise TemplateSyntaxError('The content directive can not be used '
                                      'as an element', template.filepath,
                                      *pos[1:])
        directive, tree = super(template_directives.ContentDirective, cls).attach(template, tree, value, namespaces, pos)
        directive.number_conv = template._number_conv
        return directive, tree

    def __call__(self, tree, directives, ctxt, **vars):
        result = tree.makeelement(tree.tag, tree.attrib, tree.nsmap)
        result.attrib.pop(self.qname)
        content = _eval_expr(self.expr, ctxt, vars)
        if isinstance(content, (int, float, long)):
            content = self.number_conv(content)
        result.text = content
        return _apply_directives(result, directives, ctxt, vars)

class DefDirective(template_directives.DefDirective):
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

    def __call__(self, tree, directives, ctxt, **vars):

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
            for event in _apply_directives(tree, directives, ctxt, vars):
                yield event
            ctxt.pop()
        function.__name__ = self.name

        # Store the function reference in the bottom context frame so that it
        # doesn't get popped off before processing the template has finished
        # FIXME: this makes context data mutable as a side-effect
        ctxt.frames[-1][self.name] = function

        return []


class ForDirective(template_directives.ForDirective):
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

    def __call__(self, tree, directives, ctxt, **vars):
        iterable = _eval_expr(self.expr, ctxt, vars)
        if iterable is None:
            return

        assign = self.assign
        scope = {}
        tail = None
        if tree.tag == self.qname:
            repeatable = ([tree.text] if tree.text else []) + tree.getchildren()
        else:
            repeatable = copy.copy(tree)
            repeatable.attrib.pop(self.qname)
            repeatable.tail = None
        for item in iterable:
            assign(scope, item)
            ctxt.push(scope)
            result = _apply_directives(repeatable, directives, ctxt, vars)
            if result is not None:
                yield result
            ctxt.pop()


class IfDirective(template_directives.IfDirective):
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

    def __call__(self, tree, directives, ctxt, **vars):
        value = _eval_expr(self.expr, ctxt, vars)
        if value:
            if tree.tag == self.qname:
                result = ([tree.text] if tree.text else []) + tree.getchildren()
            else:
                result = copy.copy(tree)
                result.attrib.pop(self.qname)
            return _apply_directives(result, directives, ctxt, vars)
        return None


class MatchDirective(template_directives.MatchDirective):
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

    def __call__(self, tree, directives, ctxt, **vars):
        ctxt._match_templates.append((self.path.test(ignore_context=True),
                                      self.path, list(tree), self.hints,
                                      self.namespaces, directives))
        return []


class ReplaceDirective(template_directives.ReplaceDirective):
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

    @classmethod
    def attach(cls, template, tree, value, namespaces, pos):
        if type(value) is dict:
            value = value.get('value')
        if not value:
            raise TemplateSyntaxError('missing value for "replace" directive',
                                      template.filepath, *pos[1:])
        directive, tree = super(template_directives.ReplaceDirective, cls).attach(template, tree, value, namespaces, pos)
        return None, [directive.expr, tree.tail]

class StripDirective(template_directives.StripDirective):
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

    def __call__(self, tree, directives, ctxt, **vars):
        if not self.expr or _eval_expr(self.expr, ctxt, vars):
            return _apply_directives([tree.text] + list(tree.getchildren()), directives, ctxt, vars)
        else:
            result = copy.copy(tree)
            result.attrib.pop(self.qname)
            result.tail = None
            return _apply_directives(result, directives, ctxt, vars)


class ChooseDirective(template_directives.ChooseDirective):
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

    def __call__(self, tree, directives, ctxt, **vars):
        info = [False, bool(self.expr), None]
        if self.expr:
            info[2] = _eval_expr(self.expr, ctxt, vars)
        ctxt._choice_stack.append(info)
        if tree.tag == self.qname:
            result = [tree.text] + tree.getchildren()
        else:
            result = copy.copy(tree)
            result.attrib.pop(self.qname)
            result.tail = None
            for option in result[:-1]:
                option.tail = result[-1].tail
        yield _apply_directives(result, directives, ctxt, vars)
        ctxt._choice_stack.pop()


class WhenDirective(template_directives.WhenDirective):
    """Implementation of the ``py:when`` directive for nesting in a parent with
    the ``py:choose`` directive.
    
    See the documentation of the `ChooseDirective` for usage.
    """

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
        if tree.tag == self.qname:
            result = ([tree.text] if tree.text else []) + tree.getchildren()
        else:
            result = copy.copy(tree)
            result.attrib.pop(self.qname)
            result.tail = None
        return _apply_directives(result, directives, ctxt, vars)


class OtherwiseDirective(template_directives.OtherwiseDirective):
    """Implementation of the ``py:otherwise`` directive for nesting in a parent
    with the ``py:choose`` directive.
    
    See the documentation of `ChooseDirective` for usage.
    """

    def __call__(self, tree, directives, ctxt, **vars):
        info = ctxt._choice_stack and ctxt._choice_stack[-1]
        if not info:
            raise TemplateRuntimeError('an "otherwise" directive can only be '
                                       'used inside a "choose" directive',
                                       self.filename)
        if info[0]:
            return None
        info[0] = True

        if tree.tag == self.qname:
            result = ([tree.text] if tree.text else []) + tree.getchildren()
        else:
            result = copy.copy(tree)
            result.attrib.pop(self.qname)
            result.tail = None
        return _apply_directives(result, directives, ctxt, vars)


class WithDirective(template_directives.WithDirective):
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

    def __call__(self, tree, directives, ctxt, **vars):
        frame = {}
        ctxt.push(frame)
        for targets, expr in self.vars:
            value = _eval_expr(expr, ctxt, vars)
            for assign in targets:
                assign(frame, value)
        if tree.tag == self.qname:
            result = ([tree.text] if tree.text else []) + tree.getchildren()
        else:
            result = copy.copy(tree)
            result.attrib.pop(self.qname)
        yield _apply_directives(result, directives, ctxt, vars)
        ctxt.pop()

