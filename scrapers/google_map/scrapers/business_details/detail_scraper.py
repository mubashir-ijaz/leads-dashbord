# Google Maps internal API scraper — business details.
# Uses the /maps/preview/place endpoint discovered via DevTools capture (2026-04).
#
# This single module merges the two original scrapers:
#   - "basic"    (was app_main.py)     -> core fields only
#   - "detailed" (was app_detailed.py) -> basic + description, services, photos,
#                                          CID/ChIJ IDs, city/street/region, etc.
# Pick the level per run via the interactive menu (settings.DETAIL_LEVEL).
#
# IMPORTANT — KNOWN LIMITATIONS:
# 1. Field indices in the response array drift over time. The FIELD_PATHS dicts
#    below are your single source of truth — fix them there when fields move.
# 2. This endpoint may rate-limit or require cookies after N requests. The code
#    retries with backoff but won't survive a hard block — use a proxy for volume.

import re
import csv
import json
import time
import random
import logging
import datetime
from pathlib import Path

import requests
import tldextract
from openpyxl import Workbook
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

import settings

log = logging.getLogger(__name__)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ---------------------------------------------------------------------------
# Field paths into the parsed JSON response. Each path is a list of indices
# applied sequentially to the root array. None means "field unknown — skip".
# ---------------------------------------------------------------------------

# "basic" — the core set (originally app_main.py).
FIELD_PATHS_BASIC = {
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
    "place_id_crc":      None,
}

# "detailed" — basic plus the richer fields (originally app_detailed.py).
FIELD_PATHS_DETAILED = {
    **FIELD_PATHS_BASIC,

    # Place ID variants (canonical cluster at [227][0])
    "place_id_crc":      [6, 227, 0, 4],  # "ChIJE4q3QErlwokRPMtFdVQHuBM"
    "cid_decimal":       [6, 227, 0, 5],  # "18089824232468106639" — direct, no hex parsing

    # Tier 1 additions
    "description":       [6, 154, 0, 0],  # "Ag vip mobile detailing\nWe come to you"
    "country_code":      [6, 243],        # "US"
    "region_label":      [6, 166],        # "Hillsdale, NJ, United States"
    "language":          [6, 110],        # "en"
    "city":              [6, 82, 3],      # "Hillsdale"
    "street":            [6, 82, 1],      # "432 Broadway"

    # Tier 2/3 additions (parsed via dedicated extractors — paths point at
    # containers, not leaf values)
    "services_root":     [6, 125, 0, 0, 1, 0, 1],   # list of [[["Name", ""]]]
    "profile_photo":     [6, 122, 0, 1],            # https://lh3.googleusercontent.com/...
    "photo_gallery":     [6, 51],                   # list of photo groups
}

# ---------------------------------------------------------------------------
# pb= parameter template
# ---------------------------------------------------------------------------
# The captured pb= with placeholders for the per-place fields. It encodes a
# protobuf-like structure; we substitute values without fully decoding it. The
# session token (ei) appears as !14m3!1s<TOKEN>!7e81 and matches the `ei` param
# from the Maps initial page load.

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

    Returns dict with: name, lat, lng, place_id_hex, fid (feature id like /g/...).
    Returns None if the URL doesn't match Maps' /place/ pattern.
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

    fid_match = re.search(r"!16s(%2F[a-zA-Z]%2F[a-zA-Z0-9]+|/[a-zA-Z]/[a-zA-Z0-9]+)", url)
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
    """
    Hit the Maps page first to get a fresh session token (`ei`).
    Returns empty string if extraction fails (the API may still work without it,
    or with a stale value — we'll find out empirically).
    """
    try:
        resp = session.get(url, timeout=settings.REQUEST_TIMEOUT)
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
        distance="3010.5056104",   # benign hardcoded value from capture; doesn't seem to matter
        lat=parsed["lat"],
        lng=parsed["lng"],
        fid=parsed["fid"] or "",
        ei=ei_token or settings.FALLBACK_EI_TOKEN,  # fallback to captured token; may stale-out
    )


def call_place_api(parsed: dict, ei_token: str, session: requests.Session, referer: str) -> str | None:
    """Make the actual /maps/preview/place call. Returns raw response text on success."""
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
        "user-agent": settings.USER_AGENT,
    }

    last_exc = None
    for attempt in range(settings.MAX_RETRIES):
        time.sleep(random.uniform(*settings.JITTER_RANGE))
        try:
            resp = session.get(
                settings.PLACE_ENDPOINT, params=params, headers=headers,
                timeout=settings.REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (429, 503):
                wait = settings.BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                log.warning("Got %d; backing off %.1fs (attempt %d)", resp.status_code, wait, attempt + 1)
                time.sleep(wait)
                continue
            log.error("Place API returned %d for %s", resp.status_code, parsed["name"])
            return None
        except requests.RequestException as e:
            last_exc = e
            log.warning("Request error attempt %d: %s", attempt + 1, e)
            time.sleep(settings.BACKOFF_BASE * (2 ** attempt))

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


def extract_domain(url: str) -> str:
    if not url:
        return ""
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ""


def find_phone_fallback(data) -> str:
    """
    Walk the entire structure looking for a string matching a phone-number
    pattern. Crude fallback used when the mapped phone path comes back empty.
    """
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
    """
    Parse the canonical weekly hours block from data[6][203][0].

    Structure: list of 7 day-entries, one per weekday. Each entry:
        [day_name, weekday_num, [Y, M, D], [[hours_str, [[start_h], [end_h]]]], 0, 1]

    Returns dict mapping full day name (Monday..Sunday) → string.
    """
    result = {d: "" for d in DAYS}

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
                # Normalize narrow no-break space (U+202F) and en-dash spacing
                s = slot[0].replace("\u202f", " ").replace("\u2013", "-")
                slot_strs.append(s.upper())
        result[day_name] = ", ".join(slot_strs) if slot_strs else "Closed"

    return result


def extract_services(services_root) -> str:
    """
    Flatten the services container into a "; "-joined string of service names.
    Structure: services_root = [[ [["Name", ""]], [["Name2", ""]], ... ]]
    """
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
    """
    Count photos and return joined URLs from the photo gallery container.
    The thumbnail URL lives at item[6][0]; we strip Google's size suffix so each
    URL points at the full-resolution image.
    """
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


# ---------------------------------------------------------------------------
# Field extraction (basic vs detailed)
# ---------------------------------------------------------------------------

def _common_core(parsed_response, field_paths, source_url):
    """Pull the fields shared by both basic and detailed extraction."""
    g = lambda key: safe_get(parsed_response, field_paths.get(key))

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
    hours_dict = parse_hours(hours) if hours else {d: "" for d in DAYS}

    plus_code = g("plus_code") or ""
    place_id_hex = g("place_id_hex") or ""

    return {
        "g": g, "name": name, "full_addr": full_addr, "category": category,
        "lat": lat, "lng": lng, "avg_rating": avg_rating,
        "total_reviews": total_reviews, "reviews_url": reviews_url,
        "website": website, "phone": phone, "hours_dict": hours_dict,
        "plus_code": plus_code, "place_id_hex": place_id_hex,
    }


def extract_fields_basic(parsed_response, source_url) -> dict:
    """Core fields only (was app_main.py)."""
    c = _common_core(parsed_response, FIELD_PATHS_BASIC, source_url)

    cid = ""
    if c["place_id_hex"] and ":" in c["place_id_hex"]:
        try:
            cid = str(int(c["place_id_hex"].split(":")[1], 16))
        except ValueError:
            pass

    return {
        "Source URL": source_url,
        "URL": f"https://www.google.com/maps?cid={cid}" if cid else source_url,
        "Name": c["name"],
        "Category": c["category"],
        "Phone": c["phone"],
        "Website": c["website"],
        "Address": c["full_addr"] or "",
        "Plus Code": c["plus_code"],
        "Latitude": c["lat"],
        "Longitude": c["lng"],
        "Reviews URL": c["reviews_url"],
        "Average Rating": c["avg_rating"] if c["avg_rating"] is not None else "",
        "Total Reviews": c["total_reviews"] if c["total_reviews"] is not None else "",
        "Business Status": "OPERATIONAL",
        **{f"Opening Hours [{d.lower()[:3]}]": c["hours_dict"].get(d, "") for d in DAYS},
        "Scraped Date": datetime.datetime.now().strftime("%d-%m-%Y %I:%M:%S %p"),
    }


def extract_fields_detailed(parsed_response, source_url) -> dict:
    """Core fields PLUS the richer set (was app_detailed.py)."""
    c = _common_core(parsed_response, FIELD_PATHS_DETAILED, source_url)
    g = c["g"]
    name = c["name"]

    place_id_chij = g("place_id_crc") or ""
    cid = g("cid_decimal") or ""
    if not cid and c["place_id_hex"] and ":" in c["place_id_hex"]:
        try:
            cid = str(int(c["place_id_hex"].split(":")[1], 16))
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
        "Category": c["category"],
        "Phone": c["phone"],
        "Phone (E.164)": phone_intl,
        "Website": c["website"],
        "Address": c["full_addr"] or "",
        "Street": street,
        "City": city,
        "Region": region_label,
        "Country Code": country_code,
        "Language": language,
        "Plus Code": c["plus_code"],
        "Latitude": c["lat"],
        "Longitude": c["lng"],
        "CID": cid,
        "ChIJ Place ID": place_id_chij,
        "Services": services,
        "Profile Photo": profile_photo,
        "Photo Count": photo_count,
        "Photo URLs": photo_urls,
        "Reviews URL": c["reviews_url"],
        "Average Rating": c["avg_rating"] if c["avg_rating"] is not None else "",
        "Total Reviews": c["total_reviews"] if c["total_reviews"] is not None else "",
        "Business Status": "OPERATIONAL",
        **{f"Opening Hours [{d.lower()[:3]}]": c["hours_dict"].get(d, "") for d in DAYS},
        "Scraped Date": datetime.datetime.now().strftime("%d-%m-%Y %I:%M:%S %p"),
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def fetch_and_parse(url: str, detail_level: str) -> dict | None:
    """End-to-end: URL → API call → parsed dict, using the chosen detail level."""
    url = sanitize_url(url)
    if not url:
        log.warning("Skipping invalid URL")
        return None

    parsed = parse_maps_url(url)
    if not parsed:
        log.error("Could not parse Maps URL: %s", url)
        return None

    session = requests.Session()
    proxies = settings.proxies_dict()
    if proxies:
        session.proxies.update(proxies)
    ei_token = fetch_session_token(url, session)
    raw = call_place_api(parsed, ei_token, session, referer=url)
    if not raw:
        return None

    body = strip_xssi(raw)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        log.error("JSON parse failed for %s: %s", parsed["name"], e)
        return None

    if detail_level == "basic":
        return extract_fields_basic(data, url)
    return extract_fields_detailed(data, url)


_EXCEL_MAX_CELL = 32767
_ILLEGAL_XLSX_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_SCALARS = (str, int, float, bool,
            datetime.datetime, datetime.date, datetime.time)


def _cell_value(value):
    """Coerce a scraped value into something openpyxl will accept.

    A field path can land on a nested node instead of a scalar when Google's
    response array shifts shape, and openpyxl raises on anything it can't map
    to a cell. Drop that one field rather than lose the whole run.
    """
    if value is None or isinstance(value, _SCALARS):
        text = value
    elif (isinstance(value, (list, tuple))
            and all(isinstance(v, (str, int, float)) for v in value)):
        text = "; ".join(str(v) for v in value)
    else:
        return None

    if isinstance(text, str):
        text = _ILLEGAL_XLSX_CHARS.sub("", text)
        if len(text) > _EXCEL_MAX_CELL:
            text = text[:_EXCEL_MAX_CELL - 1] + "…"
    return text


def save_to_excel(rows: list, path):
    if not rows:
        log.info("Nothing to save")
        return

    # Rows can differ in shape — an interrupted enrichment pass leaves later
    # rows without the contact columns — so collect every key and look each
    # cell up by name. Indexing by position would silently shift columns.
    headers = list(rows[0])
    known = set(headers)
    for r in rows:
        for key in r:
            if key not in known:
                known.add(key)
                headers.append(key)

    wb = Workbook()
    ws = wb.active
    ws.append(headers)

    dropped: dict[str, int] = {}
    for r in rows:
        line = []
        for key in headers:
            raw = r.get(key, "")
            cell = _cell_value(raw)
            if cell is None and raw is not None:
                dropped[key] = dropped.get(key, 0) + 1
                cell = ""
            line.append(cell)
        ws.append(line)

    wb.save(str(path))
    log.info("Saved %d rows to %s", len(rows), path)
    if dropped:
        summary = ", ".join(f"{k} ({n})" for k, n in sorted(dropped.items()))
        log.warning("Blanked %d non-scalar value(s) Excel cannot store — the "
                    "field path likely drifted for these columns: %s",
                    sum(dropped.values()), summary)


def process_links(links: list[str], detail_level: str, max_workers: int,
                  rows: list[dict] | None = None,
                  failed: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Scrape every link concurrently (Maps details only).

    Emails / social handles are NOT crawled here — they're gathered afterwards
    in a single batched async pass (see ``enrich_rows``), which is far faster
    than crawling each website inline inside every Maps worker.

    Pass `rows` / `failed` to have results appended to your own lists as they
    arrive, so a Ctrl+C mid-run still leaves the caller holding everything
    gathered so far. Returns (rows, failed).
        - `failed` is the list of input URLs that produced no data
          (invalid/unparseable URL, request failure, or a crash).
    """
    if rows is None:
        rows = []
    if failed is None:
        failed = []

    def work(link: str) -> dict | None:
        return fetch_and_parse(link, detail_level=detail_level)

    ex = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {ex.submit(work, link): link for link in links}
        for fut in tqdm(as_completed(futures), total=len(futures), desc="Scraping"):
            link = futures[fut]
            try:
                result = fut.result()
                if result:
                    rows.append(result)
                else:
                    failed.append(link)
            except Exception as e:
                log.error("Worker crashed on %s: %s", link, e)
                failed.append(link)
    finally:
        # On Ctrl+C / error, stop promptly instead of blocking on the queue —
        # whatever is already in `rows` / `failed` is preserved for the caller
        # to save.
        ex.shutdown(wait=False, cancel_futures=True)
    return rows, failed


def save_failed_links(failed: list[str], output_dir, basename: str):
    """Write the URLs that failed to a uniquely-named text file (one per line).

    The file is plain URLs with no header, so it can be fed straight back in as
    the input file to retry just the failures. Returns the path, or None when
    there were no failures (no file is created).
    """
    if not failed:
        return None
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{basename}_failed.txt"
    with open(path, "w", encoding="utf-8") as f:
        for url in failed:
            f.write(f"{url}\n")
    return path


def read_input_links(path) -> list[str]:
    """
    Read place URLs from the input file, deduped, order preserved.

    Supports two formats:
      - .txt : one URL per line.
      - .csv : the link collector's output (columns Link, Category, Location).
               The "Link" column is used (or the first column if no header).
    """
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"Input file not found: {path}")

    raw_links: list[str] = []
    if path.suffix.lower() == ".csv":
        # utf-8-sig: the link collector writes CSVs with a BOM for Excel.
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        if rows:
            header = [c.strip().lower() for c in rows[0]]
            if "link" in header:
                link_idx, start = header.index("link"), 1
            else:
                link_idx, start = 0, 0   # no header — assume first column is the URL
            for row in rows[start:]:
                if len(row) > link_idx and row[link_idx].strip():
                    raw_links.append(row[link_idx].strip())
    else:
        raw_links = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
                     if ln.strip()]

    seen, out = set(), []
    for ln in raw_links:
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    return out


SOCIAL_COLUMNS = ["Facebook", "Instagram", "Twitter", "LinkedIn", "YouTube", "TikTok"]

_email_engine = None  # cached (collect_contacts, root_domain), or False if unavailable


def _get_email_engine():
    """Import the email engine once (run.py/runner adds it to sys.path).

    Returns (collect_contacts, root_domain), or None if it can't be imported.
    """
    global _email_engine
    if _email_engine is None:
        try:
            from engine.api import collect_contacts, root_domain
            _email_engine = (collect_contacts, root_domain)
        except Exception as e:
            log.warning("Email engine unavailable (%s) — skipping contact extraction.", e)
            _email_engine = False
    return _email_engine or None


def _move_scraped_date_last(row: dict) -> None:
    """Keep the timestamp as the final column after other columns are added."""
    if "Scraped Date" in row:
        row["Scraped Date"] = row.pop("Scraped Date")


def enrich_rows(rows: list[dict], opts: dict, concurrency: int = 40) -> None:
    """Crawl every business website ONCE, in a single batched async pass, and
    merge the emails/socials columns into the matching rows.

    Far faster than crawling per-business inline: the email engine fetches all
    the sites concurrently (async) instead of one-at-a-time inside each Maps
    worker thread. Rows are matched to results by root domain, and unique
    domains are crawled only once.

    opts = {"want_emails": bool, "want_socials": bool, "mode": "single"|"all"}
    Always adds the contact columns to every row (empty strings when there's no
    website or nothing was found) so the output keeps a uniform shape.
    """
    want_emails = opts.get("want_emails", True)
    want_socials = opts.get("want_socials", True)
    extra_cols = (["Emails"] if want_emails else []) + (SOCIAL_COLUMNS if want_socials else [])

    engine = _get_email_engine()
    by_domain: dict = {}
    row_domains: list[str] = []

    if engine:
        collect_contacts, root_domain = engine
        # Collect the unique websites to crawl, and remember each row's domain
        # so results can be merged back onto it afterwards.
        seen: set[str] = set()
        websites: list[str] = []
        for row in rows:
            website = (row.get("Website") or "").strip()
            domain = root_domain(website) if website else ""
            row_domains.append(domain)
            if domain and domain not in seen:
                seen.add(domain)
                url = (website if website.startswith(("http://", "https://"))
                       else f"http://{website}")
                websites.append(url)

        if websites:
            log.info("Crawling %d unique website(s) for emails/socials "
                     "(concurrency=%d)...", len(websites), concurrency)
            # Drive a live progress bar so the batched crawl isn't silent (a
            # long, quiet pass here looks like a hang).
            try:
                from engine.api import make_bar_emit
                emit, close_bar = make_bar_emit("Emails/socials")
            except Exception:
                emit, close_bar = (lambda *a, **k: None), (lambda: None)
            try:
                by_domain = collect_contacts(
                    websites, mode=opts.get("mode", "single"),
                    want_emails=want_emails, want_socials=want_socials,
                    concurrency=concurrency, emit=emit,
                )
            except Exception as e:
                log.warning("Contact extraction pass failed: %s", e)
                by_domain = {}
            finally:
                close_bar()
    else:
        row_domains = ["" for _ in rows]

    for row, domain in zip(rows, row_domains):
        contacts = by_domain.get(domain)
        for col in extra_cols:
            row[col] = (contacts.get(col, "") if contacts else "")
        _move_scraped_date_last(row)


def run(cfg=settings):
    """
    Entry point used by the project's run.py. Reads links from cfg.INPUT_FILE,
    scrapes each at cfg.DETAIL_LEVEL, and writes one xlsx to cfg.OUTPUT_DIR.

    If cfg.EMAIL_OPTIONS is set, each business's website is crawled for emails /
    social handles inline — right after that business is scraped — and the
    results are merged into its row.
    """
    links = read_input_links(cfg.INPUT_FILE)

    if not links:
        raise SystemExit(f"No links found in {cfg.INPUT_FILE}")

    log.info("Input: %s", cfg.INPUT_FILE)

    detail_level = (getattr(cfg, "DETAIL_LEVEL", "detailed") or "detailed").strip().lower()
    log.info("Processing %d unique link(s) at '%s' detail level", len(links), detail_level)

    email_opts = getattr(cfg, "EMAIL_OPTIONS", None)
    if email_opts:
        log.info("Contact extraction is ON — websites are crawled in one batched "
                 "pass after the Maps details are scraped.")

    # Own the result lists here so a Ctrl+C mid-run still saves what was done.
    # Failed links are queued and retried after each pass — up to
    # MAX_RETRY_CYCLES extra rounds — before any leftovers are written to disk.
    MAX_RETRY_CYCLES = max(0, int(getattr(cfg, "MAX_RETRY_CYCLES", 5)))
    rows: list[dict] = []
    pending = list(links)          # links still to attempt in the next round
    round_failed: list[str] = []   # failures recorded in the round in progress
    try:
        for cycle in range(MAX_RETRY_CYCLES + 1):   # cycle 0 = initial pass
            if not pending:
                break
            if cycle:
                log.info("Retry cycle %d/%d — re-attempting %d failed link(s)...",
                         cycle, MAX_RETRY_CYCLES, len(pending))
            round_failed = []
            process_links(pending, detail_level, cfg.MAX_WORKERS, rows, round_failed)
            pending = round_failed   # only the failures move on to the next round

        # Contacts are gathered in ONE batched pass now (all websites crawled
        # concurrently) — far faster than crawling each site inline per business.
        if email_opts and rows:
            enrich_rows(rows, email_opts,
                        concurrency=int(getattr(cfg, "EMAIL_CONCURRENCY", 40)))
    except KeyboardInterrupt:
        log.warning("Interrupted by user — saving data collected so far...")
        pending = round_failed
    finally:
        cfg.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        basename = datetime.datetime.now().strftime(cfg.OUTPUT_FILENAME_PATTERN)
        out_path = cfg.OUTPUT_DIR / f"{basename}.xlsx"
        save_to_excel(rows, out_path)
        failed = pending             # whatever is still failing after all retries
        failed_path = save_failed_links(failed, cfg.OUTPUT_DIR, basename)
        log.info("=" * 60)
        if rows:
            log.info("DONE. Wrote %s (%d businesses)", out_path, len(rows))
        else:
            log.info("DONE. No business details collected.")
        if failed_path:
            log.info("%d link(s) still failed after %d retry cycle(s) — saved to %s "
                     "(feed it back in to retry)",
                     len(failed), MAX_RETRY_CYCLES, failed_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    run()
