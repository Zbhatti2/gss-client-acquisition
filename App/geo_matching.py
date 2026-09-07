"""
Lightweight geography matching for the Data Exchange CSV importers —
GSS's simplified stand-in for TMS's much larger address_parsing.py (a
~20KB fuzzy free-text address parser tuned to several tourism-specific
source files). GSS v1 trades that fuzziness for straightforward
exact/case-insensitive matching against the GLOBAL regions/countries/
states/cities lookups, falling back to free-text columns
(state_province_text/city_text) exactly like the manual address forms do
whenever nothing matches — nothing is ever silently dropped, it just isn't
auto-corrected the way TMS's parser tried to.

If GSS later needs the same free-text-address-splitting sophistication TMS
built up (embedded phone numbers, city-anywhere-in-country fallback,
mismatched-province self-correction, etc.), port address_parsing.py from
the Tourism Management System at that point rather than growing this file
ad hoc.
"""
import re

_PHONE_TAIL_RE = re.compile(
    r"(?:[,\s]+(?:\+?\d[\d().\- ]{6,}\d))+\s*$"
)
_PHONE_SPLIT_RE = re.compile(r"\+?\d[\d().\- ]{6,}\d")


def match_country(db, label):
    """Exact, case-insensitive match against countries.label or .code."""
    label = (label or "").strip()
    if not label:
        return None
    return db.execute(
        "SELECT * FROM countries WHERE (lower(label) = lower(?) OR lower(code) = lower(?)) AND is_active = 1",
        (label, label),
    ).fetchone()


def match_state(db, country_id, label):
    """Exact, case-insensitive match against states.label or .code, scoped
    to the given country (states.country_id is NOT NULL, so no country
    means no match)."""
    label = (label or "").strip()
    if not label or not country_id:
        return None
    return db.execute(
        "SELECT * FROM states WHERE country_id = ? AND (lower(label) = lower(?) OR lower(code) = lower(?)) AND is_active = 1",
        (country_id, label, label),
    ).fetchone()


def match_city(db, state_id, label):
    """Exact, case-insensitive match against cities.label, scoped to the
    given province/state."""
    label = (label or "").strip()
    if not label or not state_id:
        return None
    return db.execute(
        "SELECT * FROM cities WHERE state_id = ? AND lower(label) = lower(?) AND is_active = 1",
        (state_id, label),
    ).fetchone()


def extract_trailing_phones(text):
    """Pulls one or more phone-number-looking fragments off the END of a
    free-text address string (e.g. some source directories run a phone
    number straight into the Address column with no column of its own —
    "..., Columbus, Ohio 43210 United States of America,  (419) 535-6794").
    Returns (address_without_phones, [phone strings]) — an address with no
    trailing phone-like text is returned unchanged with an empty list."""
    text = (text or "").strip()
    if not text:
        return text, []
    m = _PHONE_TAIL_RE.search(text)
    if not m:
        return text, []
    tail = m.group(0)
    phones = [p.strip() for p in _PHONE_SPLIT_RE.findall(tail) if p.strip()]
    remaining = text[: m.start()].rstrip(" ,")
    return remaining, phones


def parse_free_text_address(db, text):
    """Best-effort split of one free-text "Street, City, Province, Country"
    style address column into its geography components, matched against
    the GLOBAL lookups (see match_country/match_state/match_city above).

    Approach: split on commas, try the LAST segment as Country, the
    second-to-last as Province/State (scoped to whatever country matched),
    the third-to-last as City (scoped to whatever province matched), and
    treat everything before that as Street. A segment that doesn't match
    an existing lookup row falls back to the free-text
    state_province_text/city_text columns rather than being dropped;
    Country has no free-text fallback column on the schema, so an
    unmatched country segment is folded back into the street text.

    This is intentionally simpler than a real address parser — it assumes
    a conventional "most specific to least specific, comma-separated"
    layout, which is the common shape of the source directories this
    importer targets. A postal code embedded in the same segment as the
    province/country (e.g. "Ohio 43210") is left in that segment's text
    for the province/country match attempt (which only compares against a
    label/code, so extra trailing digits simply won't match — the postal
    code the caller cares about isn't parsed out from a free-text address
    without a dedicated Postal Code column here, unlike the structured
    importer path in TMS)."""
    result = {
        "street": "", "region_id": None,
        "country_id": None, "country_text": "",
        "state_id": None, "state_text": "",
        "city_id": None, "city_text": "",
        "postal_code": "",
    }
    text = (text or "").strip()
    if not text:
        return result

    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return result

    remaining = list(parts)

    country_row = None
    if remaining:
        country_row = match_country(db, remaining[-1])
        if country_row:
            remaining.pop()
        else:
            result["country_text"] = remaining[-1]

    if country_row:
        result["country_id"] = country_row["country_id"]
        result["region_id"] = country_row["region_id"]
        result["country_text"] = country_row["label"]

    state_row = None
    if remaining and result["country_id"]:
        state_row = match_state(db, result["country_id"], remaining[-1])
        if state_row:
            remaining.pop()
            result["state_id"] = state_row["state_id"]
        else:
            result["state_text"] = remaining[-1]
            remaining.pop()
    elif remaining and not result["country_id"]:
        # No country matched, so there's nothing to scope a Province/City
        # match against — treat the next segment as free-text province and
        # move on, rather than guessing.
        result["state_text"] = remaining[-1]
        remaining.pop()

    city_row = None
    if remaining and result["state_id"]:
        city_row = match_city(db, result["state_id"], remaining[-1])
        if city_row:
            remaining.pop()
            result["city_id"] = city_row["city_id"]
        else:
            result["city_text"] = remaining[-1]
            remaining.pop()
    elif remaining:
        result["city_text"] = remaining[-1]
        remaining.pop()

    result["street"] = ", ".join(remaining)
    return result
