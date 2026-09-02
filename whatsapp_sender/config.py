"""
Settings for the WhatsApp sender. Edit the values here - you should not need to
touch send_whatsapp.py.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

# ---------------------------------------------------------------------------
# Where the leads come from
# ---------------------------------------------------------------------------
# Default: the Excel file that sits next to this project.
LEADS_XLSX = PROJECT / "leads_20260827_160011.xlsx"

# Column names in that sheet (change only if your export uses different headers)
COL_NAME      = "Name"
COL_CATEGORY  = "Category"
COL_RATING    = "Rating"
COL_REVIEWS   = "Reviews"
COL_WHATSAPP  = "WhatsApp"
COL_PHONE     = "Phone"
COL_CITY      = "City"
COL_STATE     = "State"
COL_WHYKEPT   = "Why kept"

# ---------------------------------------------------------------------------
# The pitch - same tokens as the dashboard:
#   {name} {category} {city} {state} {reason}
# {reason} is filled automatically from the lead's segment.
# ---------------------------------------------------------------------------
PITCH_TEMPLATE = (
    "Hi {name} team! I noticed {reason}. I build fast, modern, mobile-friendly "
    "websites for {category}s that bring in more calls and bookings from Google. "
    "I'd love to send you a free homepage mockup - no cost, no obligation. "
    "Would that be OK?"
)

REASON_NO_WEBSITE = "your business doesn't have its own website yet"
REASON_LOW_RATING = "a few tough reviews lately"
REASON_DEFAULT    = "your online presence could pull in more customers"

# ---------------------------------------------------------------------------
# Which leads to message
# ---------------------------------------------------------------------------
SEGMENTS_TO_SEND = ["No website", "Low rating"]   # remove one to skip it
MIN_REVIEWS = 0        # skip leads with fewer than this many reviews
SKIP_RATING_ABOVE = None   # e.g. 4.5 to only message weaker listings; None = no cap

# Only use the "WhatsApp" column, never fall back to the plain "Phone" number.
# The scraper puts a wa.me link in that column for numbers it thinks have
# WhatsApp - but that is a guess. Run  check_whatsapp.py  to verify for real.
WHATSAPP_COLUMN_ONLY = True

# When whatsapp_numbers.csv exists (written by check_whatsapp.py), send_whatsapp.py
# messages ONLY the numbers confirmed to be on WhatsApp. Set False to ignore it.
USE_CHECKED_LIST = True

# ---------------------------------------------------------------------------
# Sending behaviour  (keep it slow - WhatsApp bans bulk senders)
# ---------------------------------------------------------------------------
DEFAULT_COUNTRY_CODE = "1"    # prepended to bare 10-digit numbers (US = 1)
STRICT_US_NUMBERS = True      # True: only accept 10-digit or 1+10-digit numbers,
                              # skip anything malformed (this dataset is US/PR).
                              # Set False if you add international leads.
MIN_DELAY_SECONDS = 25        # random pause between messages
MAX_DELAY_SECONDS = 55
BATCH_LIMIT = 25             # max messages per run; override with --limit / --all
SEND_TIMEOUT = 45            # seconds to wait for the chat + send button to load

# check_whatsapp.py behaviour (verifying, not sending -> can be a bit quicker)
CHECK_MIN_DELAY_SECONDS = 8
CHECK_MAX_DELAY_SECONDS = 18
CHECK_TIMEOUT = 30           # seconds to decide "on WhatsApp" vs "not"

# ---------------------------------------------------------------------------
# check_via_my_chrome.py  - drives YOUR normal Chrome / your existing WhatsApp
# Web login through Chrome's DevTools port. No QR scan, no separate profile.
# ---------------------------------------------------------------------------
PER_NUMBER_WAIT = 5          # seconds to wait on each chat before reading result
DEBUG_PORT = 9222           # Chrome remote-debugging port to launch / attach to

# click_dashboard_whatsapp.py - opens your live dashboard and clicks each
# WhatsApp button one by one.
DASHBOARD_URL  = "https://leads-dashbord.vercel.app/"
DASHBOARD_USER = "sam"       # HTTP Basic Auth login for the dashboard
DASHBOARD_PASS = "samsam"
CLICK_WAIT = 5              # seconds to wait after each button click
# Leave these None to auto-detect the standard Windows locations.
CHROME_BINARY = None        # e.g. r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_USER_DATA = None     # e.g. os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
CHROME_PROFILE = "Default"  # which profile folder inside User Data to use

# ---------------------------------------------------------------------------
# Files (all created next to this script)
# ---------------------------------------------------------------------------
SENT_LOG      = HERE / "sent_log.csv"        # numbers already messaged (resume list)
FAILED_LOG    = HERE / "failed_log.csv"      # numbers that errored / were invalid
PREVIEW_CSV   = HERE / "preview.csv"         # written by --dry-run so you can review
CHECKED_CSV   = HERE / "whatsapp_numbers.csv"    # numbers CONFIRMED on WhatsApp
NOT_ON_WA_CSV = HERE / "not_on_whatsapp.csv"     # numbers confirmed NOT on WhatsApp
CHROME_PROFILE_DIR = HERE / "chrome_profile"     # keeps you logged in to WhatsApp Web
