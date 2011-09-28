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
<span height="${'%dpx' % 10*3}">High</span>
</div>"""

source3 = """<div xmlns:py="http://genshi.edgewall.org/">
<span py:for="a in range(5)">Test <i py:content="a"/> is <b py:if="a"> greater than 0</b></span>
</div>"""

source4 = """<div xmlns:py="http://genshi.edgewall.org/">
<span py:for="a in range(5)">Test <i>${a}</i><b py:if="a">Greater than 0</b></span>You
<a py:strip="True">me</a>
<?python
print 'Me'
?>
<py:if test="True"><b>Me</b></py:if>
<span py:for="a in range(5)" py:if="a % 2 == 0">Even <i py:content="a"/><b py:if="a">Greater than 0</b></span>
<span height="${'%dpx' % 10*3}">High</span>
</div>"""

source5 = """<div xmlns:py="http://genshi.edgewall.org/">
<span py:for="a in range(5)">Test <i>${a}</i></span>
</div>"""

source6 = """<div xmlns:py="http://genshi.edgewall.org/">
Z<a py:strip="True">me</a>X<a py:strip="False">you</a>Y
A<?python x = 3 ?>B
<a py:strip="True">me</a>Q
<?python
print 'Me'
?>C
<py:if test="True"><b>Me</b>Y</py:if>Z
</div>"""

source7 = """<div xmlns:py="http://genshi.edgewall.org/">
<a py:strip="True">me</a>
<?python
print 'Me'
?> C

<b>Me</b>
</div>"""

source = source7
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

