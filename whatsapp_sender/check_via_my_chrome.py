r"""
Check which lead numbers are on WhatsApp using YOUR normal Chrome and YOUR
existing WhatsApp Web / WhatsApp login - no QR scan, no separate "scraping"
profile.

It opens https://web.whatsapp.com/send?phone=<number> for each lead, one by one,
waits PER_NUMBER_WAIT seconds (default 5), then reads whether WhatsApp shows the
"not on WhatsApp" message or the chat. It SENDS NOTHING.

--------------------------------------------------------------------------------
TWO WAYS TO RUN
--------------------------------------------------------------------------------
A)  Let the script start Chrome for you (easiest):

        python check_via_my_chrome.py

    Close all Chrome windows first (Chrome allows only one instance per profile).
    The script starts Chrome with your normal profile + a debugging port, so your
    WhatsApp Web login is already there.

B)  Start Chrome yourself with the port, then attach:

        "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data"
        python check_via_my_chrome.py --attach

--------------------------------------------------------------------------------
    python check_via_my_chrome.py --limit 20         # test 20 numbers
    python check_via_my_chrome.py --segment "No website"
    python check_via_my_chrome.py --wait 7           # wait 7s per number
    python check_via_my_chrome.py --summary          # progress from the CSVs, no browser

Results (next to this script):
    whatsapp_numbers.csv   - CONFIRMED on WhatsApp   <- send_whatsapp.py uses this
    not_on_whatsapp.csv    - CONFIRMED not on WhatsApp
Stop with Ctrl+C any time; checked numbers are skipped next run.
"""
import argparse
import glob
import os
import shutil
import socket
import sys
import time

import config
import leadlib
from check_whatsapp import print_summary


# --------------------------------------------------------------------------- #
# locating Chrome
# --------------------------------------------------------------------------- #
def find_chrome_binary():
    if config.CHROME_BINARY and os.path.isfile(config.CHROME_BINARY):
        return config.CHROME_BINARY
    candidates = [
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def find_user_data_dir():
    if config.CHROME_USER_DATA and os.path.isdir(config.CHROME_USER_DATA):
        return config.CHROME_USER_DATA
    guess = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    return guess if os.path.isdir(guess) else None


def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.7)
        return s.connect_ex(("127.0.0.1", port)) == 0


def chrome_running_on_profile(user_data_dir):
    """True if a chrome.exe already locks this profile (rough check via lock file)."""
    if not user_data_dir:
        return False
    for lock in ("lockfile", "SingletonLock", "SingletonCookie"):
        if glob.glob(os.path.join(user_data_dir, lock)):
            return True
    return False


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def get_driver(attach_only):
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
    except ImportError:
        sys.exit("Missing dependency. Run:  pip install -r requirements.txt")

    port = config.DEBUG_PORT

    # already have a Chrome listening on the port -> just attach
    if port_open(port):
        print(f"Attaching to Chrome already on 127.0.0.1:{port} ...")
        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
        return webdriver.Chrome(options=opts), False

    if attach_only:
        chrome = find_chrome_binary() or "chrome.exe"
        ud = find_user_data_dir() or os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
        sys.exit(
            f"Nothing is listening on port {port}. Start Chrome first:\n\n"
            f'  "{chrome}" --remote-debugging-port={port} --user-data-dir="{ud}"\n'
        )

    # launch Chrome ourselves with the normal profile + the port
    binary = find_chrome_binary()
    user_data = find_user_data_dir()
    if not binary:
        sys.exit("Could not find chrome.exe - set CHROME_BINARY in config.py.")
    if not user_data:
        sys.exit("Could not find your Chrome 'User Data' folder - set CHROME_USER_DATA in config.py.")
    if chrome_running_on_profile(user_data):
        sys.exit(
            "Chrome is already running with your normal profile.\n"
            "Close ALL Chrome windows and run this again (Chrome only allows one\n"
            "instance per profile), or use option B with --attach."
        )

    print(f"Starting Chrome\n  {binary}\n  profile: {user_data}\\{config.CHROME_PROFILE}\n  port: {port}")
    opts = Options()
    opts.binary_location = binary
    opts.add_argument(f"--remote-debugging-port={port}")
    opts.add_argument(f"--user-data-dir={user_data}")
    opts.add_argument(f"--profile-directory={config.CHROME_PROFILE}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as e:  # noqa: BLE001
        sys.exit(
            f"Could not start Chrome with your profile ({e.__class__.__name__}).\n"
            "Make sure every Chrome window is closed, then retry.\n"
            "Details: " + str(e).splitlines()[0]
        )
    return driver, True


# --------------------------------------------------------------------------- #
# checking one number
# --------------------------------------------------------------------------- #
_INVALID = (
    "phone number shared via url is invalid",
    "isn't on whatsapp",
    "is not on whatsapp",
    "url is invalid",
)


def classify(driver, wait):
    """Return 'on_whatsapp' | 'not_on_whatsapp' | 'unknown' after waiting."""
    from selenium.webdriver.common.by import By

    time.sleep(wait)
    for _ in range(2):  # small grace re-check
        try:
            body = driver.find_element(By.TAG_NAME, "body").text.lower()
        except Exception:
            body = ""
        if any(t in body for t in _INVALID):
            return "not_on_whatsapp"
        boxes = driver.find_elements(
            By.XPATH,
            '//footer//div[@contenteditable="true"] '
            '| //div[@contenteditable="true"][@data-tab="10"]',
        )
        if boxes:
            return "on_whatsapp"
        time.sleep(2)
    return "unknown"


def ensure_logged_in(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver.get("https://web.whatsapp.com")
    try:
        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@aria-label="Chat list"] | //*[@aria-label="Search input textbox"] '
                 '| //div[@contenteditable="true"][@data-tab="3"]'))
        )
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Check numbers on WhatsApp via your own Chrome.")
    ap.add_argument("--limit", type=int, default=None, help="max numbers this run")
    ap.add_argument("--segment", action="append",
                    help='only this segment (repeatable): "No website" / "Low rating"')
    ap.add_argument("--wait", type=float, default=None,
                    help=f"seconds to wait per number (default {config.PER_NUMBER_WAIT})")
    ap.add_argument("--attach", action="store_true",
                    help="attach to a Chrome you already started with --remote-debugging-port")
    ap.add_argument("--recheck", action="store_true", help="re-check numbers already done")
    ap.add_argument("--summary", action="store_true", help="progress from the CSVs, no browser")
    ap.add_argument("--yes", action="store_true", help='skip the "go" confirmation')
    args = ap.parse_args()

    if args.summary:
        print_summary()
        return

    if not config.LEADS_XLSX.exists():
        sys.exit(f"Leads file not found: {config.LEADS_XLSX}")

    wait = args.wait if args.wait is not None else config.PER_NUMBER_WAIT
    leads = leadlib.load_leads(segment_filter=args.segment, apply_send_filters=False)

    done = set()
    if not args.recheck:
        done = leadlib.read_numbers(config.CHECKED_CSV) | leadlib.read_numbers(config.NOT_ON_WA_CSV)
    pending = [l for l in leads if l["number"] not in done]
    if args.limit:
        pending = pending[: args.limit]

    print(f"{len(leads)} leads with a number  |  {len(done)} already checked  "
          f"|  {len(pending)} to check now  |  {wait}s each")
    if not pending:
        print("Nothing to check.")
        return
    est = len(pending) * (wait + 4) / 60
    if not args.yes:
        if input(f'Type "go" to check {len(pending)} numbers (~{est:.0f} min): ').strip().lower() != "go":
            print("Cancelled.")
            return

    driver, we_started = get_driver(attach_only=args.attach)
    yes = no = unknown = 0
    started = time.time()
    try:
        if not ensure_logged_in(driver):
            print("\nWhatsApp Web is not logged in on this Chrome profile.")
            print("Log in once (scan the QR in the window), then run this again.")
            return
        print("WhatsApp Web ready. Checking...\n")

        main_handle = driver.current_window_handle
        for i, lead in enumerate(pending, 1):
            print(f"[{i:>3}/{len(pending)}] +{lead['number']}  {lead['name'][:32]:<32} ",
                  end="", flush=True)
            try:
                driver.switch_to.new_window("tab")
                driver.get(f"https://web.whatsapp.com/send?phone={lead['number']}")
                state = classify(driver, wait)
            except Exception as e:  # noqa: BLE001
                state = f"error:{e.__class__.__name__}"
            finally:
                try:
                    if driver.current_window_handle != main_handle:
                        driver.close()
                    driver.switch_to.window(main_handle)
                except Exception:
                    pass

            if state == "on_whatsapp":
                yes += 1
                leadlib.log_check(config.CHECKED_CSV, lead, "on_whatsapp")
                tag = "ON WhatsApp"
            elif state == "not_on_whatsapp":
                no += 1
                leadlib.log_check(config.NOT_ON_WA_CSV, lead, "not_on_whatsapp")
                tag = "not on WhatsApp"
            else:
                unknown += 1
                tag = state

            rate = yes / (yes + no) * 100 if (yes + no) else 0
            eta = (time.time() - started) / i * (len(pending) - i) / 60
            print(f"{tag:<16} | on WA {yes}/{yes + no} ({rate:.0f}%) | ETA {eta:4.0f}m", flush=True)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        total_yes = len(leadlib.read_numbers(config.CHECKED_CSV))
        print(f"\nThis run:  on WhatsApp={yes}  not={no}  unknown={unknown}")
        print(f"Confirmed on WhatsApp so far: {total_yes}  ->  {config.CHECKED_CSV.name}")
        if we_started:
            print("(Leaving your Chrome open.)")


if __name__ == "__main__":
    main()
