"""
Small shared helpers used across blueprints/templates.
"""
import os
import re
import subprocess
import sys
from datetime import datetime

from markupsafe import Markup, escape

_URL_RE = re.compile(r'((?:https?://|www\.)[^\s<>"\']+)', re.IGNORECASE)


def _clean(value):
    """Normalize a possibly-missing phone field to a real absent value.

    Treats None, blank/whitespace-only strings, and the literal text "none"
    (any case) all the same way: as absent. Returns a stripped string, or
    None if absent.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    return text


def _format_country_code(country):
    """Normalize a phone country code for display: always a leading '+',
    never a leading '0' — so '01' renders as '+1', and '+1' typed correctly
    is left untouched (idempotent)."""
    if not country:
        return country
    if country.startswith("+"):
        return country
    digits = country.lstrip("0")
    return f"+{digits}" if digits else country


def format_phone(p):
    """Render a contact_phones/organization_phones row as a clean display
    string — no stray "None"/"xNone" when country code, area code, or
    extension are absent (many countries, e.g. Pakistan, don't use area
    codes for mobile numbers, so this is the common case, not the
    exception). Usable as a Jinja filter: {{ p | format_phone }}.
    """
    d = dict(p) if p is not None else {}
    country = _format_country_code(_clean(d.get("country_code")))
    area = _clean(d.get("area_code"))
    number = _clean(d.get("number")) or ""
    ext = _clean(d.get("extension"))

    parts = [part for part in (country, area, number) if part]
    result = " ".join(parts)
    if ext:
        result += f" x{ext}"
    return result


def linkify(text):
    """Render freeform text as safe HTML with any http(s)/www URLs turned
    into clickable links and newlines preserved. The rest of the text is
    HTML-escaped first, so this is safe to mark as |safe in a template.
    Usable as a Jinja filter: {{ item.notes | linkify }}.
    """
    if not text:
        return ""
    escaped = str(escape(text))

    def _replace(m):
        raw = m.group(1)
        trailing = ""
        while raw and raw[-1] in ".,;:!?)]}'\"":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        href = raw if raw.lower().startswith(("http://", "https://")) else f"https://{raw}"
        return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{raw}</a>{trailing}'

    linked = _URL_RE.sub(_replace, escaped)
    return Markup(linked.replace("\n", "<br>"))


def format_date(value):
    """Render a stored 'YYYY-MM-DD' date (the HTML5 date-input format) as
    'Month DD, YYYY' for display — e.g. '1955-05-05' -> 'May 05, 1955'.
    Storage/inputs (forms, CSV import/export) stay ISO; this is display
    only. Falls back to the raw stored value for anything that isn't a
    clean ISO date, and to "" for a missing value. Usable as a Jinja
    filter: {{ contact.date_of_birth | format_date }}.
    """
    text = _clean(value)
    if not text:
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%B %d, %Y")
    except ValueError:
        return text


def orblank(value):
    """A DB NULL becomes '' instead of Jinja printing the literal word
    "None" into an input's value="..." (the classic `{{ x.field if x else
    '' }}` gotcha — that ternary only guards against x itself being
    missing, not against x.field being NULL). Only guards against None
    specifically, so legitimate falsy values like 0 or False still render
    correctly. Usable as a Jinja filter: {{ item.field | orblank }}.
    """
    return "" if value is None else value


def basename(path):
    """Last path segment, splitting on both '/' and '\\' regardless of the
    host OS this process runs on (a Windows path saved by the app can be
    displayed correctly even when Flask itself happens to run elsewhere).
    """
    if not path:
        return ""
    return re.split(r"[\\/]", path)[-1] or path


def open_local_path(path):
    """Open a local file with whatever application the OS has registered
    for its file type — os.startfile on Windows (the target platform for
    this app), with a best-effort fallback for other OSes."""
    if hasattr(os, "startfile"):
        os.startfile(path)  # Windows only
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def pick_file_dialog():
    """Pop a native OS file-picker dialog and return (path, error). Works
    because the Flask process runs locally on the same machine as the
    browser — a web page itself can never see a real local filesystem
    path, only a native dialog invoked server-side can."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None, "The file browser isn't available in this environment — type or paste the path instead."
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(title="Select a file")
        root.destroy()
    except Exception as e:
        return None, f"Couldn't open the file browser ({e}) — type or paste the path instead."
    return (path or None), None
