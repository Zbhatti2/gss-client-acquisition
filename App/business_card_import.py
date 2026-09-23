"""
AI-powered extraction of Organization + Contact info from a photo of a
business card (front, and optionally back), using Claude's vision
capability via the Anthropic API.

This mirrors the Real Estate Agent reference app's ai_import.py pattern
(same normalize -> single vision call -> strict JSON schema -> tolerant
parse approach), adapted to a two-sided card and to GSS's Organization/
Contact data model instead of a flat listing/broker shape.

Requires an API key: set the ANTHROPIC_API_KEY environment variable before
running the app. Get a key at https://console.anthropic.com

The `anthropic` package is only imported when this feature is actually
used, so the rest of the app works fine even if it isn't installed/
configured yet -- same convention as ai_import.py.
"""
import base64
import io
import json
import os

EXTRACTION_MODEL = os.environ.get("CLAUDE_IMPORT_MODEL", "claude-sonnet-5")

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# The phone "label" the model reads off the card (e.g. "Cell", "O:", "Fax")
# gets mapped to one of these normalized buckets in code (see
# _classify_phone_label below) -- kept here so the extraction prompt and the
# classifier agree on the same vocabulary.
CONTACT_PHONE_TYPES = ["Business", "Home", "Mobile", "WhatsApp", "Business Fax"]
ORG_PHONE_TYPE_LABELS = ["Office", "Mobile", "Fax"]

CARD_SCHEMA = """{
  "organization_name": string or null,
  "organization_phone": string or null,
  "organization_phone_label": string or null,
  "organization_website": string or null,
  "organization_email": string or null,
  "address_street": string or null,
  "address_unit": string or null,
  "address_city": string or null,
  "address_state": string or null,
  "address_postal_code": string or null,
  "address_country": string or null,
  "contacts": [
    {
      "full_name": string or null,
      "job_title": string or null,
      "emails": [string],
      "phones": [ { "number": string, "label": string or null } ]
    }
  ],
  "source_notes": string,
  "uncertain_fields": [string]
}"""

EXTRACTION_PROMPT = f"""You are extracting contact and company information from photo(s) of a business card. You may be given one image (front only) or two images (front and back of the SAME card) -- if two images are given, they are the two faces of one physical card, not two different cards. Combine everything you read from both faces into a single result; do not report the same phone number, email, or address twice just because it appears on both sides.

Read all text carefully, including small print, and note that the "organization" is the company the card is for and the "contact"(s) are the person or people named on it. Most cards name exactly one person, but some (e.g. two partners sharing a card) name more than one -- return one entry per distinct named person in "contacts".

Return ONLY a single raw JSON object (no markdown code fences, no commentary before or after) with exactly these keys:

{CARD_SCHEMA}

Rules:
- "organization_phone" is the company's main/office line if the card shows one distinct from a person's direct or mobile number; if only one phone number appears on the whole card and it's clearly a personal/direct/mobile line, leave organization_phone null and put it under that contact's "phones" instead.
- "organization_phone_label" is whatever label was printed next to organization_phone (e.g. "Office", "Main", "Tel"), or null if there was no label.
- Each phone in a contact's "phones" array should keep the raw label printed next to it (e.g. "Cell", "C:", "O:", "Direct", "Fax", "WhatsApp") in "label" exactly as it reads on the card -- do not translate or normalize the label yourself, that's done afterward in code. Use null if a number has no label at all.
- "address_street"/"address_unit"/"address_city"/"address_state"/"address_postal_code"/"address_country" describe the one company address printed on the card (most cards have only one). If the card has no address at all, leave all of these null.
- Do not invent a name, phone number, email, address, or website that isn't actually printed on the card.
- "source_notes" should briefly note anything ambiguous, illegible, or missing that would matter for someone reviewing this before saving it -- e.g. "Back of card was blank" or "Company name only visible as a stylized logo, transcribed as read."
- "uncertain_fields" lists the JSON key names (or "contacts[0].phones[1]" style paths for nested fields) of anything you had to infer, guess, or read with low confidence -- not fields that are just genuinely absent from the card.
- If you truly cannot make out a named person anywhere on the card, return "contacts" as an empty array rather than guessing a name.

Return raw JSON only, nothing else. Example shape: {{"organization_name": "...", ..., "contacts": [{{"full_name": "...", "job_title": "...", "emails": [...], "phones": [...]}}], "source_notes": "...", "uncertain_fields": []}}"""


class ExtractionError(Exception):
    pass


def get_client():
    try:
        import anthropic
    except ImportError as e:
        raise ExtractionError(
            "The 'anthropic' package isn't installed. Run: "
            "pip install -r requirements.txt --break-system-packages"
        ) from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ExtractionError(
            "ANTHROPIC_API_KEY is not set. Get a key from console.anthropic.com, "
            "then set it as an environment variable before running the app."
        )
    return anthropic.Anthropic(api_key=api_key)


def _strip_code_fences(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def _normalize_image(image_bytes, mime_type):
    """Runs every image through Pillow before it's sent to Claude -- same
    normalization ai_import.py applies to flyer photos, and for the same
    reasons (corrupted/truncated files, a real format that doesn't match
    the extension, unsupported color modes, oversized phone-camera photos).
    Always returns (jpeg_bytes, "image/jpeg") on success."""
    try:
        from PIL import Image
    except ImportError as e:
        raise ExtractionError(
            "The 'Pillow' package isn't installed. Run: "
            "pip install -r requirements.txt --break-system-packages"
        ) from e

    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im.load()  # forces a full decode now, so corruption is caught here
            if im.mode != "RGB":
                im = im.convert("RGB")
            max_dim = 1568  # Anthropic's recommended max on the long edge
            if max(im.size) > max_dim:
                im.thumbnail((max_dim, max_dim), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=90)
            return buf.getvalue(), "image/jpeg"
    except Exception as e:
        raise ExtractionError(
            f"Couldn't read that as an image -- it may be corrupted, or not "
            f"actually a jpg/png/gif/webp despite its filename. ({e})"
        ) from e


def _classify_contact_phone_label(label):
    """Maps whatever raw label the model read off the card (e.g. "Cell",
    "C:", "Office", "Fax", "WhatsApp") onto contacts.phone_type's fixed
    CHECK-constrained vocabulary. Business cards are a business context, so
    an unlabeled or unrecognized number defaults to "Business" rather than
    "Home" -- "Home" is realistically never printed on a business card."""
    text = (label or "").strip().lower()
    if not text:
        return "Business"
    if "fax" in text:
        return "Business Fax"
    if "whatsapp" in text or "wa" == text:
        return "WhatsApp"
    if any(k in text for k in ("cell", "mobile", "m:", "m.")) or text in ("c", "c:"):
        return "Mobile"
    if "home" in text:
        return "Home"
    return "Business"


def _classify_org_phone_label(label):
    """Same idea as _classify_contact_phone_label, but for
    organization_phone_types (Office/Mobile/Fax, seeded labels -- see
    seed_data.py). Defaults to "Office" for an unlabeled company line."""
    text = (label or "").strip().lower()
    if not text:
        return "Office"
    if "fax" in text:
        return "Fax"
    if "mobile" in text or "cell" in text:
        return "Mobile"
    return "Office"


def extract_business_card(front_bytes, front_mime, back_bytes=None, back_mime=None):
    """Returns (parsed, usage): parsed is the card dict (organization_*
    fields, "contacts" list, source_notes, uncertain_fields); usage is
    {"model_code": EXTRACTION_MODEL, "tokens_input": int, "tokens_output": int}
    straight from the API response, for the caller to pass to
    agents.log_agent_usage() so agent_usage_log can compute the real cost
    (see agent_billing.py). Raises ExtractionError on any failure."""
    front_bytes, front_mime = _normalize_image(front_bytes, front_mime)
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": front_mime, "data": base64.b64encode(front_bytes).decode("utf-8")}},
    ]
    if back_bytes:
        back_bytes, back_mime = _normalize_image(back_bytes, back_mime)
        content.append(
            {"type": "image", "source": {"type": "base64", "media_type": back_mime, "data": base64.b64encode(back_bytes).decode("utf-8")}}
        )
    content.append({"type": "text", "text": EXTRACTION_PROMPT})

    client = get_client()
    try:
        message = client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:
        raise ExtractionError(f"Claude API request failed: {e}") from e

    usage = {
        "model_code": EXTRACTION_MODEL,
        "tokens_input": getattr(message.usage, "input_tokens", None),
        "tokens_output": getattr(message.usage, "output_tokens", None),
    }

    text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    text = _strip_code_fences(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"Couldn't parse Claude's response as JSON. Raw response:\n\n{text}") from e

    if not isinstance(parsed, dict):
        raise ExtractionError(f"Expected a JSON object describing the card, got: {text[:300]}")

    # Tolerate a wrapper key, same convention as ai_import.py's
    # bare-array-or-{"listings": [...]}-wrapper handling.
    if "organization_name" not in parsed and isinstance(parsed.get("card"), dict):
        parsed = parsed["card"]

    parsed.setdefault("contacts", [])
    parsed.setdefault("source_notes", "")
    parsed.setdefault("uncertain_fields", [])
    if not parsed["contacts"]:
        parsed["uncertain_fields"] = list(parsed["uncertain_fields"]) + ["contacts"]
        parsed["source_notes"] = (parsed["source_notes"] + " No named person could be read from this card.").strip()

    return parsed, usage
