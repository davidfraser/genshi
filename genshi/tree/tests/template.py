# -*- coding: utf-8 -*-

from genshi.tree import template
from genshi.template import markup
from lxml import etree

# t = template.TreeTemplate("""<div xmlns:py="http://genshi.edgewall.org/">
#           <span py:if="True">Text</span></div>""")
source1 = """<div xmlns:py="http://genshi.edgewall.org/">
<span py:for="a in range(5)">Test <b py:content="a"/></span>
<a py:strip="True">me</a>
<py:if test="True"><b>Me</b></py:if>
<span py:for="a in range(5)" py:if="a % 2 == 0">Even <b py:content="a"></b></span>
</div>"""

source2 = """<div xmlns:py="http://genshi.edgewall.org/">
<span py:for="a in range(5)">Test <i>${a}</i><b py:if="a">Greater than 0</b></span>
<a py:strip="True">me</a>
<py:if test="True"><b>Me</b></py:if>
<span py:for="a in range(5)" py:if="a % 2 == 0">Even <i py:content="a"/><b py:if="a">Greater than 0</b></span>
</div>"""

source3 = """<div xmlns:py="http://genshi.edgewall.org/">
<span py:for="a in range(5)">Test <i py:content="a"/> is <b py:if="a"> greater than 0</b></span>
</div>"""

source = source2
print "TEMPLATE:"
print source
print
print "STANDARD GENSHI:"
print markup.MarkupTemplate(source).generate().render()
print
t = template.TreeTemplate(source)
print "TREE TEMPLATE:"
print etree.tostring(t._stream)
print
print "TREE GENSHI:"
g = t.generate()
print g.render()

