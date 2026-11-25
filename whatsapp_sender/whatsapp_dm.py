r"""
Walk the live dashboard page by page and click every lead's WhatsApp button,
one by one, waiting between each click. Unlike click_dashboard_whatsapp.py
(which only clicks whatever is on the current page), this one turns the
pager itself — you give it a page range and it clicks Next for you.

    python whatsapp_dm.py

It launches Chrome with its own dedicated profile (whatsapp_sender/chrome_profile
- same one send_whatsapp.py / check_whatsapp.py use), so it doesn't touch your
everyday Chrome and doesn't hit the "session not created" error recent Chrome
versions throw when automation tries to attach to your real default profile.

It does NOT log in to WhatsApp Web itself — it just clicks each lead's
WhatsApp button (opens the wa.me link in a new tab), waits, closes that tab,
then clicks the dashboard's Next-page button and repeats. Whatever you use on
your phone to pick up/track those numbers is on you; this script's only job
is: click -> wait -> close tab -> next page.

It opens the dashboard, gives you 20 seconds to log in (HTTP Basic Auth) and
pick the category / filters you want in the sidebar, then asks you three things:
  - seconds to wait after each WhatsApp click
  - which page to start on
  - which page to stop after
...then clicks every WhatsApp button on each of those pages, clicking to the
next page itself in between. Every click is logged to whatsapp_dm_clicks.csv.
"""
import csv
import sys
import time
from datetime import datetime

import config
import wa_web

CLICKS_CSV = config.HERE / "whatsapp_dm_clicks.csv"
LOGIN_WAIT_SECONDS = 20
PAGE_LOAD_TIMEOUT = 20
AFTER_PAGE_NAV_PAUSE = 1.5


def dashboard_url_with_auth():
    u = config.DASHBOARD_URL
    if config.DASHBOARD_USER and "://" in u:
        scheme, rest = u.split("://", 1)
        return f"{scheme}://{config.DASHBOARD_USER}:{config.DASHBOARD_PASS}@{rest}"
    return u


# ---------------------------------------------------------------------------
# input helpers
# ---------------------------------------------------------------------------

def ask_int(prompt, default, minimum=1):
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            n = int(raw)
        except ValueError:
            print("  That's not a whole number, try again.")
            continue
        if n < minimum:
            print(f"  Enter a number >= {minimum}.")
            continue
        return n


# ---------------------------------------------------------------------------
# dashboard interaction
# ---------------------------------------------------------------------------

def wait_for_grid(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
        EC.presence_of_element_located((By.ID, "grid")))


def wa_buttons(driver):
    from selenium.webdriver.common.by import By
    return driver.find_elements(By.CSS_SELECTOR, "a.a.wa")


def click_next_page(driver):
    """Click the pager's '>' button. False if there isn't one (last page)."""
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import NoSuchElementException

    try:
        btn = driver.find_element(
            By.XPATH,
            "//div[@id='pager']//button[contains(@class,'pg') and normalize-space(text())='›']")
    except NoSuchElementException:
        return False
    if btn.get_attribute("disabled") is not None or "off" in (btn.get_attribute("class") or ""):
        return False
    driver.execute_script("arguments[0].click();", btn)
    return True


def go_to_start_page(driver, start_page):
    if start_page <= 1:
        return
    print(f"Advancing to page {start_page}...")
    for _ in range(start_page - 1):
        if not click_next_page(driver):
            print("  Ran out of pages before reaching the start page.")
            return
        time.sleep(AFTER_PAGE_NAV_PAUSE)


def click_page(driver, main_handle, wait_seconds, close_tabs, page_no, writer, fh):
    from selenium.common.exceptions import StaleElementReferenceException

    buttons = wa_buttons(driver)
    total = len(buttons)
    if not total:
        print("    (no WhatsApp-able leads on this page)")
        return 0

    clicked = 0
    for i in range(total):
        try:
            btn = wa_buttons(driver)[i]
        except (IndexError, StaleElementReferenceException):
            print(f"    lead {i+1}/{total}: button no longer there, skipping")
            continue

        href = btn.get_attribute("href") or ""
        num = "".join(ch for ch in href.split("?")[0] if ch.isdigit())
        name = btn.get_attribute("data-id") or f"lead {i+1}"

        try:
            driver.switch_to.window(main_handle)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.3)
            before = set(driver.window_handles)
            btn.click()
            clicked += 1
            writer.writerow([datetime.now().isoformat(timespec="seconds"), page_no, i + 1, num, name, href])
            fh.flush()
            print(f"    page {page_no} · lead {i+1}/{total} · clicked WhatsApp for {name}")
            time.sleep(wait_seconds)
            if close_tabs:
                for h in driver.window_handles:
                    if h not in before and h != main_handle:
                        driver.switch_to.window(h)
                        driver.close()
                driver.switch_to.window(main_handle)
        except Exception as e:  # noqa: BLE001 - keep the run going no matter what
            print(f"    lead {i+1}/{total}: error ({e.__class__.__name__}), skipping")
            try:
                driver.switch_to.window(main_handle)
            except Exception:
                pass
    return clicked


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("=== whatsapp_dm.py - click every WhatsApp button, page by page ===\n")

    wait_seconds = ask_int("Seconds to wait after each WhatsApp click", config.CLICK_WAIT, minimum=1)
    start_page = ask_int("Start page", 1, minimum=1)
    end_page = ask_int("End page", start_page, minimum=start_page)
    close_tabs = True  # click -> wait -> close that tab -> next page, always

    print("\nOpening Chrome...")
    driver = wa_web.make_driver()
    main_handle = driver.current_window_handle

    print(f"Opening {config.DASHBOARD_URL} ...")
    driver.get(dashboard_url_with_auth())
    try:
        wait_for_grid(driver)
    except Exception:
        print("Dashboard did not load (check DASHBOARD_URL / login in config.py).")
        return

    print(f"\nYou have {LOGIN_WAIT_SECONDS} seconds - pick the category / filters "
          f"you want in the sidebar now.\n")
    for remaining in range(LOGIN_WAIT_SECONDS, 0, -1):
        sys.stdout.write(f"\r  starting in {remaining:2d}s... ")
        sys.stdout.flush()
        time.sleep(1)
    print("\r  starting now.              ")

    go_to_start_page(driver, start_page)

    new = not CLICKS_CSV.exists()
    fh = open(CLICKS_CSV, "a", newline="", encoding="utf-8")
    writer = csv.writer(fh)
    if new:
        writer.writerow(["timestamp", "page", "index_on_page", "number", "name", "href"])

    total_clicked = 0
    try:
        page = start_page
        while page <= end_page:
            print(f"\n--- Page {page} ---")
            try:
                wait_for_grid(driver)
            except Exception:
                print("  Page didn't load in time, stopping.")
                break
            total_clicked += click_page(driver, main_handle, wait_seconds, close_tabs, page, writer, fh)

            if page == end_page:
                break
            print("  Moving to next page...")
            if not click_next_page(driver):
                print("  No more pages - stopping early.")
                break
            time.sleep(AFTER_PAGE_NAV_PAUSE)
            page += 1
    except KeyboardInterrupt:
        print("\nStopped by you (Ctrl+C).")
    finally:
        fh.close()

    print(f"\nDone. clicked {total_clicked} WhatsApp buttons -> {CLICKS_CSV.name}")
    print("Chrome stays open - close it yourself when you're done reviewing.")


if __name__ == "__main__":
    main()
