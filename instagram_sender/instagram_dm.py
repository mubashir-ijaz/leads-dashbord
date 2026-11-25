r"""
Walk the live dashboard page by page and DM every lead's Instagram, one by
one, waiting between each. Same idea as whatsapp_sender/whatsapp_dm.py, but
for the Instagram button: it clicks it (which also copies that lead's pitch
message to your clipboard - the dashboard does that itself), switches to the
new tab, clicks "Message" on the profile, pastes the copied pitch into the
compose box, sends it, closes the tab, then clicks the dashboard's Next-page
button and repeats.

    python instagram_dm.py

By default it launches Chrome with its own dedicated profile
(instagram_sender/chrome_profile), so it doesn't touch your everyday Chrome.
The first time you run it, log in to Instagram in that Chrome window when
prompted - it's remembered after that.

--------------------------------------------------------------------------------
WANT IT TO LOOK LIKE A REAL PERSON INSTEAD OF A FRESH BOT PROFILE?
--------------------------------------------------------------------------------
Drive YOUR actual Chrome (real profile, already logged in to Instagram):

A) Let the script start your real Chrome for you (easiest):

        python instagram_dm.py --real-chrome

    Close all Chrome windows first (Chrome allows only one instance per profile).

B) Start Chrome yourself with the debug port, then attach (Chrome can stay open):

        start_chrome_debug.bat            (double-click it)
        python instagram_dm.py --attach

--------------------------------------------------------------------------------

It opens the dashboard, gives you time to log in (HTTP Basic Auth), pick the
category / filters you want in the sidebar, and confirm you're logged in to
Instagram, then asks you three things:
  - seconds to wait after each Instagram DM
  - which page to start on
  - which page to stop after
...then DMs every Instagram-able lead on each of those pages, clicking to the
next page itself in between. Every attempt is logged to instagram_dm_clicks.csv.
"""
import argparse
import csv
import sys
import time
from datetime import datetime

import config
import ig_web

LOGIN_WAIT_SECONDS = 25
PAGE_LOAD_TIMEOUT = 20
AFTER_PAGE_NAV_PAUSE = 1.5
AFTER_IG_CLICK_PAUSE = 1.5  # let the new tab open + clipboard copy land before we switch to it


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


def ig_buttons(driver):
    from selenium.webdriver.common.by import By
    return driver.find_elements(By.CSS_SELECTOR, "a.a.ig")


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


def click_page(driver, main_handle, wait_seconds, page_no, writer, fh):
    from selenium.common.exceptions import StaleElementReferenceException

    buttons = ig_buttons(driver)
    total = len(buttons)
    if not total:
        print("    (no Instagram-able leads on this page)")
        return 0

    sent = 0
    for i in range(total):
        try:
            btn = ig_buttons(driver)[i]
        except (IndexError, StaleElementReferenceException):
            print(f"    lead {i+1}/{total}: button no longer there, skipping")
            continue

        href = btn.get_attribute("href") or ""
        name = btn.get_attribute("data-id") or f"lead {i+1}"

        try:
            driver.switch_to.window(main_handle)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.3)
            before = set(driver.window_handles)
            btn.click()  # opens the profile in a new tab AND copies the pitch to the clipboard
            time.sleep(AFTER_IG_CLICK_PAUSE)

            new_handles = [h for h in driver.window_handles if h not in before]
            if not new_handles:
                print(f"    page {page_no} · lead {i+1}/{total} · {name}: no new tab opened, skipping")
                status = "no_tab"
            else:
                driver.switch_to.window(new_handles[0])
                status = ig_web.send_dm_on_open_tab(driver)
                if status == "sent":
                    sent += 1
                print(f"    page {page_no} · lead {i+1}/{total} · {name}: {status}")
                driver.close()

            writer.writerow([datetime.now().isoformat(timespec="seconds"), page_no, i + 1, name, href, status])
            fh.flush()
            driver.switch_to.window(main_handle)
            time.sleep(wait_seconds)
        except Exception as e:  # noqa: BLE001 - keep the run going no matter what
            print(f"    lead {i+1}/{total}: error ({e.__class__.__name__}), skipping")
            try:
                driver.switch_to.window(main_handle)
            except Exception:
                pass
    return sent


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Walk the dashboard and DM every Instagram lead.")
    ap.add_argument("--real-chrome", action="store_true",
                     help="drive YOUR actual Chrome (real profile, already logged in) "
                          "instead of the dedicated automation profile")
    ap.add_argument("--attach", action="store_true",
                     help="attach to a real Chrome you already started with "
                          "--remote-debugging-port (see start_chrome_debug.bat)")
    args = ap.parse_args()
    use_real_chrome = args.real_chrome or args.attach

    print("=== instagram_dm.py - DM every Instagram lead, page by page ===\n")

    wait_seconds = ask_int("Seconds to wait after each Instagram DM", config.CLICK_WAIT, minimum=1)
    start_page = ask_int("Start page", 1, minimum=1)
    end_page = ask_int("End page", start_page, minimum=start_page)

    print("\nOpening Chrome...")
    if use_real_chrome:
        driver, we_started = ig_web.get_real_chrome_driver(attach_only=args.attach)
    else:
        driver, we_started = ig_web.make_driver(), True
    main_handle = driver.current_window_handle

    print(f"Opening {config.DASHBOARD_URL} ...")
    driver.get(dashboard_url_with_auth())
    try:
        wait_for_grid(driver)
    except Exception:
        print("Dashboard did not load (check DASHBOARD_URL / login in config.py).")
        return

    # With --real-chrome / --attach you're presumably already logged in to
    # Instagram in that browser, so only pop a check tab if we can't confirm it.
    check_handle = None
    already_logged_in = False
    if use_real_chrome:
        try:
            driver.switch_to.new_window("tab")
            check_handle = driver.current_window_handle
            driver.get("https://www.instagram.com/")
            already_logged_in = ig_web.is_logged_in(driver, timeout=6)
        except Exception:
            pass
        finally:
            driver.switch_to.window(main_handle)

    if already_logged_in:
        print("\nLooks like you're already logged in to Instagram on this Chrome. "
              f"You have {LOGIN_WAIT_SECONDS} seconds to pick the category / filters "
              "you want in the sidebar.\n")
    else:
        print(f"\nYou have {LOGIN_WAIT_SECONDS} seconds - pick the category / filters you want "
              "in the sidebar, and make sure you're logged in to Instagram in this Chrome window "
              "(a check tab is opening now; log in there if asked, then come back to the "
              "dashboard tab).\n")
        if not use_real_chrome:
            try:
                driver.switch_to.new_window("tab")
                check_handle = driver.current_window_handle
                driver.get("https://www.instagram.com/")
            except Exception:
                pass
            finally:
                driver.switch_to.window(main_handle)

    for remaining in range(LOGIN_WAIT_SECONDS, 0, -1):
        sys.stdout.write(f"\r  starting in {remaining:2d}s... ")
        sys.stdout.flush()
        time.sleep(1)
    print("\r  starting now.              ")

    if check_handle and check_handle in driver.window_handles:
        driver.switch_to.window(check_handle)
        driver.close()
        driver.switch_to.window(main_handle)

    go_to_start_page(driver, start_page)

    new = not config.CLICKS_CSV.exists()
    fh = open(config.CLICKS_CSV, "a", newline="", encoding="utf-8")
    writer = csv.writer(fh)
    if new:
        writer.writerow(["timestamp", "page", "index_on_page", "name", "href", "status"])

    total_sent = 0
    try:
        page = start_page
        while page <= end_page:
            print(f"\n--- Page {page} ---")
            try:
                wait_for_grid(driver)
            except Exception:
                print("  Page didn't load in time, stopping.")
                break
            total_sent += click_page(driver, main_handle, wait_seconds, page, writer, fh)

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

    print(f"\nDone. sent {total_sent} Instagram DMs -> {config.CLICKS_CSV.name}")
    print("Chrome stays open - close it yourself when you're done reviewing.")


if __name__ == "__main__":
    main()
