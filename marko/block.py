#! -*- coding: utf-8 -*-
"""
Block level elements
"""
import re
from . import inline

_root_node = None
_element_types = {}

__all__ = (
    'CodeBlock',
    'Heading',
    'List',
    'BlankLine',
    'Quote',
    'FencedCode',
    'ThematicBreak',
    'HTMLBlock',
    'Paragraph'
)


def add_element(element_type, override=False):
    """Add a block element.

    :param element_type: the element type class.
    :param override: whether to replace the element type that bases.
    """
    if not override:
        _element_types[element_type.__name__] = element_type
    else:
        for cls in element_type.__bases__:
            if cls in _element_types.values():
                _element_types[cls.__name__] = element_type
                break
        else:
            _element_types[element_type.__name__] = element_type


def get_elements():
    return sorted(_element_types.items(), key=lambda e: e[1].priority, reverse=True)


class BlockElement(object):

    #: Use to denote the precedence in parsing
    priority = 5

    @classmethod
    def match(self, source):
        """Test if the source matches the element at current position.
        The source should not be consumed in the method unless you have to.

        :param source: the ``Source`` object of the content to be parsed
        """
        raise NotImplementedError()

    @classmethod
    def parse(self, source):
        """Parses the source. This is a proper place to consume the source body and
        return an element or information to build one. The information tuple will be
        passed to ``__init__`` method afterwards. Inline parsing, if any, should also
        be performed here.

        :param source: the ``Source`` object of the content to be parsed
        """
        raise NotImplementedError()


class Document(BlockElement):
    """Document node element."""

    _prefix = ''

    def __init__(self, source):
        self.footnotes = []
        self.link_ref_defs = {}
        global _root_node
        _root_node = self
        inline._root_node = self
        with source.under_state(self):
            self.children = parser.parse(source)
        _root_node = None
        inline._root_node = None


class BlankLine(BlockElement):
    """Blank lines"""

    priority = 5
    pattern = re.compile(r'\n+')

    @classmethod
    def match(cls, source):
        return source.expect_re(cls.pattern)

    @classmethod
    def parse(cls, source):
        source.expect_re(cls.pattern, True)
        return cls()


class Heading(BlockElement):
    """Heading element: (### Hello\n)"""

    priority = 6
    pattern = re.compile(
        r' {0,3}(#{1,6})( [^\n]*?|[^\n\S]*)(?:(?<= )(?<!\\)#+)?[^\n\S]*$\n?',
        flags=re.M
    )

    def __init__(self, match):
        self.level = len(match.group(1))
        self.children = parser.parse_inline(match.group(2).strip())

    @classmethod
    def match(cls, source):
        return source.expect_re(cls.pattern)

    @classmethod
    def parse(cls, source):
        return source.expect_re(cls.pattern, True)


class SetextHeading(BlockElement):
    """Setext heading: (Hello\n===\n)
    It can only be created by Paragraph.parse.
    """

    priority = 1

    def __init__(self, lines):
        self.level = 1 if lines.pop().strip()[0] == '=' else 2
        self.children = ''.join(line.lstrip() for line in lines)


class CodeBlock(BlockElement):
    """Indented code block: (    this is a code block\n)"""

    priority = 9

    def __init__(self, lines):
        self.content = inline._element_types['RawText'](lines)

    @classmethod
    def match(cls, source):
        line = source.next_line()
        if not line:
            return False
        return len(line.expandtabs()) - len(line.expandtabs().lstrip()) >= 4

    @classmethod
    def parse(cls, source):
        lines = [cls.strip_indent(source.next_line(True))]
        while not source.exhausted:
            if cls.match(source):
                lines.append[cls.strip_indent(source.next_line(True))]
                source.anchor()
            elif not source.next_line().strip():
                lines.append(source.next_line(True))
            else:
                source.reset()
                break
        return ''.join(lines).rstrip('\n') + '\n'

    @staticmethod
    def strip_indent(line):
        spaces = 0
        for i, c in enumerate(line):
            if c == ' ':
                spaces += 1
            if spaces >= 4 or c == '\t':
                break
        else:
            return line
        return line[i + 1 :]


class FencedCode(BlockElement):
    """Fenced code block: (```python\nhello\n```\n)"""

    priority = 7
    pattern = re.compile(r'( {,3})(`{3,}|~{3,})[^\n\S]*(\S*)(.*?)$', re.M)
    _parse_info = None

    def __init__(self, match):
        self.lang = match[0]
        self.children = inline._element_types['RawText'](match[1])

    @classmethod
    def match(cls, source):
        m = source.expect_re(cls.pattern)
        if not m:
            return False
        prefix, leading, lang, tail = m.groups()
        if leading[0] in lang or leading[0] in tail:
            return False
        cls._parse_info = prefix, leading, lang
        return True

    @classmethod
    def parse(cls, source):
        source.next_line(True)
        lines = []
        while not source.exhausted:
            line = source.next_line(True)
            m = re.match(r' {,3}(~+|`+)[^\n\S]*$', line, flags=re.M)
            if m and cls._parse_info[1] in m.group(1):
                break

            prefix_len = source.match_prefix(cls._parse_info[0], line)
            if prefix_len >= 0:
                line = line[prefix_len:]
            lines.append(line)
        return cls._parse_info[2], ''.join(lines)


class ThematicBreak(BlockElement):
    """Horizontal rules: (----\n)"""

    priority = 8
    pattern = re.compile(r' {,3}([-_*][^\n\S]*){3,}$\n?', flags=re.M)

    @classmethod
    def match(cls, source):
        m = source.expect_re(cls.pattern)
        if not m:
            return False
        return len(set(re.sub(r'\s+', '', m.group()))) == 1

    @classmethod
    def parse(cls, source):
        source.next_line(True)
        return cls()


class HTMLBlock(BlockElement):
    """HTML blocks, parsed as it is"""

    priority = 5
    _end_cond = None

    def __init__(self, lines):
        self.children = lines

    @classmethod
    def match(cls, source):
        if source.expect_re(r' {,3}<(?:script|pre|style)[>\s](?i)'):
            cls._end_cond = re.compile(r'</(?:script|pre|style)>(?i)')
            return 1
        if source.expect_re(r' {,3}<!--'):
            cls._end_cond = re.compile(r'-->')
            return 2
        if source.expect_re(r' {,3}<\?'):
            cls._end_cond = re.compile(r'\?>')
            return 3
        if source.expect_re(r' {,3}<!'):
            cls._end_cond = re.compile(r'>')
            return 4
        if source.expect_re(r' {,3}<!\[CDATA\['):
            cls._end_cond = re.compile(r'\]\]>')
            return 5
        block_tag = r'(?:%s)' % ('|'.join(inline._tags),)
        if source.expect_re(r' {,3}</?%s(?: +|/?>|$)(?im)' % block_tag):
            cls._end_cond = None
            return 6
        if source.expect_re(
            r' {,3}(<%(tag)s(?:%(attr)s)*[^\n\S]*/?>|</%(tag)s[^\n\S]*>)[^\n\S]*$(?m)'
            % {'tag': inline._tag_name, 'attr': inline._attribute_no_lf}
        ):
            cls._end_cond = None
            return 7

        return False

    @classmethod
    def parse(cls, source):
        lines = [source.next_line(True)]
        while not source.exhausted:
            line = source.next_line()
            lines.append(line)
            if cls._end_cond is not None:
                if cls._end_cond.search(line):
                    source.next_line(True)
                    break
            elif line.strip() == '':
                lines.pop()
                break
            source.next_line(True)
        return ''.join(lines)


class Paragraph(BlockElement):
    """A paragraph element"""

    priority = 1
    pattern = re.compile(r'[^\n]+$\n?', flags=re.M)

    def __init__(self, lines):
        lines = ''.join(line.lstrip() for line in lines)
        if not lines.endswith('\n'):
            lines += '\n'
        self.children = parser.parse_inline(lines)
        self._tight = False

    @classmethod
    def match(cls, source):
        return source.expect_re(cls.pattern) is not None

    @staticmethod
    def is_setext_heading(line):
        return re.match(r' {,3}(=+|-+)[^\n\S]*$', line) is not None

    @classmethod
    def break_paragraph(cls, source, parse_setext=True):
        if (
            source.expect_element('Quote')
            or source.expect_element('Heading')
            or source.expect_element('BlankLine')
            or source.expect_element('FencedCode')
        ):
            return True
        if source.expect_element('List'):
            result = ListItem.parse_leading(source.next_line())
            if (result[1][:-1] == '1' or result[1] in '*-+') and result[3]:
                return True
        html_type = source.expect_element('HTMLBlock')
        if html_type and html_type != 7:
            return True
        if source.expect_element('ThematicBreak'):
            if parse_setext and cls.is_setext_heading(source.next_line()):
                return False
            return True
        return False

    @classmethod
    def parse(cls, source):
        lines = [source.next_line(True)]
        end_parse = False
        while not source.exhausted and not end_parse:
            if cls.break_paragraph(source):
                break
            line = source.next_line()
            # the prefix is matched and not breakers
            if line:
                lines.append(source.next_line(True))
                if cls.is_setext_heading(line):
                    return SetextHeading(lines)
            else:
                # check lazy continuation, store the previous state stack
                states = source._states[:]
                while source.state is not _root_node:
                    source.pop_state()
                    if cls.break_paragraph(source, False):
                        end_parse = True
                        break
                else:
                    lines.append(source.next_line(True))
                source._states = states
        return lines


class Quote(BlockElement):
    """block quote element: (> hello world)"""

    priority = 6
    _prefix = r' {,3}>[^\n\S]?'

    @classmethod
    def match(cls, source):
        return source.expect_re(r' {,3}>')

    @classmethod
    def parse(cls, source):
        state = cls()
        with source.under_state(state):
            state.children = parser.parse(source)
        return state


class List(BlockElement):
    """List block element"""

    priority = 6
    _prefix = ''
    pattern = re.compile(r' {,3}(\d+\.|[*\-+])\s')
    _parse_info = None

    def __init__(self):
        self.bullet, self.ordered, self.start = self._parse_info
        self.tight = True

    @classmethod
    def match(cls, source):
        m = source.expect_re(cls.pattern)
        if not m:
            return False
        bullet, ordered, start = m.group(1), False, 1
        if bullet[:-1].isdigit():
            ordered = True
            start = bullet[:-1]
        cls._parse_info = (bullet, ordered, start)
        return m

    @classmethod
    def parse(cls, source):
        state = cls()
        children = []
        tight = True
        with source.under_state(state):
            while not source.exhausted:
                if ListItem.match(source):
                    el = ListItem.parse(source)
                    if not isinstance(el, BlockElement):
                        el = ListItem(el)
                    children.append(el)
                    source.anchor()
                elif BlankLine.match(source):
                    BlankLine.parse(source)
                    tight = False
                else:
                    source.reset()
                    break
        tight = tight and not any(
            isinstance(e, BlankLine) for item in children for e in item.children
        )
        if tight:
            for item in children:
                for child in item.children:
                    if isinstance(child, Paragraph):
                        child._tight = tight
        state.children = children
        state.tight = tight
        return state


class ListItem(BlockElement):
    """List item element. It can only be created by List.parse"""

    _parse_info = None

    def __init__(self):
        indent, bullet, mid, tail = self._parse_info
        self._prefix = ' ' * indent + re.sub(r'([*.+])', r'\\\1', bullet) + ' ' * mid
        self._second_prefix = ' ' * (len(bullet) + indent + mid)

    @classmethod
    def parse_leading(cls, line):
        line = line.expandtabs()
        stripped_line = line.lstrip()
        indent = len(line) - len(stripped_line)
        temp = stripped_line.split(maxsplit=1)
        bullet = temp[0]
        if len(temp) == 1:
            mid = 1
            tail = ''
        else:
            mid = len(stripped_line) - len(''.join(temp))
            tail = temp[1]
        return indent, bullet, mid, tail

    @classmethod
    def match(cls, source):
        if not source.expect_re(List.pattern):
            return False
        indent, bullet, mid, tail = cls.parse_leading(source.next_line())
        parent = source.state
        if parent.ordered and not bullet[:-1].isdigit():
            return False
        if not parent.ordered and bullet != parent.bullet:
            return False
        cls._parse_info = (indent, bullet, mid, tail)
        return True

    @classmethod
    def parse(cls, source):
        state = cls()
        with source.under_state(state):
            state.children = parser.parse(source)
        return state


# import parsers here to avoid cyclic import
from . import parser  # noqa
for name in __all__:
    add_element(globals()[name])