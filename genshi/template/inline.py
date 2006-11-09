# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://genshi.edgewall.org/wiki/License.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://genshi.edgewall.org/log/.

import compiler
import imp

from genshi.core import Attrs, Stream, _ensure, START, END, TEXT
from genshi.template.core import EXPR, SUB
from genshi.template.directives import *


class CodeWriter(object):

    def __init__(self):
        self.indent = 0

    def __call__(self, line='', *args):
        if not line:
            return ''
        if args:
            line %= args
        return ' ' * self.indent + line

    def shift(self):
        self.indent += 4

    def unshift(self):
        self.indent -= 4


def _expand(obj, pos):
    if obj is not None:
        # First check for a string, otherwise the iterable test below
        # succeeds, and the string will be chopped up into individual
        # characters
        if isinstance(obj, basestring):
            yield TEXT, obj, pos
        elif hasattr(obj, '__iter__'):
            for event in _ensure(obj):
                yield event
        else:
            yield TEXT, unicode(obj), pos

def _expand_text(obj):
    if obj is not None:
        # First check for a string, otherwise the iterable test below
        # succeeds, and the string will be chopped up into individual
        # characters
        if isinstance(obj, basestring):
            yield obj
        elif hasattr(obj, '__iter__'):
            for event in _ensure(obj):
                if event[0] is TEXT:
                    yield event[1]
        else:
            yield unicode(obj)

def _assign(ast):
    buf = []
    def _build(node, indices):
        if isinstance(node, (compiler.ast.AssTuple, compiler.ast.Tuple)):
            for idx, child in enumerate(node.nodes):
                _build(child, indices + (idx,))
        elif isinstance(node, (compiler.ast.AssName, compiler.ast.Name)):
            buf.append('"%s": v%s' % (node.name, ''.join(['[%s]' % i for i in indices])))
    _build(ast, ())
    return '{%s}' % ', '.join(buf)

def inline(template):
    w = CodeWriter()

    yield w('from genshi.core import Attrs, QName')
    yield w('from genshi.core import START, START_NS, END, END_NS, DOCTYPE, TEXT')
    yield w('from genshi.path import Path')
    yield w('from genshi.template.core import Template')
    yield w('from genshi.template.eval import Expression')
    yield w('from genshi.template.inline import _expand, _expand_text')
    yield w('')

    yield '# predeclare qnames, attributes, and expressions'
    p_attrs, p_qnames, p_exprs = {}, {}, {}
    ai, qi, ei, pi = [0], [0], [0], [0]
    def _predecl(stream):
        for kind, data, pos in stream:

            if kind is START:
                tagname, attrs = data
                if tagname not in p_qnames:
                    qi[0] += 1
                    yield w('Q%d = %r', qi[0], tagname)
                    p_qnames[tagname] = qi[0]

                sattrs = Attrs()
                for name, substream in attrs:
                    if isinstance(substream, basestring):
                        sattrs.set(name, substream)
                    else:
                        for subkind, subdata, subpos in substream:
                            if subkind is EXPR:
                                if subdata.source not in p_exprs:
                                    ei[0] += 1
                                    yield w('E%d = %r', ei[0], subdata)
                                    p_exprs[subdata.source] = ei[0]

                if tuple(sattrs) not in p_attrs:
                    ai[0] += 1
                    yield w('A%d = %r', ai[0], sattrs)
                    p_attrs[tuple(sattrs)] = ai[0]

            elif kind is EXPR:
                if data.source not in p_exprs:
                    ei[0] += 1
                    yield w('E%d = %r', ei[0], data)
                    p_exprs[data.source] = ei[0]

            elif kind is SUB:
                directives, substream = data
                for directive in directives:
                    if directive.expr:
                        if directive.expr.source not in p_exprs:
                            ei[0] += 1
                            yield w('E%d = %r', ei[0], directive.expr)
                            p_exprs[directive.expr.source] = ei[0]
                    elif hasattr(directive, 'vars'):
                        for _, expr in directive.vars:
                            if expr.source not in p_exprs:
                                ei[0] += 1
                                yield w('E%d = %r', ei[0], expr)
                                p_exprs[expr.source] = ei[0]
                    elif hasattr(directive, 'path') and directive.path:
                        yield w('P%d = %r', pi[0], directive.path)
                for line in _predecl(substream):
                    yield line

    lines = list(_predecl(template.stream))
    lines.sort()
    for line in lines:
        yield line
    yield w('')

    # Recursively apply directives
    def _apply(directives, stream):
        if not directives:
            for line in _generate(stream):
                yield line
            return

        directive = directives[0]
        directives = directives[1:]

        yield w()
        yield w('# Applying %r', directive)

        if isinstance(directive, ContentDirective):
            ei[0] += 1
            yield w('for e in _expand(E%d.evaluate(ctxt), %r):', p_exprs[directive.expr.source],
                    (None, -1, -1))
            w.shift()
            lines = _apply(directives, stream)
            for line in lines:
                yield line
                break
            yield w('yield e')
            line = lines.next()
            for next in lines:
                line = next
            yield line
            w.unshift()

        elif isinstance(directive, ForDirective):
            ei[0] += 1
            yield w('for v in E%d.evaluate(ctxt):', p_exprs[directive.expr.source])
            w.shift()
            yield w('ctxt.push(%s)', _assign(directive.target))
            for line in _apply(directives, stream):
                yield line
            yield w('ctxt.pop()')
            w.unshift()

        elif isinstance(directive, IfDirective):
            ei[0] += 1
            yield w('if E%d.evaluate(ctxt):', p_exprs[directive.expr.source])
            w.shift()
            for line in _apply(directives, stream):
                yield line
            w.unshift()

        elif isinstance(directive, ReplaceDirective):
            ei[0] += 1
            yield w('for e in _expand(E%d.evaluate(ctxt), %r): yield e',
                    p_exprs[directive.expr.source],
                    (None, -1, -1))

        elif isinstance(directive, WithDirective):
            for targets, expr in directive.vars:
                ei[0] += 1
                yield w('v = E%d.evaluate(ctxt)', p_exprs[directive.expr.source])
                for node, _ in targets:
                    yield w('ctxt.push(%s)', _assign(node))
            for line in _apply(directives, stream):
                yield line
            yield w('ctxt.pop()')

        elif isinstance(directive, StripDirective):
            if directive.expr:
                yield w('if E%d.evaluate(ctxt):', p_exprs[directive.expr.source])
                w.shift()
                lines = _apply(directives, stream)
                previous = lines.next()
                for line in lines:
                    yield previous
                    previous = line
                w.unshift()
                yield w('else:')
                w.shift()
                for line in _apply(directives, stream):
                    yield line
                w.unshift()
            else: # always strip
                lines = _apply(directives, stream)
                previous = lines.next()
                for line in lines:
                    yield previous
                    previous = line

        else:
            raise NotImplementedError

        yield w('')

    # Generate code for the given template stream
    def _generate(stream):
        for kind, data, pos in stream:

            if kind is EXPR:
                yield w('for e in _expand(E%d.evaluate(ctxt), %r): yield e',
                        p_exprs[data.source], pos)

            elif kind is START:
                tagname, attrs = data
                qn = p_qnames[tagname]

                sattrs = Attrs()
                for name, substream in attrs:
                    if isinstance(substream, basestring):
                        sattrs.set(name, substream)
                at = p_attrs[tuple(sattrs)]
                if filter(None, [not isinstance(v, basestring) for n,v in attrs]):
                    yield w('a = Attrs(A%d)', at)
                    for name, value in attrs:
                        if not isinstance(value, basestring):
                            parts = []
                            for subkind, subdata, subpos in value:
                                if subkind is EXPR:
                                    parts.append('list(_expand_text(E%d.evaluate(ctxt)))' %
                                                 p_exprs[subdata.source])
                                elif subkind is TEXT:
                                    parts.append('[%r]' % subdata)
                            yield w('v = [v for v in %s if v is not None]',
                                    ' + '.join(parts))
                            yield w('if v:')
                            w.shift()
                            yield w('a.append((%r, "".join(v)))', name)
                            w.unshift()
                    yield w('yield START, (Q%d, a), %r', qn, pos)
                else:
                    yield w('yield START, (Q%d, A%d), %r', qn, at, pos)

            elif kind is END:
                yield w('yield END, Q%d, %r', p_qnames[data], pos)

            elif kind is SUB:
                directives, substream = data
                for line in _apply(directives, substream):
                    yield line

            else:
                yield w('yield %s, %r, %r', kind, data, pos)

    yield w('def generate(ctxt):')
    w.shift()

    ei, pi = [0], [0]
    for line in _generate(template.stream):
        yield line


if __name__ == '__main__':
    import timeit
    from genshi.template import Context, MarkupTemplate

    text = """<!DOCTYPE html
    PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:py="http://genshi.edgewall.org/"
      lang="en">
 <body>
    Hello, $hello!
    <ul py:if="items">
      <li py:for="idx, item in enumerate(items)"
          class="${idx % 2 and 'odd' or 'even'}">
        <span py:content="item + 1">NUM</span>
      </li>
    </ul>
 </body>
</html>"""

    ctxt = Context(hello='world', items=range(10))
    tmpl = MarkupTemplate(text)

    print 'Generated source:'
    for idx, line in enumerate(inline(tmpl)):
        print '%3d  %s' % (idx + 1, line)

    print
    print 'Interpreted template:'
    print tmpl.generate(ctxt)

    print
    print 'Executed module:'
    module = tmpl.compile()
    print Stream(module.generate(ctxt))

    print
    print
    t = timeit.Timer('list(tmpl.generate(ctxt))', '''
from genshi.template import Context, MarkupTemplate
ctxt = Context(hello='world', items=range(10))
tmpl = MarkupTemplate("""%s""")''' % text)
    print 'Interpreted: %.2f msec/pass' % (1000 * t.timeit(number=1000) / 1000)
    print

    t = timeit.Timer('list(module.generate(ctxt))', '''
from genshi.core import Stream
from genshi.template import Context, MarkupTemplate
ctxt = Context(hello='world', items=range(10))
tmpl = MarkupTemplate("""%s""")
module = tmpl.compile()''' % text)
    print 'Compiled: %.2f msec/pass' % (1000 * t.timeit(number=1000) / 1000)
    print
