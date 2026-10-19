"""CommonMark links, local code-path references and GitHub-style heading IDs.

Only local Git data is consulted: no provider, filesystem or external HTTP access.
Footnote extensions and anchors in non-Markdown/non-HTML files are not validated.
"""
from __future__ import annotations

import html
import posixpath
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from tools.file_hygiene_git import GitTree

ROOTS = ("docs/", "backend/", "frontend/", "tools/", "ops/", "architecture/", "tasks/")
PARSER = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
PATH_CODE = re.compile(r"[^\s`<>*?{}|]+\.(md|py|tsx?|jsx?|mjs|cjs|ps1|json|toml|ya?ml|html|css)$")


@dataclass(frozen=True, order=True)
class Reference:
    url: str
    code_path: bool = False


class HtmlRefs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls: set[Reference] = set()
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        for key in ("href", "src"):
            if attrs.get(key):
                self.urls.add(Reference(attrs[key]))
        for key in ("id", "name"):
            if attrs.get(key):
                self.ids.add(attrs[key])


def _children(tokens):
    for token in tokens:
        yield token
        yield from _children(token.children or [])


def parse(text: str) -> tuple[set[Reference], set[str]]:
    # YAML-style metadata is neither prose nor a Markdown heading.
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            text = text[end + 5:]
    tokens = PARSER.parse(text)
    refs: set[Reference] = set()
    ids: set[str] = set()
    raw_html = HtmlRefs()
    for token in _children(tokens):
        if token.type in {"link_open", "image"}:
            value = token.attrGet("href" if token.type == "link_open" else "src")
            if value:
                refs.add(Reference(value))
        elif token.type == "code_inline" and PATH_CODE.fullmatch(token.content):
            value = token.content.replace("\\", "/")
            # Standalone *.md and explicit repository paths are actionable references.
            if value.endswith(".md") or value.startswith(ROOTS):
                refs.add(Reference(value, True))
        elif token.type in {"html_inline", "html_block"}:
            raw_html.feed(token.content)
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or index + 1 >= len(tokens):
            continue
        title = "".join(child.content for child in _children(tokens[index + 1].children or [])
                        if child.type in {"text", "code_inline"})
        title = html.unescape(title).lower()
        slug = "".join(c for c in title if c in " -_" or unicodedata.category(c)[0] in "LMN")
        slug = slug.replace(" ", "-")
        candidate, suffix = slug, 0
        while candidate in ids:
            suffix += 1
            candidate = f"{slug}-{suffix}"
        ids.add(candidate)
    return refs | raw_html.urls, ids | raw_html.ids


def active_document(path: str) -> bool:
    parts = path.split("/")
    return (path.endswith(".md") and not path.startswith(("archive/", "docs/generated/"))
            and path != "backend/SYMBOL_MAP.md"
            and not any(p in {"node_modules", ".venv", ".runtime", ".git"} for p in parts))


def resolve(path: str, reference: Reference, tree: GitTree) -> tuple[str, str] | None:
    url = reference.url
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        return None
    pathname, anchor = unquote(parsed.path), unquote(parsed.fragment)
    if reference.code_path:
        if pathname.startswith(ROOTS) or ("/" not in pathname and pathname in tree.files):
            target = pathname
        else:
            target = posixpath.join(posixpath.dirname(path), pathname)
    elif not pathname:
        target = path
    elif pathname.startswith("/"):
        # /feed and /api/... describe product routes, not checkout paths.
        if not re.search(r"\.[a-zA-Z0-9]+$", pathname):
            return None
        target = pathname.lstrip("/")
    else:
        target = posixpath.join(posixpath.dirname(path), pathname)
    return posixpath.normpath(target), anchor


def problems(tree: GitTree) -> set[tuple[str, str, str, str]]:
    """Compare resolved problems, not only the textual URL, across two Git trees."""
    parsed: dict[str, tuple[set[Reference], set[str]]] = {}

    def document(path):
        if path not in parsed:
            parsed[path] = parse(tree.read(path).decode("utf-8"))
        return parsed[path]

    out: set[tuple[str, str, str, str]] = set()
    for path in sorted(p for p in tree.files if active_document(p)):
        refs, _ = document(path)
        for ref in sorted(refs):
            target = resolve(path, ref, tree)
            if target is None:
                continue
            dest, anchor = target
            if dest.startswith("../") or dest == ".." or not tree.exists(dest):
                out.add((path, ref.url, dest, "BROKEN_LOCAL_REFERENCE"))
            elif anchor and dest.endswith((".md", ".html")) and dest in tree.files:
                ids = document(dest)[1]
                if anchor not in ids and not (anchor.startswith("user-content-") and anchor[13:] in ids):
                    out.add((path, ref.url, dest, "BROKEN_LOCAL_ANCHOR"))
    return out
