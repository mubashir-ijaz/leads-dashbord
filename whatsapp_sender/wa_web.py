"""
WhatsApp Web browser plumbing shared by check_whatsapp.py and send_whatsapp.py.
"""
import time
from urllib.parse import quote

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


def wait_until_logged_in(driver, timeout=180):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver.get("https://web.whatsapp.com")
    print("\nIf this is the first run, scan the QR code in the Chrome window with")
    print("your phone (WhatsApp > Linked devices > Link a device).")
    print(f"Waiting up to {timeout}s for WhatsApp Web to be ready...")
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located(
            (By.XPATH,
             '//div[@contenteditable="true"][@data-tab="3"] '
             '| //*[@aria-label="Search input textbox"] '
             '| //*[@aria-label="Chat list"]')
        )
    )
    print("WhatsApp Web is ready.\n")
    time.sleep(2)


# --------------------------------------------------------------------------- #
# Opening a number's chat
# --------------------------------------------------------------------------- #
_INVALID_TEXTS = (
    "Phone number shared via url is invalid",
    "isn't on WhatsApp",
    "is not on WhatsApp",
    "url is invalid",
)
_BOX_XPATH = ('//div[@contenteditable="true"][@data-tab="10"] '
              '| //footer//div[@contenteditable="true"]')


def _has_invalid_dialog(driver):
    from selenium.webdriver.common.by import By
    try:
        body = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return False
    return any(t.lower() in body.lower() for t in _INVALID_TEXTS)


def open_chat(driver, number: str, prefill: str = "", timeout: int = 30) -> str:
    """
    Navigate to a number's chat.
    Returns:
      'ready'    - chat open, compose box present (number is on WhatsApp)
      'invalid'  - WhatsApp says the number is not on WhatsApp
      'timeout'  - neither happened in time
    Sends nothing.
    """
    from selenium.webdriver.common.by import By

    url = f"https://web.whatsapp.com/send?phone={number}"
    if prefill:
        url += f"&text={quote(prefill)}"
    driver.get(url)

    end = time.time() + timeout
    while time.time() < end:
        if _has_invalid_dialog(driver):
            return "invalid"
        if driver.find_elements(By.XPATH, _BOX_XPATH):
            return "ready"
        time.sleep(1)
    return "timeout"


def send_current_chat(driver, number: str, message: str, timeout: int = 45) -> str:
    """Open the chat with the message prefilled, then send it. Returns 'sent' or 'error: ...'."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    state = open_chat(driver, number, prefill=message, timeout=timeout)
    if state == "invalid":
        return "invalid"
    if state != "ready":
        return "error: chat did not load"

    boxes = driver.find_elements(By.XPATH, _BOX_XPATH)
    if not boxes:
        return "error: no compose box"
    box = boxes[-1]
    try:
        box.click()
        time.sleep(0.5)
        box.send_keys(Keys.ENTER)
    except Exception:
        try:
            btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, '//button[@aria-label="Send"] | //span[@data-icon="send"]'))
            )
            btn.click()
        except TimeoutException:
            return "error: no send control"
    time.sleep(3)
    return "sent"
