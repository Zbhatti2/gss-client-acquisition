"""
Module — Help. Serves the in-app contextual help panel: a section/page tree
built from plain Markdown files under App/help_content/, rendered into the
Bootstrap Offcanvas drawer that every form's "?" button opens (see
templates/_help_drawer.html and static/js/help.js).

Content lives as Markdown files in git, not the database. Anyone with repo
access adds/edits a .md file and it's live on the next request — no
migration, no admin screen, no build step. Each form declares a help_id
(e.g. "organizations/new-organization") on its "?" button; the drawer opens
straight to that page with its section expanded in the tree, while the
search box and full tree navigation stay right there for browsing.

Help content is the same for every user of a tenant (and, in practice,
every tenant — it documents the app, not tenant data), so unlike almost
everything else in this app there's no tenant_id filtering here. It's
still behind login_required, same as every other screen, and the .md
files themselves are only ever written by whoever has repo/deploy access
-- not by end users -- so their Markdown is rendered as trusted content
(no sanitization pass), the same trust level as this app's own templates.

Adding a new help page: drop a `<page>.md` file under
help_content/<section>/ with `title` (and optionally `order`, `keywords`)
in a leading `---` front-matter block; it appears in the tree
automatically, sorted by `order` then title, as
"<section-folder-name>/<page-file-name>" (its help_id). Adding a new
section is just a new folder — give it a `_section.json` with
{"title": ..., "order": ...} to control how it's labeled/ordered, or leave
it out and the folder name is title-cased for you.
"""
import json
import re
from pathlib import Path

import markdown as md
from flask import Blueprint, abort, jsonify

from auth.decorators import login_required

help_bp = Blueprint("help", __name__)

# App/help_content/ — sibling of this blueprints/ package, not the instance
# folder, since this ships with the app rather than being per-tenant data.
CONTENT_DIR = Path(__file__).resolve().parent.parent / "help_content"

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n?(.*)$", re.DOTALL)


def _parse_front_matter(text):
    """Split a help page's leading `---`-delimited front matter from its
    Markdown body. Front matter is flat `key: value` lines, with
    `key: [a, b, c]` for the one list-valued field (keywords) — hand-rolled
    rather than pulling in PyYAML, since nothing here is ever nested."""
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            value = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        else:
            value = value.strip("'\"")
        meta[key] = value
    return meta, m.group(2)


def _humanize(slug):
    return slug.replace("-", " ").replace("_", " ").strip().title()


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_tree():
    """Walk help_content/ and build the section -> pages tree that drives
    both the drawer's sidebar and /help/page/<help_id> lookups. Re-walked
    on every call rather than cached at import time, so an edited .md file
    is live on the next request with no app restart — this is a few dozen
    small text files, not a hot path worth caching."""
    sections = []
    if not CONTENT_DIR.exists():
        return sections
    for section_dir in CONTENT_DIR.iterdir():
        if not section_dir.is_dir():
            continue
        meta_path = section_dir / "_section.json"
        section_meta = {}
        if meta_path.exists():
            try:
                section_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except ValueError:
                section_meta = {}
        pages = []
        for md_path in section_dir.glob("*.md"):
            text = md_path.read_text(encoding="utf-8")
            page_meta, _ = _parse_front_matter(text)
            pages.append({
                "help_id": f"{section_dir.name}/{md_path.stem}",
                "title": page_meta.get("title") or _humanize(md_path.stem),
                "order": _safe_int(page_meta.get("order"), 999),
                "keywords": page_meta.get("keywords") or [],
            })
        if not pages:
            continue
        pages.sort(key=lambda p: (p["order"], p["title"]))
        sections.append({
            "key": section_dir.name,
            "title": section_meta.get("title") or _humanize(section_dir.name),
            "order": _safe_int(section_meta.get("order"), 999),
            "pages": pages,
        })
    sections.sort(key=lambda s: (s["order"], s["title"]))
    return sections


def _resolve_md_path(help_id):
    """help_id -> its .md file, refusing anything that would resolve
    outside help_content/ (help_id comes from the URL, so it's untrusted
    even though the files it ultimately points at are not)."""
    if not help_id or "/" not in help_id:
        return None
    section_key, _, page_key = help_id.partition("/")
    if not section_key or not page_key or "/" in page_key:
        return None
    candidate = (CONTENT_DIR / section_key / f"{page_key}.md")
    try:
        resolved = candidate.resolve()
        resolved.relative_to(CONTENT_DIR.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


@help_bp.route("/tree")
@login_required
def tree():
    """The full section -> pages tree, fetched once by the drawer and
    cached client-side for the rest of the page's lifetime."""
    return jsonify({"sections": _load_tree()})


@help_bp.route("/page/<path:help_id>")
@login_required
def page(help_id):
    """One rendered help page, plus enough about its place in the tree
    (section key/title) for the drawer to expand the right branch and
    show a breadcrumb without re-deriving it from the full tree."""
    md_path = _resolve_md_path(help_id)
    if md_path is None:
        abort(404)
    text = md_path.read_text(encoding="utf-8")
    meta, body = _parse_front_matter(text)
    html = md.markdown(body, extensions=["fenced_code", "tables", "sane_lists", "toc"])

    section_key = help_id.split("/", 1)[0]
    sections = _load_tree()
    section_title = next((s["title"] for s in sections if s["key"] == section_key), _humanize(section_key))

    return jsonify({
        "help_id": help_id,
        "title": meta.get("title") or _humanize(md_path.stem),
        "section_key": section_key,
        "section_title": section_title,
        "html": html,
    })
