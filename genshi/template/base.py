# -*- coding: utf-8 -*-
#
# Copyright (C) 2006-2007 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://genshi.edgewall.org/wiki/License.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://genshi.edgewall.org/log/.

try:
    from collections import deque
except ImportError:
    class deque(list):
        def appendleft(self, x): self.insert(0, x)
        def popleft(self): return self.pop(0)
import os
from StringIO import StringIO

from genshi.core import Attrs, Stream, StreamEventKind, START, TEXT, _ensure

__all__ = ['Context', 'Template', 'TemplateError', 'TemplateRuntimeError',
           'TemplateSyntaxError', 'BadDirectiveError']
__docformat__ = 'restructuredtext en'


class TemplateError(Exception):
    """Base exception class for errors related to template processing."""


class TemplateRuntimeError(TemplateError):
    """Exception raised when an the evualation of a Python expression in a
    template causes an error."""

    def __init__(self, message, filename='<string>', lineno=-1, offset=-1):
        self.msg = message
        if filename != '<string>' or lineno >= 0:
            message = '%s (%s, line %d)' % (self.msg, filename, lineno)
        TemplateError.__init__(self, message)
        self.filename = filename
        self.lineno = lineno
        self.offset = offset


class TemplateSyntaxError(TemplateError):
    """Exception raised when an expression in a template causes a Python syntax
    error."""

    def __init__(self, message, filename='<string>', lineno=-1, offset=-1):
        if isinstance(message, SyntaxError) and message.lineno is not None:
            message = str(message).replace(' (line %d)' % message.lineno, '')
        self.msg = message
        message = '%s (%s, line %d)' % (self.msg, filename, lineno)
        TemplateError.__init__(self, message)
        self.filename = filename
        self.lineno = lineno
        self.offset = offset


class BadDirectiveError(TemplateSyntaxError):
    """Exception raised when an unknown directive is encountered when parsing
    a template.
    
    An unknown directive is any attribute using the namespace for directives,
    with a local name that doesn't match any registered directive.
    """

    def __init__(self, name, filename='<string>', lineno=-1):
        message = 'bad directive "%s"' % name
        TemplateSyntaxError.__init__(self, message, filename, lineno)


class Context(object):
    """Container for template input data.
    
    A context provides a stack of scopes (represented by dictionaries).
    
    Template directives such as loops can push a new scope on the stack with
    data that should only be available inside the loop. When the loop
    terminates, that scope can get popped off the stack again.
    
    >>> ctxt = Context(one='foo', other=1)
    >>> ctxt.get('one')
    'foo'
    >>> ctxt.get('other')
    1
    >>> ctxt.push(dict(one='frost'))
    >>> ctxt.get('one')
    'frost'
    >>> ctxt.get('other')
    1
    >>> ctxt.pop()
    {'one': 'frost'}
    >>> ctxt.get('one')
    'foo'
    """

    def __init__(self, **data):
        self.frames = deque([data])
        self.pop = self.frames.popleft
        self.push = self.frames.appendleft
        self._match_templates = []

    def __repr__(self):
        return repr(list(self.frames))

    def __contains__(self, key):
        """Return whether a variable exists in any of the scopes."""
        return self._find(key)[1] is not None

    def __delitem__(self, key):
        """Set a variable in the current scope."""
        for frame in self.frames:
            if key in frame:
                del frame[key]

    def __getitem__(self, key):
        """Get a variables's value, starting at the current scope and going
        upward.
        
        Raises `KeyError` if the requested variable wasn't found in any scope.
        """
        value, frame = self._find(key)
        if frame is None:
            raise KeyError(key)
        return value

    def __len__(self):
        """Return the number of distinctly named variables in the context."""
        return len(self.items())

    def __setitem__(self, key, value):
        """Set a variable in the current scope."""
        self.frames[0][key] = value

    def _find(self, key, default=None):
        """Retrieve a given variable's value and the frame it was found in.

        Intented for internal use by directives.
        """
        for frame in self.frames:
            if key in frame:
                return frame[key], frame
        return default, None

    def get(self, key, default=None):
        """Get a variable's value, starting at the current scope and going
        upward.
        """
        for frame in self.frames:
            if key in frame:
                return frame[key]
        return default

    def keys(self):
        keys = []
        for frame in self.frames:
            keys += [key for key in frame if key not in keys]
        return keys

    def items(self):
        return [(key, self.get(key)) for key in self.keys()]

    def push(self, data):
        """Push a new scope on the stack."""

    def pop(self):
        """Pop the top-most scope from the stack."""


def _apply_directives(stream, ctxt, directives):
    """Apply the given directives to the stream."""
    if directives:
        stream = directives[0](iter(stream), ctxt, directives[1:])
    return stream


class TemplateMeta(type):
    """Meta class for templates."""

    def __new__(cls, name, bases, d):
        if 'directives' in d:
            d['_dir_by_name'] = dict(d['directives'])
            d['_dir_order'] = [directive[1] for directive in d['directives']]

        return type.__new__(cls, name, bases, d)


class Template(object):
    """Abstract template base class.
    
    This class implements most of the template processing model, but does not
    specify the syntax of templates.
    """
    __metaclass__ = TemplateMeta

    EXPR = StreamEventKind('EXPR') # an expression
    SUB = StreamEventKind('SUB') # a "subprogram"

    def __init__(self, source, basedir=None, filename=None, loader=None,
                 encoding=None):
        """Initialize a template from either a string or a file-like object."""
        self.basedir = basedir
        self.filename = filename
        if basedir and filename:
            self.filepath = os.path.join(basedir, filename)
        else:
            self.filepath = filename
        self.loader = loader

        if isinstance(source, basestring):
            source = StringIO(source)
        else:
            source = source
        self.stream = list(self._prepare(self._parse(source, encoding)))
        self.filters = [self._flatten, self._eval]

    def __repr__(self):
        return '<%s "%s">' % (self.__class__.__name__, self.filename)

    def _parse(self, source, encoding):
        """Parse the template.
        
        The parsing stage parses the template and constructs a list of
        directives that will be executed in the render stage. The input is
        split up into literal output (text that does not depend on the context
        data) and directives or expressions.
        """
        raise NotImplementedError

    def _prepare(self, stream):
        """Call the `attach` method of every directive found in the template."""
        for kind, data, pos in stream:
            if kind is SUB:
                directives = []
                substream = data[1]
                for cls, value, namespaces, pos in data[0]:
                    directive, substream = cls.attach(self, substream, value,
                                                      namespaces, pos)
                    if directive:
                        directives.append(directive)
                substream = self._prepare(substream)
                if directives:
                    yield kind, (directives, list(substream)), pos
                else:
                    for event in substream:
                        yield event
            else:
                yield kind, data, pos

    def generate(self, *args, **kwargs):
        """Apply the template to the given context data.
        
        Any keyword arguments are made available to the template as context
        data.
        
        Only one positional argument is accepted: if it is provided, it must be
        an instance of the `Context` class, and keyword arguments are ignored.
        This calling style is used for internal processing.
        
        @return: a markup event stream representing the result of applying
            the template to the context data.
        """
        if args:
            assert len(args) == 1
            ctxt = args[0]
            if ctxt is None:
                ctxt = Context(**kwargs)
            assert isinstance(ctxt, Context)
        else:
            ctxt = Context(**kwargs)

        stream = self.stream
        for filter_ in self.filters:
            stream = filter_(iter(stream), ctxt)
        return Stream(stream)

    def _eval(self, stream, ctxt):
        """Internal stream filter that evaluates any expressions in `START` and
        `TEXT` events.
        """
        filters = (self._flatten, self._eval)

        for kind, data, pos in stream:

            if kind is START and data[1]:
                # Attributes may still contain expressions in start tags at
                # this point, so do some evaluation
                tag, attrs = data
                new_attrs = []
                for name, substream in attrs:
                    if isinstance(substream, basestring):
                        value = substream
                    else:
                        values = []
                        for subkind, subdata, subpos in self._eval(substream,
                                                                   ctxt):
                            if subkind is TEXT:
                                values.append(subdata)
                        value = [x for x in values if x is not None]
                        if not value:
                            continue
                    new_attrs.append((name, u''.join(value)))
                yield kind, (tag, Attrs(new_attrs)), pos

            elif kind is EXPR:
                result = data.evaluate(ctxt)
                if result is not None:
                    # First check for a string, otherwise the iterable test below
                    # succeeds, and the string will be chopped up into individual
                    # characters
                    if isinstance(result, basestring):
                        yield TEXT, result, pos
                    elif hasattr(result, '__iter__'):
                        substream = _ensure(result)
                        for filter_ in filters:
                            substream = filter_(substream, ctxt)
                        for event in substream:
                            yield event
                    else:
                        yield TEXT, unicode(result), pos

            else:
                yield kind, data, pos

    def _flatten(self, stream, ctxt):
        """Internal stream filter that expands `SUB` events in the stream."""
        for event in stream:
            if event[0] is SUB:
                # This event is a list of directives and a list of nested
                # events to which those directives should be applied
                directives, substream = event[1]
                substream = _apply_directives(substream, ctxt, directives)
                for event in self._flatten(substream, ctxt):
                    yield event
            else:
                yield event


EXPR = Template.EXPR
SUB = Template.SUB
