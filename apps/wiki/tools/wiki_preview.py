#!/usr/bin/env python3
"""Show an article as the console would: the Stick's own text code, on a
desktop.

    tools/wiki_preview.py "Nintendo Entertainment System"
    tools/wiki_preview.py --file reply.json         a saved API reply
    tools/wiki_preview.py --save reply.json "Famicom"

It fetches with urllib and feeds the reply to neswiki.wikitext in chunks of
--chunk bytes, as the Stick's socket would. Headings are shown in bold.
"""

import argparse
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware", "stick"))

from neswiki import wikitext  # noqa: E402
from neswiki.linkrate import COLUMNS  # noqa: E402
from neswiki.wrap import HEADING, Article  # noqa: E402

DEFAULT_QUERY = "Nintendo Entertainment System"
CAPACITY = 256 * 1024 // COLUMNS    # the Stick's buffer: 256 KB of lines


def fetch(query):
    request = urllib.request.Request(
        "https://%s%s" % (wikitext.HOST, wikitext.api_path(query)),
        headers={"User-Agent": wikitext.USER_AGENT, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=20) as reply:
        return reply.read()


def chunks(body, size):
    for start in range(0, len(body), size):
        yield body[start:start + size]


def show(article, out, color):
    for index in range(article.count):
        line = article.line(index)
        text = bytes(char & 0x7F for char in line).decode("ascii").rstrip()
        if line[0] & HEADING and color:
            text = "\033[1m%s\033[0m" % text
        out.write("%5d  %s\n" % (index, text))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("query", nargs="?", default=DEFAULT_QUERY)
    parser.add_argument("--file", help="read a saved API reply instead of fetching")
    parser.add_argument("--save", help="write the API reply to this file")
    parser.add_argument("--chunk", type=int, default=1024, help="bytes per chunk fed")
    parser.add_argument("--summary", action="store_true", help="print only the counts")
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, "rb") as handle:
            body = handle.read()
    else:
        body = fetch(args.query)
    if args.save:
        with open(args.save, "wb") as handle:
            handle.write(body)

    article = Article(CAPACITY)
    if not wikitext.load(chunks(body, args.chunk), article):
        print("no article found")
        return 1
    if not args.summary:
        show(article, sys.stdout, sys.stdout.isatty())
    print("%s: %d bytes of reply, %d lines%s" % (
        article.title.decode("ascii"), len(body), article.count,
        ", cut short" if article.full else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
