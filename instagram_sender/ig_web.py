"""
Instagram browser plumbing shared by instagram_dm.py.

Two ways to get a driver:
  make_driver()        - its own dedicated Chrome profile
                          (instagram_sender/chrome_profile), separate from
                          your everyday Chrome and from the WhatsApp runner's.
  get_real_chrome_driver(attach_only) - drives YOUR actual Chrome (real
                          profile, real cookies, already logged in) via its
                          remote-debugging port. Looks like a real person
                          browsing, not a fresh automation profile.
"""
import glob
import os
import shutil
import socket
import sys
import time

import config

# Selenium is imported lazily so --dry-run / --help work without it installed.


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument(f"--user-data-dir={config.CHROME_PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=opts)


# --------------------------------------------------------------------------- #
# real Chrome (your everyday browser) - same approach as
# whatsapp_sender/check_via_my_chrome.py
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


def get_real_chrome_driver(attach_only=False):
    """
    Returns (driver, we_started_it). Attaches to your real Chrome if it's
    already listening on config.DEBUG_PORT; otherwise launches it with your
    real profile + that port (unless attach_only, in which case it tells you
    how to start it yourself).
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        sys.exit("Missing dependency. Run:  pip install -r requirements.txt")

    port = config.DEBUG_PORT

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
            f"  (or double-click start_chrome_debug.bat)\n"
        )

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
            "instance per profile), or use --attach after starting it yourself\n"
            "(see start_chrome_debug.bat)."
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
            "Recent Chrome versions block launching it this way against your real\n"
            "profile (this is what 'session not created' with no other detail means).\n\n"
            "Use start_chrome_debug.bat instead:\n"
            '  1. Double-click "start_chrome_debug.bat"\n'
            "  2. Then run:  python instagram_dm.py --attach\n\n"
            "Full error:\n" + str(e)
        )
    return driver, True


def is_logged_in(driver, timeout=8):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    xpath = ('//a[contains(@href,"/direct/inbox/")] '
             '| //svg[@aria-label="Home"] '
             '| //span[@aria-label="Profile"]')
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# sending a DM on an already-open profile tab
# --------------------------------------------------------------------------- #
_MESSAGE_BTN_XPATH = (
    '//div[@role="button"][normalize-space(text())="Message"] '
    '| //button[normalize-space(text())="Message"] '
    '| //a[normalize-space(text())="Message"] '
    '| //div[@role="button"][.//div[normalize-space(text())="Message"]]'
)
_COMPOSE_BOX_XPATH = (
    '//div[@contenteditable="true"][contains(@aria-label,"Message")] '
    '| //textarea[contains(@aria-label,"Message")] '
    '| //div[@role="textbox"][@contenteditable="true"]'
)
_SEND_BTN_XPATH = (
    '//div[@role="button"][normalize-space(text())="Send"] '
    '| //button[normalize-space(text())="Send"]'
)


def find_message_button(driver, timeout=15):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, _MESSAGE_BTN_XPATH)))


def find_compose_box(driver, timeout=15):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, _COMPOSE_BOX_XPATH)))


def send_dm_on_open_tab(driver, timeout=15):
    """
    On an Instagram profile tab that is already open and the active tab:
    click "Message", paste whatever is on the clipboard (the dashboard copies
    the pitch there the moment you click the Instagram button) into the
    compose box, then send it.

    Returns one of:
      'sent'               - message sent
      'no_message_button'  - couldn't find/click "Message" (private/logged out/etc.)
      'no_compose_box'      - Message opened something but no text box appeared
      'error: <ExcName>'   - unexpected error
    """
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    try:
        btn = find_message_button(driver, timeout=timeout)
    except TimeoutException:
        return "no_message_button"
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(2)

    try:
        box = find_compose_box(driver, timeout=timeout)
    except TimeoutException:
        return "no_compose_box"

    try:
        box.click()
        time.sleep(0.3)
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.CONTROL, "v")
        time.sleep(0.6)
        box.send_keys(Keys.ENTER)
        time.sleep(1)
        # Some layouts need an explicit Send click instead of Enter.
        send_btns = driver.find_elements(By.XPATH, _SEND_BTN_XPATH)
        if send_btns:
            driver.execute_script("arguments[0].click();", send_btns[0])
    except Exception as e:  # noqa: BLE001 - keep the run going no matter what
        return f"error: {e.__class__.__name__}"
    time.sleep(1.5)
    return "sent"
