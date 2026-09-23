"""
AI-powered extraction of Organization ad/marketing-listing info from a
photo of an advertisement, using Claude's vision capability via the
Anthropic API.

This is a direct port of the Real Estate Agent reference app's ai_import.py
(same normalize -> single vision call -> strict JSON schema -> tolerant
parse structure), generalized from real-estate flyers to any ad for an
Organization: a magazine ad, a "Help Wanted" clipping, a social-media post
screenshot, a classified, an online ad screenshot. Unlike a real-estate
flyer, an ad image here is always for the ONE Organization whose page the
upload happened from -- see blueprints/organizations.py -- so there's no
broker/company-identification step; extraction only needs the ad's own
content.

Requires an API key: set the ANTHROPIC_API_KEY environment variable (App/
.env is loaded automatically at startup -- see app.py). Get a key at
https://console.anthropic.com

The `anthropic` package is only imported when this feature is actually
used, so the rest of the app works fine even if it isn't installed/
configured yet -- same convention as ai_import.py / business_card_import.py.
"""
import base64
import io
import json
import os
import zipfile

EXTRACTION_MODEL = os.environ.get("CLAUDE_IMPORT_MODEL", "claude-sonnet-5")

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Extension -> mime type, used when pulling images out of an uploaded zip
# (zip entries don't carry a mime type of their own) -- identical to
# ai_import.py's ZIP_IMAGE_EXTENSIONS.
ZIP_IMAGE_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

AD_TYPES = ["Print", "Online", "Social Media", "Classified", "Direct Mail", "Broadcast", "Other"]

AD_SCHEMA = """{
  "headline": string or null,
  "ad_type": "Print" or "Online" or "Social Media" or "Classified" or "Direct Mail" or "Broadcast" or "Other",
  "publication": string or null,
  "date_published": string or null,
  "description": string or null,
  "offer_details": string or null,
  "price": number or null,
  "price_label": string or null,
  "contact_name": string or null,
  "contact_phone": string or null,
  "contact_email": string or null,
  "source_notes": string,
  "uncertain_fields": [string]
}"""

EXTRACTION_PROMPT = f"""You are extracting information from a photo of an advertisement or marketing material for a business -- a magazine or newspaper ad, a "Help Wanted" clipping, a classified ad, a flyer, a social-media post screenshot, or a screenshot of an online ad or web page.

IMPORTANT: a single image can contain more than one distinct ad (e.g. a page of classifieds, or a social feed screenshot with several posts visible). Identify each DISTINCT ad separately -- do not merge them into one.

Read all text in the image carefully, including small print. Return ONLY a single raw JSON object (no markdown code fences, no commentary before or after) with exactly one key, "ads", whose value is a JSON array. If the image shows only one ad, return an array with exactly one element. Each array element must have exactly these keys:

{AD_SCHEMA}

Rules:
- "headline" is the ad's main title/headline text -- the single most identifying line of the ad (e.g. a product name, a job title being advertised, a promotional tagline). Never leave this null if there is ANY readable text in the ad; fall back to a short phrase summarizing what the ad is for if there's no single obvious headline.
- "ad_type": infer from visual context -- a screenshot with browser/app UI chrome or a URL visible is "Online"; a screenshot showing a social platform's UI (like/comment/share icons, a handle/username, a feed layout) is "Social Media"; a small boxed listing among many similar ones in tiny print is "Classified"; a full-page or half-page magazine/newspaper ad is "Print"; an addressed mailer/postcard is "Direct Mail"; a still frame from TV/radio-style media is "Broadcast"; otherwise "Other".
- "date_published" must be ISO format YYYY-MM-DD, and only filled in if an actual date is printed/shown on the image -- never guess a date.
- "price" is a plain number with no "$" or commas, and only filled in if a specific price, rate, or offer amount is printed on the ad (e.g. "$49.99", "20% OFF" has no price, "Starting at $199/mo" -> price 199). "price_label" captures what that number means in the ad's own words (e.g. "Starting at", "Sale Price", "/month", "Up to X% off" style offers with no single dollar figure go in "offer_details" instead, with price left null).
- "offer_details" is the promotional offer or call-to-action text (e.g. "Buy One Get One Free", "Call now for a free quote", "20% off this week only") -- free text, can be longer than one line.
- "contact_name"/"contact_phone"/"contact_email" are only filled in if a specific person, phone number, or email address is printed directly on the ad itself -- not invented, and not the same thing as "publication" (the outlet the ad ran in).
- "publication" is the name of the magazine, newspaper, website, or platform the ad ran in/on, only if it's evident from the image (e.g. a masthead, a URL, a recognizable platform UI) -- otherwise null.
- Do not invent a headline, price, date, or contact detail that isn't shown in the image.
- "source_notes" should briefly note anything ambiguous and list which important fields simply weren't printed/legible, for that specific ad.
- "uncertain_fields" lists the JSON key names of anything you had to infer, guess, or read with low confidence for that specific ad -- not fields that are just genuinely null.

Return raw JSON only, nothing else. Example shape: {{"ads": [{{...}}, {{...}}]}}"""


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
            "then set it as an environment variable (or in App/.env) before "
            "using this feature."
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
    normalization ai_import.py/business_card_import.py apply, and for the
    same reasons (corrupted/truncated files, a real format that doesn't
    match the extension, unsupported color modes, oversized phone-camera
    photos). Always returns (jpeg_bytes, "image/jpeg") on success. This is
    only what gets SENT to Claude for reading -- the original upload is
    what's actually attached to the ad listing (see
    blueprints/organizations.py), so nothing here affects the saved photo's
    quality."""
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


def extract_ads_from_image(image_bytes, mime_type):
    """Returns (ads, usage): ads is a list of ad dicts (one per distinct ad
    found in the image, always a list even for one ad); usage is
    {"model_code": EXTRACTION_MODEL, "tokens_input": int, "tokens_output": int}
    for the caller to pass to agents.log_agent_usage() (see
    agent_billing.py for the cost computation)."""
    image_bytes, mime_type = _normalize_image(image_bytes, mime_type)

    client = get_client()
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    try:
        message = client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=4000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime_type, "data": b64},
                        },
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }
            ],
        )
    except Exception as e:
        raise ExtractionError(f"Claude API request failed: {e}") from e

    usage = {
        "model_code": EXTRACTION_MODEL,
        "tokens_input": getattr(message.usage, "input_tokens", None),
        "tokens_output": getattr(message.usage, "output_tokens", None),
    }

    text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )
    text = _strip_code_fences(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError(
            f"Couldn't parse Claude's response as JSON. Raw response:\n\n{text}"
        ) from e

    if isinstance(parsed, list):
        ads = parsed  # tolerate a bare array too
    elif isinstance(parsed, dict) and isinstance(parsed.get("ads"), list):
        ads = parsed["ads"]
    else:
        raise ExtractionError(
            f"Expected a JSON object with an 'ads' array, got: {text[:300]}"
        )

    if not ads:
        raise ExtractionError("Claude didn't find any ads in that image.")

    return ads, usage


AD_IMPORT_SCHEMA = """{
  "organization_name": string or null,
  "organization_phone": string or null,
  "organization_website": string or null,
  "organization_email": string or null,
  "address_street": string or null,
  "address_unit": string or null,
  "address_city": string or null,
  "address_state": string or null,
  "address_postal_code": string or null,
  "address_country": string or null,
  "headline": string or null,
  "ad_type": "Print" or "Online" or "Social Media" or "Classified" or "Direct Mail" or "Broadcast" or "Other",
  "publication": string or null,
  "date_published": string or null,
  "description": string or null,
  "offer_details": string or null,
  "price": number or null,
  "price_label": string or null,
  "contact_name": string or null,
  "contact_phone": string or null,
  "contact_email": string or null,
  "source_notes": string,
  "uncertain_fields": [string]
}"""

AD_IMPORT_EXTRACTION_PROMPT = f"""You are extracting information from a photo of an advertisement or marketing material (a magazine or newspaper ad, a "Help Wanted" clipping, a classified ad, a flyer, a social-media post screenshot, or a screenshot of an online ad/web page) so it can be imported into a CRM -- unlike a routine ad scan, the business the ad is FOR is NOT already known, so you must also identify the advertiser.

IMPORTANT: a single image can contain more than one distinct ad (e.g. a page of classifieds, or several promos on one flyer). Identify each DISTINCT ad separately -- do not merge them into one. If several ads on the same image are clearly for the SAME advertiser (e.g. three product promos on one company's flyer), repeat that same advertiser's organization_name/phone/website/email/address on each of those ad entries. If the image is a classifieds-style page mixing several different businesses, extract each one's own advertiser info separately.

Read all text in the image carefully, including small print. Return ONLY a single raw JSON object (no markdown code fences, no commentary before or after) with exactly one key, "ads", whose value is a JSON array. If the image shows only one ad, return an array with exactly one element. Each array element must have exactly these keys:

{AD_IMPORT_SCHEMA}

Rules:
- "organization_name" is the name of the BUSINESS the ad is advertising for (from a logo, letterhead, or business name printed on the ad) -- never the publication/platform the ad ran in, and never invented. Read it as printed (don't expand abbreviations or "correct" spelling). Leave it null only if genuinely no business name is legible anywhere on the ad.
- "organization_phone"/"organization_website"/"organization_email" and the "address_*" fields describe the advertiser's own contact info as printed on the ad (a phone to call, a site to visit, a physical address) -- not the publication's.
- "contact_name"/"contact_phone"/"contact_email" are ONLY filled in if the ad names a SPECIFIC PERSON to contact (e.g. "Ask for Dave", a named sales rep or agent) as distinct from the business's own general phone/email above -- leave all three null if the ad only gives generic business contact info with no named person.
- "headline" is the ad's main title/headline text -- the single most identifying line of the ad (e.g. a product name, a job title being advertised, a promotional tagline). Never leave this null if there is ANY readable text in the ad; fall back to a short phrase summarizing what the ad is for if there's no single obvious headline.
- "ad_type": infer from visual context -- a screenshot with browser/app UI chrome or a URL visible is "Online"; a screenshot showing a social platform's UI (like/comment/share icons, a handle/username, a feed layout) is "Social Media"; a small boxed listing among many similar ones in tiny print is "Classified"; a full-page or half-page magazine/newspaper ad is "Print"; an addressed mailer/postcard is "Direct Mail"; a still frame from TV/radio-style media is "Broadcast"; otherwise "Other".
- "date_published" must be ISO format YYYY-MM-DD, and only filled in if an actual date is printed/shown on the image -- never guess a date.
- "price" is a plain number with no "$" or commas, and only filled in if a specific price, rate, or offer amount is printed on the ad (e.g. "$49.99", "20% OFF" has no price, "Starting at $199/mo" -> price 199). "price_label" captures what that number means in the ad's own words. Up to X% off" style offers with no single dollar figure go in "offer_details" instead, with price left null.
- "offer_details" is the promotional offer or call-to-action text (e.g. "Buy One Get One Free", "Call now for a free quote", "20% off this week only") -- free text, can be longer than one line.
- "publication" is the name of the magazine, newspaper, website, or platform the ad ran in/on, only if it's evident from the image -- otherwise null.
- Do not invent a business name, headline, price, date, address, or contact detail that isn't shown in the image.
- "source_notes" should briefly note anything ambiguous and list which important fields simply weren't printed/legible, for that specific ad.
- "uncertain_fields" lists the JSON key names of anything you had to infer, guess, or read with low confidence for that specific ad -- not fields that are just genuinely null.

Return raw JSON only, nothing else. Example shape: {{"ads": [{{...}}, {{...}}]}}"""


def extract_ads_for_import(image_bytes, mime_type):
    """Like extract_ads_from_image, but for Data Exchange's mass "Import
    Ads/Flyers" feature (blueprints/data_exchange.py) rather than the
    per-Organization ad import on an org's own page (blueprints/
    organizations.py, which this function is NOT used by -- that feature's
    behavior is unchanged). The difference: mass-collected ads/flyers are
    photographed before anyone has entered the advertiser as an
    Organization yet, so this extraction ALSO identifies the advertiser
    (organization_name/phone/website/email/address) per ad, using a
    separate schema/prompt (AD_IMPORT_SCHEMA/AD_IMPORT_EXTRACTION_PROMPT)
    from the org-already-known extraction above. Returns (ads, usage): ads
    is a list of ad dicts (one per distinct ad found in the image, always
    a list even for a single ad); usage is
    {"model_code": EXTRACTION_MODEL, "tokens_input": int, "tokens_output": int}
    for the caller to pass to agents.log_agent_usage()."""
    image_bytes, mime_type = _normalize_image(image_bytes, mime_type)

    client = get_client()
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    try:
        message = client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=4000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime_type, "data": b64},
                        },
                        {"type": "text", "text": AD_IMPORT_EXTRACTION_PROMPT},
                    ],
                }
            ],
        )
    except Exception as e:
        raise ExtractionError(f"Claude API request failed: {e}") from e

    usage = {
        "model_code": EXTRACTION_MODEL,
        "tokens_input": getattr(message.usage, "input_tokens", None),
        "tokens_output": getattr(message.usage, "output_tokens", None),
    }

    text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )
    text = _strip_code_fences(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError(
            f"Couldn't parse Claude's response as JSON. Raw response:\n\n{text}"
        ) from e

    if isinstance(parsed, list):
        ads = parsed  # tolerate a bare array too
    elif isinstance(parsed, dict) and isinstance(parsed.get("ads"), list):
        ads = parsed["ads"]
    else:
        raise ExtractionError(
            f"Expected a JSON object with an 'ads' array, got: {text[:300]}"
        )

    if not ads:
        raise ExtractionError("Claude didn't find any ads in that image.")

    return ads, usage


def iter_images_from_zip(zip_bytes):
    """Yields (filename, image_bytes, mime_type) for each image found in an
    uploaded zip of ad photos. Skips folders, hidden/system files
    (.DS_Store, __MACOSX, dotfiles), and anything that isn't a recognized
    image extension. Filename is just the base name (no folder path) for
    display. Identical logic to ai_import.py's iter_images_from_zip.

    Raises zipfile.BadZipFile if the upload isn't actually a valid zip.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if "__MACOSX" in name:
                continue
            base = name.rsplit("/", 1)[-1]
            if not base or base.startswith("."):
                continue
            ext = base[base.rfind("."):].lower() if "." in base else ""
            mime_type = ZIP_IMAGE_EXTENSIONS.get(ext)
            if not mime_type:
                continue
            yield base, zf.read(info), mime_type
