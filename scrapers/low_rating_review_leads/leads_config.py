# =============================================================================
# LOW-RATING / NO-WEBSITE REVIEW-LEADS SCRAPER  —  settings
# =============================================================================
# Edit values here, then run:  python low_rating_review_leads/run_leads.py
#
# This scraper REUSES the three engines already in this project
# (scrapers/link_collector, scrapers/business_details, scrapers/email_scraper)
# and adds a "leads" layer on top:
#
#   keep a business when  ->  it has NO website   OR   its rating <= MAX_RATING
#   then                  ->  build a wa.me WhatsApp link from its phone
#   then                  ->  for the ones with no website, look up their
#                             Facebook / Instagram / LinkedIn by name (best effort)
#
# Named module `leads_config` (not `settings`) on purpose, so it never clashes
# with the two other `settings.py` files the reused engines import.
# -----------------------------------------------------------------------------

from pathlib import Path

HERE = Path(__file__).resolve().parent

# Path to the main "Google Maps & Contacts Scraper" project (the folder holding
# console.py and scrapers/). Leave as None to auto-detect: run_leads.py finds it
# whether this folder is INSIDE that project or sitting next to it. Only set it
# if auto-detect fails, e.g.:
#   PROJECT_ROOT = r"C:\Users\Administrator\Desktop\map leadas\Google Maps & Contacts Scraper Transfer"
PROJECT_ROOT = None


# ---------------------------------------------------------------------------
# 1. LEAD FILTER  — which businesses end up in the final sheet
# ---------------------------------------------------------------------------
# A row is KEPT if ANY enabled rule below matches it.
MAX_RATING = 4.0            # "low rating" = average rating at or below this
KEEP_IF_NO_WEBSITE = True   # keep every business with no website (any rating)
KEEP_IF_LOW_RATING = True   # keep every business rated <= MAX_RATING (any website)

# A business with no rating yet (0 reviews) is kept ONLY when it also has no
# website — otherwise there's no signal that it needs us.
KEEP_NO_RATING_ONLY_IF_NO_WEBSITE = True

REQUIRE_US = True           # drop rows whose Google "Country Code" isn't US

# The final sheet's "Website Type" column labels every row as one of:
#   none          - no website at all               -> prime lead
#   social-only   - "website" is just a FB / IG / Linktr.ee / business.site page
#   chain/booking - a corporate or aggregator domain (marriott.com, booking.com)
#   own           - its own real website
#
# "social-only" pages count as NO website (you can sell these a real site), and
# the social handle is captured for free.
SOCIAL_AS_NO_WEBSITE = True
SOCIAL_ONLY_DOMAINS = [
    "facebook.com", "instagram.com", "m.facebook.com", "linktr.ee",
    "business.site", "godaddysites.com", "wixsite.com", "weebly.com",
    "blogspot.com", "wordpress.com", "sites.google.com", "square.site",
    "linktree.ee", "beacons.ai", "carrd.co",
]

# Chains / booking / delivery aggregators. A row on one of these is treated as
# HAVING a website (so it's only kept when it is ALSO low-rated), never as a
# no-website lead. Set DROP_CHAIN_SITE_ROWS = True to leave them out entirely.
DROP_CHAIN_SITE_ROWS = False
CHAIN_OR_AGGREGATOR_DOMAINS = [
    # hotel chains
    "wyndhamhotels.com", "choicehotels.com", "hilton.com", "marriott.com",
    "ihg.com", "bestwestern.com", "bwhhotels.com", "hyatt.com",
    "radissonhotels.com", "motel6.com", "redroof.com", "sonesta.com",
    "extendedstayamerica.com", "g6hospitality.com", "oyorooms.com",
    "redlion.com", "drury-hotels.com", "myamericinn.com", "choicehotels.ca",
    # booking / listing / delivery aggregators
    "booking.com", "expedia.com", "hotels.com", "tripadvisor.com", "yelp.com",
    "trivago.com", "kayak.com", "priceline.com", "airbnb.com", "vrbo.com",
    "opentable.com", "doordash.com", "ubereats.com", "grubhub.com",
    "seamless.com", "slicelife.com", "toasttab.com", "chownow.com",
    "allmenus.com", "menupix.com", "zmenu.com", "restaurantji.com",
]


# ---------------------------------------------------------------------------
# 2. WHAT TO SEARCH
# ---------------------------------------------------------------------------
CATEGORIES_FILE = HERE / "input" / "categories.txt"   # one search term per line
LOCATIONS_FILE  = HERE / "input" / "states.txt"       # one location per line
# Every category is paired with every location -> "<category> in <location>".
# Default files: hotels + restaurants  x  all 50 US states  = 100 searches.


# ---------------------------------------------------------------------------
# 3. LINK COLLECTION
# ---------------------------------------------------------------------------
# "playwright" -> real browser, scrolls to ~120 results/search. Best coverage,
#                but Google will throw a /sorry/ CAPTCHA at the IP after a few
#                hundred requests. Use a residential proxy or small batches.
# "api"        -> Google's internal search endpoint. ~20 results/search (or 100s
#                in tiled mode). Faster, far more block-resistant, and it CAN
#                use the proxy below.
LINK_COLLECTOR = "api"

HEADLESS = True                 # playwright: False = watch the browser work
MAX_RESULTS_PER_SEARCH = 0      # playwright: 0 = scroll to end of list (~120)
PER_SEARCH_DELAY = 8.0          # seconds between searches (raise if blocked)
PAIR_LIMIT = 0                  # 0 = run every category x location.
                               # Small number = quick test (or `--test`).

# Proxy — used by API link collection AND business details. A rotating
# residential proxy is what makes a nationwide run survive without a CAPTCHA.
USE_PROXY = False
PROXY_URL = ""                  # "http://user:pass@host:port"  /  "socks5://..."

# API-mode knobs (only when LINK_COLLECTOR = "api")
API_TILE = False               # True = grid of requests per search (100s of
                               # results) instead of one (~20). Slower.
API_MAX_WORKERS = 1            # parallel searches; keep at 1-2 with a proxy


# ---------------------------------------------------------------------------
# 4. BUSINESS DETAILS
# ---------------------------------------------------------------------------
DETAIL_LEVEL = "detailed"       # "detailed" gives City / Region / Phone (E.164)
BUSINESS_MAX_WORKERS = 2        # keep low — Google rate-limits /maps/preview/*
                               # (uses USE_PROXY / PROXY_URL above when set)


# ---------------------------------------------------------------------------
# 5. WEBSITE CONTACT CRAWL  (only helps leads that DO have a website)
# ---------------------------------------------------------------------------
CRAWL_WEBSITES_FOR_CONTACTS = True
EMAIL_MODE = "single"           # "single" = best email per site, "all" = every one


# ---------------------------------------------------------------------------
# 6. NAME-BASED SOCIAL LOOKUP  (for leads with NO website)
# ---------------------------------------------------------------------------
# Best-effort web search by business name + city + state to find a Facebook,
# Instagram or LinkedIn page. This is a heuristic: it can miss, and it can
# occasionally grab the wrong page for a common name — treat results as leads
# to confirm, not gospel.
SOCIAL_LOOKUP_ENABLED = True
SOCIAL_LOOKUP_MAX = 0           # 0 = every lead missing socials; e.g. 400 to cap
SOCIAL_LOOKUP_DELAY = 2.5       # seconds between search queries (be polite)


# ---------------------------------------------------------------------------
# 7. OUTPUT
# ---------------------------------------------------------------------------
OUTPUT_DIR = HERE / "output"           # final leads_*.xlsx / .csv land here
WORK_DIR   = OUTPUT_DIR / "_work"      # intermediate link + details files
OUTPUT_NAME = ""                       # blank = auto: leads_YYYYmmdd_HHMMSS
