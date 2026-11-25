# =============================================================================
# LINK COLLECTOR SETTINGS — edit this file, then run:  python run.py
# =============================================================================
# Everything you'd normally tweak for the LINK COLLECTOR lives here. You never
# need to touch the code in scraper/. Change a value, save, re-run.
#
# Inputs are read from   <project root>/input/link_collector/
# Outputs are written to <project root>/output/link_collector/
# -----------------------------------------------------------------------------

from pathlib import Path

# This file lives at <root>/scrapers/link_collector/settings.py, so the project
# root is two levels up. Paths below are built from the root so the scraper
# works no matter which directory you launch it from.
SCRAPER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRAPER_DIR.parent.parent


# -----------------------------------------------------------------------------
# 1. WHICH COLLECTOR TO USE
# -----------------------------------------------------------------------------
# "api"        -> Fast. Uses Google's internal search endpoint. ~20 results per
#                 query (single mode) or 100s (tiled mode). No browser needed.
# "playwright" -> Slower. Drives a real Chromium browser and scrolls the result
#                 list, breaking the 20-result cap (up to ~120 per query).
#
# Rule of thumb: "api" is fast (~20/query); "playwright" drives a real browser
# and returns more results per query (default).
COLLECTOR = "playwright"


# -----------------------------------------------------------------------------
# 2. INPUT / OUTPUT
# -----------------------------------------------------------------------------
INPUT_DIR = PROJECT_ROOT / "input" / "link_collector"
OUTPUT_DIR = PROJECT_ROOT / "output" / "link_collector"

# One "<category> in <location>" search is run for every category x location.
CATEGORIES_FILE = INPUT_DIR / "categories.txt"
LOCATIONS_FILE = INPUT_DIR / "locations.txt"

# Base name for the output files (without extension). Leave empty to auto-name
# each run with a timestamp, e.g. "links_20260628_164851". A custom value like
# "brooklyn_coffee" produces brooklyn_coffee.csv and brooklyn_coffee.xlsx.
OUTPUT_NAME = ""

# How many category x location searches to run. Each category is paired with
# each location, so 3 categories x 3 locations = 9 searches. 0 = run them all.
# Handy for a quick test: set to 1.
PAIR_LIMIT = 0

# Include sponsored / ad results. Usually leave False — ad URLs (/aclk) aren't
# directly usable by a place-detail scraper.
INCLUDE_SPONSORED = False


# -----------------------------------------------------------------------------
# 3. API COLLECTOR SETTINGS   (only used when COLLECTOR = "api")
# -----------------------------------------------------------------------------
# Single mode: one request per query, ~20 results.
# Tiled mode:  splits a map area into a grid and searches each tile, returning
#              100s of results. Set API_TILE = True and configure API_BBOX.
API_TILE = False

# How many "<category> in <location>" searches to run at the same time.
#   1 = one at a time (safest).
#   2-5 = noticeably faster on long category x location lists.
# Higher values finish sooner but hit Google's per-IP rate limits (HTTP 429)
# more often — back off if you start seeing 429 warnings. In tiled mode this
# multiplies with TILE_MAX_WORKERS (workers x tiles in flight), so keep it low.
API_MAX_WORKERS = 1

# --- Single mode (API_TILE = False) ---
# Search center. For "<category> in <location>" queries the exact center rarely
# matters — Google re-centers on the named location.
API_LAT = 40.6886459
API_LNG = -74.0020469
API_ZOOM = 13.0

# --- Tiled mode (API_TILE = True) ---
# Bounding box to cover: (lat_min, lng_min, lat_max, lng_max).
# Draw a rectangle on bboxfinder.com, copy as Lat/Lng, reorder to this layout.
#   Brooklyn NY  : (40.57, -74.04, 40.74, -73.83)
#   Manhattan NY : (40.70, -74.02, 40.88, -73.91)
#   Greater London: (51.28, -0.51, 51.69, 0.33)
API_BBOX = (40.57, -74.04, 40.74, -73.83)
API_TILE_SIZE_DEG = 0.04   # tile size in degrees (~4 km at NYC latitude)
API_TILE_ZOOM = 14.0       # higher zoom = more local results per tile


# -----------------------------------------------------------------------------
# 4. PLAYWRIGHT COLLECTOR SETTINGS   (only used when COLLECTOR = "playwright")
# -----------------------------------------------------------------------------
# Show the browser window? False = run hidden (headless). True = watch it work,
# useful for debugging.
HEADLESS = False

# Maximum results to collect per query. 0 = all (scroll to the end of the list).
# Set a number to stop early. Note: ~120 is Google's practical ceiling anyway.
MAX_RESULTS = 0

# Seconds to pause between queries, to look less robotic. 0 = no pause.
PER_PAIR_DELAY = 3.0


# -----------------------------------------------------------------------------
# 5. PROXY   (api mode; helps avoid per-IP rate limits / 429s)
# -----------------------------------------------------------------------------
# Flip USE_PROXY to True and fill in PROXY_URL (full URL incl. scheme + auth):
#   "http://user:pass@proxy.example.com:8000"
#   "socks5://user:pass@host:1080"   (needs: pip install requests[socks])
# Checked by default for API mode; ignored when COLLECTOR = "playwright".
USE_PROXY = False
PROXY_URL = ""

# -----------------------------------------------------------------------------
# 6. NETWORK TUNING   (api mode; advanced — defaults are sane)
# -----------------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = (10, 30)   # (connect, read) seconds
MAX_RETRIES = 3
BACKOFF_BASE = 1.5           # seconds; multiplied by 2**attempt on 429/503
JITTER_RANGE = (0.5, 2.0)    # random sleep before each request

# Tiled mode concurrency. Keep low — going higher invites 429s.
TILE_MAX_WORKERS = 2


# -----------------------------------------------------------------------------
# Helper used by the scraper — no need to edit.
# -----------------------------------------------------------------------------
def proxies_dict():
    """Return a requests-style proxies dict, or None when proxying is off."""
    if not USE_PROXY or not PROXY_URL:
        return None
    return {"http": PROXY_URL, "https": PROXY_URL}
