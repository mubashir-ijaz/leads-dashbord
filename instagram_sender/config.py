"""
Settings for the Instagram runner. Edit the values here - you should not need
to touch instagram_dm.py.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# The live dashboard this runner drives (same one the WhatsApp runner uses).
# ---------------------------------------------------------------------------
DASHBOARD_URL  = "https://leads-dashbord.vercel.app/"
DASHBOARD_USER = "sam"       # HTTP Basic Auth login for the dashboard
DASHBOARD_PASS = "samsam"

# ---------------------------------------------------------------------------
# Sending behaviour
# ---------------------------------------------------------------------------
CLICK_WAIT = 8               # default seconds to wait after each Instagram DM

# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------
# Its own dedicated profile - separate from the WhatsApp runner's, and from
# your everyday Chrome. Log in to Instagram here once; it's remembered after.
CHROME_PROFILE_DIR = HERE / "chrome_profile"

# ---------------------------------------------------------------------------
# --real-chrome / --attach  - drive YOUR actual Chrome (real profile, real
# cookies, already logged in to Instagram) instead of the dedicated profile
# above. Looks like a real person, not a fresh automation browser.
# ---------------------------------------------------------------------------
DEBUG_PORT = 9223            # different port than the WhatsApp runner's 9222,
                              # so both can run at the same time if you want
# Leave these None to auto-detect the standard Windows locations.
CHROME_BINARY = None         # e.g. r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_USER_DATA = None      # e.g. os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
CHROME_PROFILE = "Default"   # which profile folder inside User Data to use

# ---------------------------------------------------------------------------
# Files (created next to this script)
# ---------------------------------------------------------------------------
CLICKS_CSV = HERE / "instagram_dm_clicks.csv"    # every DM attempt, logged
