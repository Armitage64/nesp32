#!/usr/bin/env python3
"""Show an article as the console would: the Stick's own text code, on a
desktop.

    tools/wiki_preview.py "Nintendo Entertainment System"
    tools/wiki_preview.py --file reply.json         a saved API reply
    tools/wiki_preview.py --save reply.json "Famicom"

It fetches with urllib and feeds the reply to the Stick's extractor and
wrapper (nesp32's, through stick.py) in chunks of --chunk bytes, as the
Stick's connection would. Headings are shown in bold.
"""

import argparse
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stick import COLUMNS, SOURCE, nesp  # noqa: E402

DEFAULT_QUERY = "Nintendo Entertainment System"
CAPACITY = 256 * 1024 // COLUMNS    # the Stick's room for an article: 256 KB of lines
# Wikimedia asks every client to say what it is.
USER_AGENT = "NESpedia/0.2 (a Wikipedia reader for the NES; wiki_preview.py)"


def fetch(query):
    request = urllib.request.Request(
        nesp.wiki_url(query),
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=20) as reply:
        return reply.read()


def lay_out(body, chunk):
    """(title, lines) of the article in an API reply, or (None, []) if it
    holds none. A line is COLUMNS tile numbers."""
    extract = nesp.Extract()
    wrap = nesp.Wrap(COLUMNS)
    titled = False
    taken = 0
    for start in range(0, len(body), chunk):
        extract.feed(body[start:start + chunk])
        if not titled and extract.title is not None:
            wrap.title(extract.title)
            titled = True
        text = extract.text
        wrap.put(text[taken:])
        taken = len(text)
        if extract.done:
            break
    if not extract.found:
        return None, []
    wrap.close()
    return extract.title or b"", wrap.lines + [line.ljust(COLUMNS) for line in SOURCE]


def show(lines, out, color):
    for index, line in enumerate(lines):
        text, heading = nesp.text_of(line)
        text = text.decode("ascii")
        if heading and color:
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

    title, lines = lay_out(body, args.chunk)
    if title is None:
        print("no article found")
        return 1
    if not args.summary:
        show(lines, sys.stdout, sys.stdout.isatty())
    print("%s: %d bytes of reply, %d lines%s" % (
        title.decode("ascii"), len(body), len(lines),
        ", more than the Stick has room for" if len(lines) > CAPACITY else ""),
        file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
