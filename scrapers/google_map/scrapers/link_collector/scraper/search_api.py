# Google Maps search engine (API mode).
#
# Two ways to search:
#   1. Single search  -> one GET to /search?tbm=map. Up to 20 results. Fast.
#   2. Tiled search    -> splits a bounding box into a grid, one GET per tile,
#                         dedupes by Place ID. Returns 100s of results.
#
# Reuses the parsing helpers in place_api.py - the search response embeds the
# same per-result structure as the place-detail API, so there's no duplicated
# parsing logic.

import json
import math
import time
import random
import logging
import requests
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

import settings
from .place_api import (
    extract_fields, strip_xssi, safe_get, new_session,
    USER_AGENT, REQUEST_TIMEOUT, MAX_RETRIES, BACKOFF_BASE, JITTER_RANGE,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (sourced from settings.py)
# ---------------------------------------------------------------------------

SEARCH_ENDPOINT = "https://www.google.com/search"

TILE_MAX_WORKERS = settings.TILE_MAX_WORKERS
DEFAULT_TILE_SIZE_DEG = settings.API_TILE_SIZE_DEG

# ---------------------------------------------------------------------------
# pb= template (only the variable parts are substituted per call)
# ---------------------------------------------------------------------------

PB_TEMPLATE = (
    "!4m12!1m3!1d{diameter}!2d{lng}!3d{lat}"
    "!2m3!1f0!2f0!3f0!3m2!1i{width}!2i{height}!4f{zoom}"
    "!7i{batch_size}!10b1"
    "!12m25!1m5!18b1!30b1!31m1!1b1!34e1!2m4!5m1!6e2!20e3!39b1!10b1!12b1!13b1!16b1!17m1!3e1!20m3!5e2!6b1!14b1!46m1!1b0!96b1!99b1"
    "!19m4!2m3!1i360!2i120!4i8"
    "!20m65!2m2!1i203!2i100!3m2!2i4!5b1!6m6!1m2!1i86!2i86!1m2!1i408!2i240"
    "!7m33!1m3!1e1!2b0!3e3!1m3!1e2!2b1!3e2!1m3!1e2!2b0!3e3!1m3!1e8!2b0!3e3"
    "!1m3!1e10!2b0!3e3!1m3!1e10!2b1!3e2!1m3!1e10!2b0!3e4!1m3!1e9!2b1!3e2!2b1!9b0"
    "!15m16!1m7!1m2!1m1!1e2!2m2!1i195!2i195!3i20!1m7!1m2!1m1!1e2!2m2!1i195!2i195!3i20"
    "!24m109!1m27!13m9!2b1!3b1!4b1!6i1!8b1!9b1!14b1!20b1!25b1"
    "!18m16!3b1!4b1!5b1!6b1!9b1!13b1!14b1!17b1!20b1!21b1!22b1!32b1!33m1!1b1!34b1!36e2"
    "!10m1!8e3!11m1!3e1!17b1!20m2!1e3!1e6!24b1!25b1!26b1!27b1!29b1!30m1!2b1!36b1!37b1"
    "!39m3!2m2!2i1!3i1!43b1!52b1!54m1!1b1!55b1!56m1!1b1!61m2!1m1!1e1"
    "!65m5!3m4!1m3!1m2!1i224!2i298"
    "!72m22!1m8!2b1!5b1!7b1!12m4!1b1!2b1!4m1!1e1!4b1!8m10!1m6!4m1!1e1!4m1!1e3!4m1!1e4"
    "!3sother_user_google_review_posts__and__hotel_and_vr_partner_review_posts!6m1!1e1!9b1"
    "!89b1!90m2!1m1!1e2!98m3!1b1!2b1!3b1!103b1!113b1!114m3!1b1!2m1!1b1!117b1!122m1!1b1!126b1!127b1!128m1!1b0"
    "!26m4!2m3!1i80!2i92!4i8"
    "!34m19!2b1!3b1!4b1!6b1!8m6!1b1!3b1!4b1!5b1!6b1!7b1!9b1!12b1!14b1!20b1!23b1!25b1!26b1!31b1"
    "!37m1!1e81!42b1!47m0!49m10!3b1!6m2!1b1!2b1!7m2!1e3!2b1!8b1!9b1!10e2"
    "!50m4!2e2!3m2!1b1!3b1!67m5!7b1!10b1!14b1!15m1!1b0!69i776!77b1"
)


# ---------------------------------------------------------------------------
# Geographic helpers
# ---------------------------------------------------------------------------

def zoom_to_diameter_m(zoom: float, lat: float) -> float:
    """Approximate viewport diameter in meters for a Maps zoom + latitude."""
    meters_per_px = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)
    return meters_per_px * 1024


def build_pb(query: str, lat: float, lng: float, zoom: float = 13.0,
             width: int = 1303, height: int = 945, batch_size: int = 20) -> str:
    """Substitute geographic and viewport values into the pb= template."""
    diameter = zoom_to_diameter_m(zoom, lat)
    return PB_TEMPLATE.format(
        diameter=f"{diameter:.6f}",
        lng=lng, lat=lat,
        width=width, height=height,
        zoom=zoom, batch_size=batch_size,
    )


def tile_grid(bbox: tuple[float, float, float, float],
              tile_size_deg: float) -> list[tuple[float, float]]:
    """Generate tile center points for a bounding box (lat_min,lng_min,lat_max,lng_max)."""
    lat_min, lng_min, lat_max, lng_max = bbox
    lats, lngs = [], []
    lat = lat_min + tile_size_deg / 2
    while lat < lat_max:
        lats.append(lat)
        lat += tile_size_deg
    lng = lng_min + tile_size_deg / 2
    while lng < lng_max:
        lngs.append(lng)
        lng += tile_size_deg
    return [(la, ln) for la in lats for ln in lngs]


# ---------------------------------------------------------------------------
# Response envelope handling
# ---------------------------------------------------------------------------

def unwrap_search_response(raw: str) -> list | None:
    """Strip the JS comment guard + XSSI prefix and parse the inner array."""
    text = raw.rstrip()
    if text.endswith('/*""*/'):
        text = text[:-6].rstrip()

    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("Failed to parse outer envelope: %s", e)
        return None

    inner = envelope.get("d", "")
    if not inner:
        log.error("Envelope missing 'd' field")
        return None

    inner = strip_xssi(inner)
    try:
        return json.loads(inner)
    except json.JSONDecodeError as e:
        log.error("Failed to parse inner JSON: %s", e)
        return None


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

def call_search_api(query: str, lat: float, lng: float, zoom: float,
                    session: requests.Session) -> str | None:
    """Make the /search?tbm=map call with retries and backoff."""
    pb_value = build_pb(query, lat, lng, zoom=zoom)
    params = {
        "tbm": "map",
        "authuser": "0",
        "hl": "en",
        "pb": pb_value,
        "q": query,
        "tch": "1",
        "ech": "1",
    }
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "referer": "https://www.google.com/maps/",
        "user-agent": USER_AGENT,
    }

    last_exc = None
    for attempt in range(MAX_RETRIES):
        time.sleep(random.uniform(*JITTER_RANGE))
        try:
            resp = session.get(SEARCH_ENDPOINT, params=params, headers=headers,
                               timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (429, 503):
                wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                log.warning("Got %d on '%s' near (%.4f,%.4f); backoff %.1fs (attempt %d)",
                            resp.status_code, query, lat, lng, wait, attempt + 1)
                time.sleep(wait)
                continue
            log.error("Search API returned %d for '%s' near (%.4f,%.4f)",
                      resp.status_code, query, lat, lng)
            return None
        except requests.RequestException as e:
            last_exc = e
            log.warning("Request error attempt %d: %s", attempt + 1, e)
            time.sleep(BACKOFF_BASE * (2 ** attempt))

    log.error("All retries exhausted for '%s' near (%.4f,%.4f): %s",
              query, lat, lng, last_exc)
    return None


# ---------------------------------------------------------------------------
# Result extraction
# ---------------------------------------------------------------------------

# Path to the businesses array within the inner JSON (verified 2026-04).
RESULTS_CONTAINER_PATH = [64]
ORGANIC_RESULT_SUBPATH = [1]
SPONSORED_RESULT_SUBPATH = [4, 1]


def build_place_url(name: str, lat: float, lng: float, hex_id: str,
                    fid: str | None = None) -> str:
    """Build a verbose Maps place URL that place_api.parse_maps_url can consume."""
    safe_name = quote(name.replace(" ", "+"), safe="+")
    base = (
        f"https://www.google.com/maps/place/{safe_name}/@{lat},{lng},17z/"
        f"data=!4m6!3m5!1s{hex_id}!8m2!3d{lat}!4d{lng}"
    )
    if fid:
        base += f"!16s{quote(fid, safe='')}"
    return base


def extract_links_from_response(parsed_response: list,
                                include_sponsored: bool = False) -> list[dict]:
    """Extract the minimal info needed to build a Maps URL for each result."""
    rows = []
    container = safe_get(parsed_response, RESULTS_CONTAINER_PATH)
    if not isinstance(container, list):
        return rows

    for item in container:
        if not isinstance(item, list):
            continue

        place_block = safe_get(item, ORGANIC_RESULT_SUBPATH)
        is_sponsored = False
        if not (isinstance(place_block, list) and len(place_block) > 11
                and isinstance(safe_get(place_block, [11]), str)):
            if include_sponsored:
                place_block = safe_get(item, SPONSORED_RESULT_SUBPATH)
                is_sponsored = True
            else:
                continue

        if not (isinstance(place_block, list) and len(place_block) > 11):
            continue

        name = safe_get(place_block, [11])
        lat = safe_get(place_block, [9, 2])
        lng = safe_get(place_block, [9, 3])
        hex_id = safe_get(place_block, [10])
        fid = safe_get(place_block, [89]) or safe_get(place_block, [227, 0, 3])
        cid = safe_get(place_block, [227, 0, 5])
        chij = safe_get(place_block, [227, 0, 4])

        if not (name and lat and lng and hex_id):
            continue

        url = build_place_url(name, lat, lng, hex_id, fid)
        rows.append({
            "Name": name,
            "URL": url,
            "CID": cid or "",
            "ChIJ Place ID": chij or "",
            "Latitude": lat,
            "Longitude": lng,
            "Sponsored": "Yes" if is_sponsored else "No",
        })

    return rows


def extract_results_from_response(parsed_response: list, query: str, lat: float,
                                  lng: float, include_sponsored: bool = False) -> list[dict]:
    """Run extract_fields on each business found (full ~35-field rows)."""
    results = []
    container = safe_get(parsed_response, RESULTS_CONTAINER_PATH)
    if not isinstance(container, list):
        log.warning("Results container missing or wrong type for '%s'", query)
        return results

    src_url = f"https://www.google.com/maps/search/{quote(query)}/@{lat},{lng},13z"

    for idx, item in enumerate(container):
        if not isinstance(item, list):
            continue

        place_block = safe_get(item, ORGANIC_RESULT_SUBPATH)
        is_sponsored = False
        if not (isinstance(place_block, list) and len(place_block) > 11
                and isinstance(safe_get(place_block, [11]), str)):
            if include_sponsored:
                place_block = safe_get(item, SPONSORED_RESULT_SUBPATH)
                is_sponsored = True
            else:
                continue

        if not (isinstance(place_block, list) and len(place_block) > 11):
            continue

        wrapper = [None] * 7
        wrapper[6] = place_block

        try:
            row = extract_fields(wrapper, src_url)
            row["Search Query"] = query
            row["Result Index"] = idx
            row["Sponsored"] = "Yes" if is_sponsored else "No"
            results.append(row)
        except Exception as e:
            log.warning("Failed to extract result %d for '%s': %s", idx, query, e)

    return results


# ---------------------------------------------------------------------------
# Top-level scraping functions
# ---------------------------------------------------------------------------

def scrape_search(query: str, lat: float, lng: float, zoom: float = 13.0,
                  include_sponsored: bool = False,
                  session: requests.Session | None = None) -> list[dict]:
    """Single search: one GET, up to 20 full-field business rows."""
    if session is None:
        session = new_session()

    raw = call_search_api(query, lat, lng, zoom, session)
    if not raw:
        return []
    parsed = unwrap_search_response(raw)
    if not parsed:
        return []
    return extract_results_from_response(parsed, query, lat, lng, include_sponsored)


def scrape_search_links(query: str, lat: float, lng: float, zoom: float = 13.0,
                        include_sponsored: bool = False,
                        session: requests.Session | None = None) -> list[dict]:
    """Lighter variant: returns just URL + minimal metadata per result."""
    if session is None:
        session = new_session()
    raw = call_search_api(query, lat, lng, zoom, session)
    if not raw:
        return []
    parsed = unwrap_search_response(raw)
    if not parsed:
        return []
    return extract_links_from_response(parsed, include_sponsored)


def scrape_search_links_tiled(query: str, bbox: tuple[float, float, float, float],
                              tile_size_deg: float = DEFAULT_TILE_SIZE_DEG,
                              zoom: float = 14.0,
                              include_sponsored: bool = False) -> list[dict]:
    """Tiled variant of scrape_search_links. Dedupes by CID across tiles."""
    centers = tile_grid(bbox, tile_size_deg)
    log.info("Tiling links for '%s' across %d tiles at zoom %.1f",
             query, len(centers), zoom)

    seen: set[str] = set()
    out: list[dict] = []

    def fetch_tile(c):
        return scrape_search_links(query, c[0], c[1], zoom=zoom,
                                   include_sponsored=include_sponsored)

    with ThreadPoolExecutor(max_workers=TILE_MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_tile, c): c for c in centers}
        for fut in tqdm(as_completed(futures), total=len(futures), desc="Tiles"):
            try:
                rows = fut.result()
            except Exception as e:
                log.error("Tile %s crashed: %s", futures[fut], e)
                continue
            for row in rows:
                key = row.get("CID") or row.get("ChIJ Place ID") or row.get("URL")
                if key and key not in seen:
                    seen.add(key)
                    out.append(row)

    log.info("Tiled link scrape: %d unique businesses across %d tile(s)",
             len(out), len(centers))
    return out
