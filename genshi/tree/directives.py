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

class Directive(interpolation.ContentElement):
    """Abstract base class for template directives elements
    
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
    # __slots__ = ['expr']
    include_tail = False

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(Directive, self)._init()
        directive_attribs = set(self.keys()).intersection(DIRECTIVE_ATTRS)
        if directive_attribs:
            self.dynamic_attrs = [(attr_name, attr_value) for (attr_name, attr_value) in self.dynamic_attrs if attr_name not in directive_attribs]
            for directive_qname in directive_attribs:
                self.static_attrs.pop(directive_qname, None)

    @classmethod
    def get_directive_cls(cls, element):
        directive_classes = []
        if element.tag in DIRECTIVE_TAGS:
            directive_cls = DIRECTIVE_CLASS_LOOKUP[element.tag]
            # directive_value = dict(element.attrib.items())
            directive_classes.append(directive_cls)
        directive_attribs = set(element.keys()).intersection(DIRECTIVE_ATTRS)
        if directive_attribs:
            sorted_attribs = sorted(directive_attribs, key=DIRECTIVE_NAMES.index)
            for directive_qname in sorted_attribs:
                directive_cls = DIRECTIVE_CLASS_LOOKUP[directive_qname]
                # directive_value = element.attrib[directive_qname]
                directive_classes.append(directive_cls)
        if not directive_classes:
            return None
        if len(directive_classes) == 1:
            return directive_classes[0]
        # TODO: lock this type generation section
        class_set = frozenset(directive_classes)
        if class_set in DIRECTIVE_DERIVATION:
            return DIRECTIVE_DERIVATION[class_set]
        derived_name = ''.join(directive_cls.__name__.replace("Directive", "") for directive_cls in directive_classes )+'Directive'
        derived_dict = {}
        for directive_cls in reversed(directive_classes):
            derived_dict.update(directive_cls.__dict__)
        derived_class = DIRECTIVE_DERIVATION[class_set] = type(derived_name, tuple(directive_classes), derived_dict)
        return derived_class

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
        return etree.ElementBase.__repr__(self).replace("<Element", "<Directive", 1)

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

    def undirectify_base(cls, self):
        cls = type(self) if cls is None else cls
        if self.tag == cls.qname:
            result = ([self.text_dynamic if self.text_dynamic else self.text] if self.text else []) + self.getchildren()
            if cls.include_tail:
                # TODO: review whether this should handle _dynamic
                result.append(self.tail)
        else:
            attrib = dict(self.attrib.items())
            attrib.pop(cls.qname, None)
            if not set(attrib).intersection(DIRECTIVE_ATTRS):
                attrib[tree_base.LOOKUP_CLASS_TAG] = "ContentElement"
            result = self.makeelement(self.tag, attrib, self.nsmap)
            result.text = self.text
            result.extend(self.getchildren())
            result._init()
            if cls.include_tail:
                result.tail = self.tail
        return result
    undirectify = classmethod(undirectify_base)
    undirectify_static = staticmethod(undirectify_base)

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
    def _parse_expr(cls, expr, filepath="<string>", lineno=-1, offset=-1, lookup='strict'):
        """Parses the given expression, raising a useful error message when a
        syntax error is encountered.
        """
        try:
            return expr and Expression(expr, filepath, lineno, lookup=lookup) or None
        except SyntaxError, err:
            err.msg += ' in expression "%s" of "%s" directive' % (expr,
                                                                  cls.tagname)
            raise TemplateSyntaxError(err, filepath, lineno,
                                      offset + (err.offset or 0))

tree_base.LOOKUP_CLASSES["Directive"] = Directive

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
    # __slots__ = []
    tagname = 'attrs'
    include_tail = True

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(AttrsDirective, self)._init()
        value = self.attrib.get(AttrsDirective.qname)
        self.attrs_expr = self._parse_expr(value, None, 1, 1)

    def generate(self, template, ctxt, **vars):
        result = AttrsDirective.undirectify(self)
        attrs = _eval_expr(self.attrs_expr, ctxt, vars)
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
        return tree_base.flatten_generate(result, template, ctxt, vars)


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
    # __slots__ = ["number_conv"]
    tagname = 'content'
    include_tail = True

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(ContentDirective, self)._init()
        value = self.attrib.get(ContentDirective.qname)
        self.text_dynamic = interpolation.InterpolationString([self._parse_expr(value, None, 1, 1)])

    def generate(self, template, ctxt, **vars):
        # FIXME: this won't mix properly with lower-down directives (i.e. py:attrs or py:strip)
        return interpolation.ContentElement.generate(self, template, ctxt, **vars)

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
    # __slots__ = ['name', 'args', 'star_args', 'dstar_args', 'defaults']
    tagname = 'def'

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(DefDirective, self)._init()
        if self.tag == DefDirective.qname:
            function_def = self.attrib.get('function')
        else:
            function_def = self.attrib.get(DefDirective.qname)
        ast = _parse(function_def).body
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
                exp = Expression(kwd.value, "<string>", 1, lookup='strict')
                self.defaults[kwd.arg] = exp
            if getattr(ast, 'starargs', None):
                self.star_args = ast.starargs.id
            if getattr(ast, 'kwargs', None):
                self.dstar_args = ast.kwargs.id
        else:
            self.name = ast.id

    def generate(self, template, ctxt, **vars):

        body = DefDirective.undirectify(self)
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
            yield list(tree_base.flatten_generate(body, template, ctxt, vars))
            ctxt.pop()
        function.__name__ = self.name

        # Store the function reference in the bottom context frame so that it
        # doesn't get popped off before processing the template has finished
        # FIXME: this makes context data mutable as a side-effect
        ctxt.frames[-1][self.name] = function

        return self.tail_dynamic if self.tail_dynamic else self.tail

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
    # __slots__ = ['assign', 'filename']
    tagname = 'for'
    include_tail = False

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(ForDirective, self)._init()
        if self.tag == ForDirective.qname:
            value = self.attrib.get('each')
        else:
            value = self.attrib.get(ForDirective.qname)
        if ' in ' not in value:
            raise TemplateSyntaxError('"in" keyword missing in "for" directive',
                                      "<string>", 1, 1)
        assign, value = value.split(' in ', 1)
        ast = _parse(assign, 'exec')
        value = 'iter(%s)' % value.strip()
        self.assign = template_directives._assignment(ast.body[0].value)
        self.for_expr = self._parse_expr(value, None, 1, 1)
        self.filename = "<string>"

    def generate(self, template, ctxt, **vars):
        iterable = _eval_expr(self.for_expr, ctxt, vars)
        if iterable is None:
            return

        assign = self.assign
        scope = {}
        tail = None
        repeatable = ForDirective.undirectify(self)
        for item in iterable:
            assign(scope, item)
            ctxt.push(scope)
            result = tree_base.flatten_generate(repeatable, template, ctxt, vars)
            if result is not None:
                yield list(result)
            ctxt.pop()
        yield self.tail_dynamic if self.tail_dynamic else self.tail

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
    # __slots__ = []
    tagname = 'if'

    include_tail = True

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(IfDirective, self)._init()
        if self.tag == IfDirective.qname:
            value = self.attrib.get('test')
        else:
            value = self.attrib.get(IfDirective.qname)
        self.if_expr = self._parse_expr(value, None, 1, 1)

    def generate(self, template, ctxt, **vars):
        value = _eval_expr(self.if_expr, ctxt, vars)
        if value:
            return tree_base.flatten_generate(IfDirective.undirectify(self), template, ctxt, vars)
        return self.tail_dynamic if self.tail_dynamic else self.tail


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
    # __slots__ = ['path', 'namespaces', 'hints']
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

    @classmethod
    def undirectify(cls, self):
        cls = type(self) if cls is None else cls
        return ([self.text_dynamic if self.text_dynamic else self.text] if self.text else []) + self.getchildren()

    def __call__(self, tree, directives, ctxt, **vars):
        ctxt._match_templates.append((self.path.test(ignore_context=True),
                                      self.path, MatchDirective.undirectify(self), self.hints,
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
    # __slots__ = []
    tagname = 'replace'

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(ReplaceDirective, self)._init()
        if self.tag == ReplaceDirective.qname:
            value = self.attrib.get('value')
        else:
            value = self.attrib.get(ReplaceDirective.qname)
        if not value:
            raise TemplateSyntaxError('missing value for "replace" directive',
                                      "<string>", 1, 1)
        self.text_dynamic = interpolation.InterpolationString([self._parse_expr(value, None, 1, 1)])

    def generate(self, template, ctxt, **vars):
        return [self.text_dynamic, self.tail_dynamic if self.tail_dynamic else self.tail]

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
    # __slots__ = []
    tagname = 'strip'
    include_tail = True

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(StripDirective, self)._init()
        value = self.attrib.get(StripDirective.qname)
        self.strip_expr = self._parse_expr(value, None, 1, 1)

    def generate(self, template, ctxt, **vars):
        if not self.strip_expr or _eval_expr(self.strip_expr, ctxt, vars):
            text = self.text_dynamic if self.text_dynamic else self.text
            return tree_base.flatten_generate([text] + list(self.getchildren()) + [self.tail_dynamic if self.tail_dynamic else self.tail], template, ctxt, vars)
        else:
            return tree_base.flatten_generate(StripDirective.undirectify(self), template, ctxt, vars)


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
    # __slots__ = ['matched', 'value']
    tagname = 'choose'
    include_tail = True

    @classmethod
    def undirectify(cls, self):
        cls = type(self) if cls is None else cls
        result = Directive.undirectify_static(ChooseDirective, self)
        if self.tag != ChooseDirective.qname and len(result):
            for option in result[:-1]:
                option.tail = result[-1].tail
        return result

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(ChooseDirective, self)._init()
        if self.tag == ChooseDirective.qname:
            value = self.attrib.get('test')
        else:
            value = self.attrib.get(ChooseDirective.qname)
        if value is None:
            self.choose_expr = None
        else:
            value = value.strip()
            self.choose_expr = self._parse_expr(value, None, 1, 1)

    def generate(self, template, ctxt, **vars):
        info = [False, bool(self.choose_expr), None]
        if self.choose_expr:
            info[2] = _eval_expr(self.choose_expr, ctxt, vars)
        ctxt._choice_stack.append(info)
        yield list(tree_base.flatten_generate(ChooseDirective.undirectify(self), template, ctxt, vars))
        ctxt._choice_stack.pop()


class WhenDirective(Directive):
    """Implementation of the ``py:when`` directive for nesting in a parent with
    the ``py:choose`` directive.
    
    See the documentation of the `ChooseDirective` for usage.
    """
    # __slots__ = ['filename']
    tagname = 'when'
    include_tail = True

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(WhenDirective, self)._init()
        if self.tag == WhenDirective.qname:
            value = self.attrib.get('test')
        else:
            value = self.attrib.get(WhenDirective.qname)
        if value is None:
            self.when_expr = None
        else:
            value = value.strip()
            self.when_expr = self._parse_expr(value, None, 1, 1)

    def generate(self, template, ctxt, **vars):
        info = ctxt._choice_stack and ctxt._choice_stack[-1]
        if not info:
            raise TemplateRuntimeError('"when" directives can only be used '
                                       'inside a "choose" directive',
                                       "<string>")
        if info[0]:
            return []
        if not self.when_expr and not info[1]:
            raise TemplateRuntimeError('either "choose" or "when" directive '
                                       'must have a test expression',
                                       "<string>")
        if info[1]:
            value = info[2]
            if self.when_expr:
                matched = value == _eval_expr(self.when_expr, ctxt, vars)
            else:
                matched = bool(value)
        else:
            matched = bool(_eval_expr(self.when_expr, ctxt, vars))
        info[0] = matched
        if not matched:
            return None
        return tree_base.flatten_generate(WhenDirective.undirectify(self), template, ctxt, vars)


class OtherwiseDirective(Directive):
    """Implementation of the ``py:otherwise`` directive for nesting in a parent
    with the ``py:choose`` directive.
    
    See the documentation of `ChooseDirective` for usage.
    """
    # __slots__ = ['filename']
    tagname = 'otherwise'
    include_tail = True

    def generate(self, template, ctxt, **vars):
        info = ctxt._choice_stack and ctxt._choice_stack[-1]
        if not info:
            raise TemplateRuntimeError('an "otherwise" directive can only be '
                                       'used inside a "choose" directive',
                                       "<string>")
        if info[0]:
            return None
        info[0] = True

        return tree_base.flatten_generate(OtherwiseDirective.undirectify(self), template, ctxt, vars)


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
    # __slots__ = ['vars']
    tagname = 'with'

    include_tail = True

    def _init(self):
        """Instantiates this element - caches items that'll be used in generation"""
        super(WithDirective, self)._init()
        self.vars = []
        if self.tag == WithDirective.qname:
            value = self.attrib.get('vars')
        else:
            value = self.attrib.get(WithDirective.qname)
        value = value.strip()
        try:
            ast = _parse(value, 'exec')
            for node in ast.body:
                if not isinstance(node, _ast.Assign):
                    raise TemplateSyntaxError('only assignment allowed in '
                                              'value of the "with" directive',
                                              "<string>", 1, 1)
                self.vars.append(([template_directives._assignment(n) for n in node.targets],
                                  Expression(node.value, "<string>",
                                             1, lookup='strict')))
        except SyntaxError, err:
            err.msg += ' in expression "%s" of "%s" directive' % (value,
                                                                  self.tagname)
            raise TemplateSyntaxError(err, "<string>", 1,
                                      1 + (err.offset or 0))

    def generate(self, template, ctxt, **vars):
        frame = {}
        ctxt.push(frame)
        for targets, expr in self.vars:
            value = _eval_expr(expr, ctxt, vars)
            for assign in targets:
                assign(frame, value)
        yield list(tree_base.flatten_generate(WithDirective.undirectify(self), template, ctxt, vars))
        ctxt.pop()

    def __repr__(self):
        return '<%s>' % (type(self).__name__)

DIRECTIVE_CLASS_LOOKUP = dict([("{%s}%s" % (tree_base.GENSHI_NAMESPACE, directive_tag), locals().get("%sDirective" % directive_tag.title(), directive_cls)) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives])
DIRECTIVE_NAMES = ["{%s}%s" % (tree_base.GENSHI_NAMESPACE, directive_tag) for (directive_tag, directive_cls) in markup.MarkupTemplate.directives]
DIRECTIVE_TAGS = set([directive_tag for directive_tag in DIRECTIVE_NAMES if directive_tag[directive_tag.find("}")+1:] not in ("content", "attrs", "strip")])
DIRECTIVE_ATTRS = set(DIRECTIVE_NAMES)
DIRECTIVE_DERIVATION = {}

# TODO: find a cleaner way to do this
for directive_qname, directive_cls in DIRECTIVE_CLASS_LOOKUP.items():
    setattr(directive_cls, "qname", directive_qname)

