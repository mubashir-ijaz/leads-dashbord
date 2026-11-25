# Low-level Google Maps place parsing + HTTP helpers.
#
# This module is the foundation the API search engine (search_api.py) builds on.
# It knows how to:
#   - parse a Maps /place/ URL into the bits needed to call the place API
#   - strip Google's XSSI guard and walk the nested JSON response
#   - extract ~35 business fields from a place response
#
# Tunables (user agent, timeouts, retries, proxy) come from settings.py - don't
# hardcode them here.
#
# KNOWN LIMITATION: field indices in Google's response array drift over time.
# FIELD_PATHS below is the single source of truth - fix it there when fields
# move.

import re
import json
import time
import random
import logging
import datetime
import requests
import tldextract
from urllib.parse import quote

import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (sourced from settings.py)
# ---------------------------------------------------------------------------

PLACE_ENDPOINT = "https://www.google.com/maps/preview/place"

USER_AGENT = settings.USER_AGENT
REQUEST_TIMEOUT = settings.REQUEST_TIMEOUT
MAX_RETRIES = settings.MAX_RETRIES
BACKOFF_BASE = settings.BACKOFF_BASE
JITTER_RANGE = settings.JITTER_RANGE


def new_session() -> requests.Session:
    """Create a requests session, wired to the proxy if one is configured."""
    s = requests.Session()
    proxies = settings.proxies_dict()
    if proxies:
        s.proxies.update(proxies)
    return s


# Field paths into the parsed JSON response. Each path is a list of indices
# applied sequentially to the root array. Verified from the 2026-04 capture.
FIELD_PATHS = {
    "ved_token":         [6, 1],
    "address_lines":     [6, 2],
    "reviews_url":       [6, 4, 3, 0],
    "reviews_label":     [6, 4, 3, 1],
    "average_rating":    [6, 4, 7],
    "total_reviews":     [6, 4, 8],
    "website_full":      [6, 7, 0],
    "website_display":   [6, 7, 1],
    "latitude":          [6, 9, 2],
    "longitude":         [6, 9, 3],
    "place_id_hex":      [6, 10],
    "business_name":     [6, 11],
    "categories":        [6, 13],
    "full_address":      [6, 18],
    "timezone":          [6, 30],
    "phone":             [6, 178, 0, 0],
    "phone_intl":        [6, 178, 0, 3],
    "opening_hours":     [6, 203, 0],
    "plus_code":         [6, 183, 2, 2, 0],
    "place_id_crc":      [6, 227, 0, 4],
    "cid_decimal":       [6, 227, 0, 5],
    "description":       [6, 154, 0, 0],
    "country_code":      [6, 243],
    "region_label":      [6, 166],
    "language":          [6, 110],
    "city":              [6, 82, 3],
    "street":            [6, 82, 1],
    "services_root":     [6, 125, 0, 0, 1, 0, 1],
    "profile_photo":     [6, 122, 0, 1],
    "photo_gallery":     [6, 51],
}

# ---------------------------------------------------------------------------
# pb= parameter template (per-place values substituted in)
# ---------------------------------------------------------------------------

PB_TEMPLATE = (
    "!1m17!1s{place_id_hex}!2s{name_encoded}"
    "!3m8!1m3!1d{distance}!2d{lng}!3d{lat}!3m2!1i1024!2i768!4f13.1"
    "!4m2!3d{lat}!4d{lng}"
    "!15m2!1m1!4s{fid}"
    "!12m4!2m3!1i360!2i120!4i8"
    "!13m57!2m2!1i203!2i100!3m2!2i4!5b1"
    "!6m6!1m2!1i86!2i86!1m2!1i408!2i240"
    "!7m33!1m3!1e1!2b0!3e3!1m3!1e2!2b1!3e2!1m3!1e2!2b0!3e3"
    "!1m3!1e8!2b0!3e3!1m3!1e10!2b0!3e3!1m3!1e10!2b1!3e2"
    "!1m3!1e10!2b0!3e4!1m3!1e9!2b1!3e2!2b1!9b0"
    "!15m8!1m7!1m2!1m1!1e2!2m2!1i195!2i195!3i20"
    "!14m3!1s{ei}!7e81!15i10112"
    "!15m108!1m26!13m9!2b1!3b1!4b1!6i1!8b1!9b1!14b1!20b1!25b1"
    "!18m15!3b1!4b1!5b1!6b1!13b1!14b1!17b1!21b1!22b1!30b1!32b1"
    "!33m1!1b1!34b1!36e2!10m1!8e3!11m1!3e1!17b1!20m2!1e3!1e6"
    "!24b1!25b1!26b1!27b1!29b1!30m1!2b1!36b1!37b1"
    "!39m3!2m2!2i1!3i1!43b1!52b1!54m1!1b1!55b1!56m1!1b1"
    "!61m2!1m1!1e1!65m5!3m4!1m3!1m2!1i224!2i298"
    "!72m22!1m8!2b1!5b1!7b1!12m4!1b1!2b1!4m1!1e1!4b1"
    "!8m10!1m6!4m1!1e1!4m1!1e3!4m1!1e4"
    "!3sother_user_google_review_posts__and__hotel_and_vr_partner_review_posts"
    "!6m1!1e1!9b1!89b1!90m2!1m1!1e2!98m3!1b1!2b1!3b1!103b1!113b1"
    "!114m3!1b1!2m1!1b1!117b1!122m1!1b1!126b1!127b1!128m1!1b0"
    "!21m0!22m1!1e81!30m8!3b1!6m2!1b1!2b1!7m2!1e3!2b1!9b1"
    "!34m5!7b1!10b1!14b1!15m1!1b0!37i776"
)

# Fallback session token (ei) used inside pb= when we can't extract a fresh one.
FALLBACK_EI_TOKEN = "Bv_uaZnSJYzPhbIP6M-uoQY"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_url(raw: str) -> str | None:
    """Strip view-source: pseudo-scheme and validate."""
    raw = raw.strip()
    if raw.startswith("view-source:"):
        raw = raw[len("view-source:"):]
    if not raw.startswith(("http://", "https://")):
        return None
    return raw


def parse_maps_url(url: str) -> dict | None:
    """
    Extract the bits we need to build the place API call from a Maps URL.
    Returns dict with: name, lat, lng, place_id_hex, fid. None if not a /place/ URL.
    """
    name_match = re.search(r"/place/([^/@]+)", url)
    name = name_match.group(1).replace("+", " ") if name_match else None

    coord_match = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if coord_match:
        lat, lng = float(coord_match.group(1)), float(coord_match.group(2))
    else:
        d_match = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
        if d_match:
            lat, lng = float(d_match.group(1)), float(d_match.group(2))
        else:
            return None

    pid_match = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", url)
    place_id_hex = pid_match.group(1) if pid_match else None

    fid_match = re.search(r"!16s(%2F[a-zA-Z]%2F[a-zA-Z0-9_]+|/[a-zA-Z]/[a-zA-Z0-9_]+)", url)
    fid = None
    if fid_match:
        fid = fid_match.group(1).replace("%2F", "/")

    if not (name and place_id_hex):
        return None

    return {
        "name": name,
        "lat": lat,
        "lng": lng,
        "place_id_hex": place_id_hex,
        "fid": fid or "",
    }


def fetch_session_token(url: str, session: requests.Session) -> str:
    """Hit the Maps page to get a fresh session token (`ei`). Empty on failure."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            log.warning("Session-token fetch returned %d", resp.status_code)
            return ""
        m = re.search(r'\\"([A-Za-z0-9_-]{22})\\",\\"0ahUK', resp.text)
        if m:
            return m.group(1)
    except Exception as e:
        log.warning("Session-token fetch failed: %s", e)
    return ""


def build_pb(parsed: dict, ei_token: str) -> str:
    """Substitute per-place values into the pb= template."""
    return PB_TEMPLATE.format(
        place_id_hex=parsed["place_id_hex"],
        name_encoded=parsed["name"].replace(" ", "+"),
        distance="3010.5056104",
        lat=parsed["lat"],
        lng=parsed["lng"],
        fid=parsed["fid"] or "",
        ei=ei_token or FALLBACK_EI_TOKEN,
    )


def call_place_api(parsed: dict, ei_token: str, session: requests.Session,
                   referer: str) -> str | None:
    """Make the /maps/preview/place call. Returns raw response text on success."""
    pb_value = build_pb(parsed, ei_token)
    params = {
        "authuser": "0",
        "hl": "en",
        "q": parsed["name"],
        "pb": pb_value,
    }
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "referer": referer,
        "user-agent": USER_AGENT,
    }

    last_exc = None
    for attempt in range(MAX_RETRIES):
        time.sleep(random.uniform(*JITTER_RANGE))
        try:
            resp = session.get(PLACE_ENDPOINT, params=params, headers=headers,
                               timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (429, 503):
                wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                log.warning("Got %d; backing off %.1fs (attempt %d)",
                            resp.status_code, wait, attempt + 1)
                time.sleep(wait)
                continue
            log.error("Place API returned %d for %s", resp.status_code, parsed["name"])
            return None
        except requests.RequestException as e:
            last_exc = e
            log.warning("Request error attempt %d: %s", attempt + 1, e)
            time.sleep(BACKOFF_BASE * (2 ** attempt))

    log.error("All retries exhausted for %s: %s", parsed["name"], last_exc)
    return None


def strip_xssi(text: str) -> str:
    """Remove the )]}'\\n prefix Google uses on JSON responses."""
    if text.startswith(")]}'"):
        nl = text.find("\n")
        if nl >= 0:
            return text[nl + 1:]
    return text


def safe_get(data, path):
    """Walk a nested list using a path of indices. Return None on any failure."""
    if path is None:
        return None
    try:
        for idx in path:
            data = data[idx]
        return data
    except (IndexError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def extract_fields(parsed_response: list, source_url: str) -> dict:
    """Pull all the fields we know about from the parsed JSON response."""
    g = lambda key: safe_get(parsed_response, FIELD_PATHS.get(key))

    name = g("business_name") or ""

    full_addr = g("full_address")
    address_lines = g("address_lines") or []
    if not full_addr and address_lines:
        full_addr = ", ".join(x for x in address_lines if x)
    if full_addr and name and full_addr.startswith(name + ","):
        full_addr = full_addr[len(name) + 2:]

    categories = g("categories") or []
    category = categories[0] if categories else ""

    lat = g("latitude") or ""
    lng = g("longitude") or ""

    avg_rating = g("average_rating")
    total_reviews = g("total_reviews")
    reviews_url = g("reviews_url") or ""
    if reviews_url:
        reviews_url = reviews_url.encode().decode("unicode_escape")

    website_full = g("website_full") or ""
    website_display = g("website_display") or ""
    website = website_display or extract_domain(website_full)

    phone = g("phone") or ""
    if not phone:
        phone = find_phone_fallback(parsed_response)

    hours = g("opening_hours")
    hours_dict = parse_hours(hours) if hours else {d: "" for d in
                  ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}

    plus_code = g("plus_code") or ""

    place_id_hex = g("place_id_hex") or ""
    place_id_chij = g("place_id_crc") or ""
    cid = g("cid_decimal") or ""
    if not cid and place_id_hex and ":" in place_id_hex:
        try:
            cid = str(int(place_id_hex.split(":")[1], 16))
        except ValueError:
            pass

    description_raw = g("description") or ""
    description = description_raw
    if description and name and description.startswith(name + "\n"):
        description = description[len(name) + 1:]
    description = description.replace("\n", " ").strip()

    country_code = g("country_code") or ""
    region_label = g("region_label") or ""
    language     = g("language") or ""
    city         = g("city") or ""
    street       = g("street") or ""
    phone_intl   = g("phone_intl") or ""

    services = extract_services(g("services_root"))
    profile_photo = g("profile_photo") or ""
    photo_count, photo_urls = extract_photos(g("photo_gallery"))

    return {
        "Source URL": source_url,
        "URL": f"https://www.google.com/maps?cid={cid}" if cid else source_url,
        "Name": name,
        "Description": description,
        "Category": category,
        "Phone": phone,
        "Phone (E.164)": phone_intl,
        "Website": website,
        "Address": full_addr or "",
        "Street": street,
        "City": city,
        "Region": region_label,
        "Country Code": country_code,
        "Language": language,
        "Plus Code": plus_code,
        "Latitude": lat,
        "Longitude": lng,
        "CID": cid,
        "ChIJ Place ID": place_id_chij,
        "Services": services,
        "Profile Photo": profile_photo,
        "Photo Count": photo_count,
        "Photo URLs": photo_urls,
        "Reviews URL": reviews_url,
        "Average Rating": avg_rating if avg_rating is not None else "",
        "Total Reviews": total_reviews if total_reviews is not None else "",
        "Business Status": "OPERATIONAL",
        **{f"Opening Hours [{d.lower()[:3]}]": hours_dict.get(d, "") for d in
           ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]},
        "Scraped Date": datetime.datetime.now().strftime("%d-%m-%Y %I:%M:%S %p"),
    }


def extract_services(services_root) -> str:
    """Flatten the services container into a '; '-joined string of names."""
    if not isinstance(services_root, list) or not services_root:
        return ""
    inner = services_root[0]
    if not isinstance(inner, list):
        return ""
    names = []
    for item in inner:
        try:
            name = item[0][0]
            if isinstance(name, str) and name:
                names.append(name)
        except (IndexError, TypeError):
            continue
    return "; ".join(names)


def extract_photos(gallery_root) -> tuple[int, str]:
    """Count photos and return joined full-resolution URLs from the gallery."""
    if not isinstance(gallery_root, list):
        return 0, ""
    urls = []
    for group in gallery_root:
        if not isinstance(group, list):
            continue
        for item in group if isinstance(group[0], list) else [group]:
            try:
                url = item[6][0]
                if isinstance(url, str) and url.startswith("http"):
                    url = re.sub(r"=[swh][\d-]+[a-z-]*$", "", url)
                    urls.append(url)
            except (IndexError, TypeError):
                continue
    seen = set()
    unique = [u for u in urls if not (u in seen or seen.add(u))]
    return len(unique), "; ".join(unique)


def extract_domain(url: str) -> str:
    if not url:
        return ""
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ""


def find_phone_fallback(data) -> str:
    """Phone path is fragile. Walk the structure for a phone-shaped string."""
    phone_re = re.compile(r"^\+?\d[\d\s\-().]{8,}\d$")
    found = []

    def walk(node):
        if isinstance(node, str):
            if phone_re.match(node) and any(c.isdigit() for c in node):
                digits = re.sub(r"\D", "", node)
                if 10 <= len(digits) <= 15:
                    found.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found[0] if found else ""


def parse_hours(hours_node) -> dict:
    """Parse the canonical weekly hours block into {Monday..Sunday: string}."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    result = {d: "" for d in days}

    if not isinstance(hours_node, list):
        return result

    for entry in hours_node:
        if not (isinstance(entry, list) and len(entry) >= 4 and isinstance(entry[0], str)):
            continue
        day_name = entry[0]
        if day_name not in result:
            continue
        slots = entry[3]
        if not slots:
            result[day_name] = "Closed"
            continue
        slot_strs = []
        for slot in slots:
            if isinstance(slot, list) and slot and isinstance(slot[0], str):
                s = slot[0].replace(" ", " ").replace("–", "-")
                slot_strs.append(s.upper())
        result[day_name] = ", ".join(slot_strs) if slot_strs else "Closed"

    return result
