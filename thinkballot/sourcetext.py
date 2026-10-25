"""Turn an official HTML page into plain text the same way everywhere (fetch script and seed checks),
so text copied from a page can always be found on that page again."""

import html
import re
from html.parser import HTMLParser

BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "dt", "dd"}


class _TextExtractor(HTMLParser):
    """Visible text of an HTML fragment; block tags become line breaks; scripts and styles are skipped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw):
    """Plain text with one paragraph per line and single spaces inside lines."""
    parser = _TextExtractor()
    parser.feed(raw)
    text = html.unescape("".join(parser.parts)).replace(" ", " ")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)
