# =============================================================================
# BUSINESS DETAILS SETTINGS — edit this file, then run:  python run.py
# =============================================================================
# Tweakable settings for the business-details scraper (detail_scraper.py).
# Edit values here — no need to touch the scraper code.
#
# Inputs are read from   <project root>/input/business_details/
# Outputs are written to <project root>/output/business_details/
# -----------------------------------------------------------------------------

from pathlib import Path

# This file lives at <root>/scrapers/business_details/settings.py, so the
# project root is two levels up.
SCRAPER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRAPER_DIR.parent.parent


# ---------------------------------------------------------------------------
# Detail level
# ---------------------------------------------------------------------------
# "basic"    -> core fields only (name, phone, website, address, hours, rating).
# "detailed" -> everything basic, PLUS description, services, photos, CID/ChIJ
#               IDs, city/street/region, language, profile photo, and more.
# The interactive menu asks this each run; this value is the default.
DETAIL_LEVEL = "detailed"

# Optionally crawl each business website for emails / social handles and merge
# them into the output. None = off. The menu sets this; to enable by default set
# e.g. {"want_emails": True, "want_socials": True, "mode": "single"}  (mode:
# "single" = best email per site, "all" = every email found).
EMAIL_OPTIONS = None


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
INPUT_DIR = PROJECT_ROOT / "input" / "business_details"
OUTPUT_DIR = PROJECT_ROOT / "output" / "business_details"

# File containing one Google Maps place URL per line.
INPUT_FILE = INPUT_DIR / "links.txt"

# strftime pattern (without extension) used to build the output xlsx filename.
OUTPUT_FILENAME_PATTERN = "Google Maps - %d.%m.%Y %I.%M.%S %p"


# ---------------------------------------------------------------------------
# Proxy
# ---------------------------------------------------------------------------
# Flip to True to route all requests through PROXY_URL.
# PROXY_URL takes the complete URL, including scheme and (optional) auth, e.g.:
#   "http://user:pass@proxy.example.com:8000"
#   "http://127.0.0.1:8888"
#   "socks5://user:pass@host:1080"   # requires `pip install requests[socks]`
USE_PROXY = False
PROXY_URL = ""


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
PLACE_ENDPOINT = "https://www.google.com/maps/preview/place"


# ---------------------------------------------------------------------------
# Concurrency / retries
# ---------------------------------------------------------------------------
# Stay low. Google rate-limits /maps/preview/* aggressively.
MAX_WORKERS = 3
REQUEST_TIMEOUT = (10, 30)        # (connect, read) in seconds
MAX_RETRIES = 3                   # per-request retries (inside a single attempt)

# After the initial pass, any links that still failed are queued and retried as
# a batch. This repeats up to MAX_RETRY_CYCLES times (0 = no retry cycles);
# whatever is still failing afterwards is written to <name>_failed.txt.
MAX_RETRY_CYCLES = 5

# Emails/socials are gathered AFTER the Maps details, in one batched pass that
# crawls all business websites concurrently (much faster than crawling each
# site inline). This is how many websites to fetch at once. These requests are
# direct (no proxy) and async, so a high value is safe — raise it to go faster.
EMAIL_CONCURRENCY = 40
BACKOFF_BASE = 1.5                # seconds; multiplied by 2**attempt
JITTER_RANGE = (0.5, 2.0)         # random sleep before each request


# ---------------------------------------------------------------------------
# Request identity
# ---------------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

# Fallback session token used inside the pb= parameter when we can't extract a
# fresh `ei` from the Maps page. Captured once and may stale-out — replace by
# opening any Maps place page in DevTools and copying the value.
FALLBACK_EI_TOKEN = "Bv_uaZnSJYzPhbIP6M-uoQY"


def proxies_dict() -> dict | None:
    """Return a `requests`-style proxies dict, or None when proxying is off."""
    if not USE_PROXY or not PROXY_URL:
        return None
    return {"http": PROXY_URL, "https": PROXY_URL}
