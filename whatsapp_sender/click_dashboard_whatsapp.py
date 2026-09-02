r"""
Open your live dashboard and click every WhatsApp button, one by one, waiting a
few seconds between each.

    python click_dashboard_whatsapp.py                 # click them all
    python click_dashboard_whatsapp.py --limit 20      # just the first 20
    python click_dashboard_whatsapp.py --segment "No website"
    python click_dashboard_whatsapp.py --wait 6        # 6s between clicks
    python click_dashboard_whatsapp.py --keep-tabs     # don't auto-close the popups

It uses your normal Chrome (same as check_via_my_chrome.py):
  * close ALL Chrome windows and just run it, OR
  * run  start_chrome_debug.bat  then add  --attach

Each click opens the lead's wa.me link in a new tab; by default the script closes
that tab after WAIT seconds and moves to the next. Every click is written to
dashboard_clicks.csv.
"""
import argparse
import sys
import time
from datetime import datetime

import config
import leadlib
from check_via_my_chrome import get_driver

CLICKS_CSV = config.HERE / "dashboard_clicks.csv"


def dashboard_url_with_auth():
    u = config.DASHBOARD_URL
    if config.DASHBOARD_USER and "://" in u:
        scheme, rest = u.split("://", 1)
        return f"{scheme}://{config.DASHBOARD_USER}:{config.DASHBOARD_PASS}@{rest}"
    return u


def main():
    ap = argparse.ArgumentParser(description="Click every WhatsApp button on the dashboard.")
    ap.add_argument("--limit", type=int, default=None, help="max buttons to click")
    ap.add_argument("--segment", action="append",
                    help='only this segment (repeatable): "No website" / "Low rating"')
    ap.add_argument("--wait", type=float, default=None,
                    help=f"seconds between clicks (default {config.CLICK_WAIT})")
    ap.add_argument("--attach", action="store_true",
                    help="attach to a Chrome started with --remote-debugging-port")
    ap.add_argument("--keep-tabs", action="store_true",
                    help="do not close the wa.me tabs after each click")
    ap.add_argument("--yes", action="store_true", help='skip the "go" confirmation')
    args = ap.parse_args()

    wait = args.wait if args.wait is not None else config.CLICK_WAIT

    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver, _ = get_driver(attach_only=args.attach)
    main_handle = driver.current_window_handle

    print(f"Opening {config.DASHBOARD_URL} ...")
    driver.get(dashboard_url_with_auth())
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.a.wa, .card")))
    except Exception:
        print("Dashboard did not load (check the URL / login in config.py).")
        return
    time.sleep(2)

    # optional segment filter via the on-page chips
    if args.segment:
        for seg in args.segment:
            try:
                btn = driver.find_element(
                    By.CSS_SELECTOR, f'#segFilter button[data-seg="{seg}"]')
                btn.click()
                time.sleep(1.5)
            except Exception:
                print(f"(could not click segment chip {seg!r})")

    buttons = driver.find_elements(By.CSS_SELECTOR, "a.a.wa")
    if args.limit:
        buttons = buttons[: args.limit]
    if not buttons:
        print("No WhatsApp buttons found on the page.")
        return

    # snapshot href + card name up front (the DOM may change as tabs open)
    targets = []
    for b in buttons:
        href = b.get_attribute("href") or ""
        num = "".join(ch for ch in href.split("?")[0] if ch.isdigit())
        name = ""
        try:
            name = b.find_element(By.XPATH, './ancestor::div[contains(@class,"card")]//*[contains(@class,"name")]').text
        except Exception:
            pass
        targets.append((b, num, name))

    print(f"\n{len(targets)} WhatsApp buttons. Clicking one every {wait}s "
          f"(~{len(targets) * wait / 60:.0f} min).")
    if not args.yes and input('Type "go" to start: ').strip().lower() != "go":
        print("Cancelled.")
        return

    new = not CLICKS_CSV.exists()
    fh = open(CLICKS_CSV, "a", newline="", encoding="utf-8")
    import csv as _csv
    w = _csv.writer(fh)
    if new:
        w.writerow(["timestamp", "index", "number", "name", "href"])

    clicked = 0
    try:
        for i, (btn, num, name) in enumerate(targets, 1):
            print(f"[{i:>3}/{len(targets)}] +{num}  {name[:36]:<36} ", end="", flush=True)
            try:
                driver.switch_to.window(main_handle)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.4)
                before = set(driver.window_handles)
                btn.click()
                clicked += 1
                href = btn.get_attribute("href") or ""
                w.writerow([datetime.now().isoformat(timespec="seconds"), i, num, name, href])
                fh.flush()
                print("clicked")
                time.sleep(wait)
                if not args.keep_tabs:
                    for h in driver.window_handles:
                        if h not in before and h != main_handle:
                            driver.switch_to.window(h)
                            driver.close()
                    driver.switch_to.window(main_handle)
            except Exception as e:  # noqa: BLE001
                print(f"error: {e.__class__.__name__}")
                try:
                    driver.switch_to.window(main_handle)
                except Exception:
                    pass
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        fh.close()
        print(f"\nDone. clicked {clicked} buttons -> {CLICKS_CSV.name}")


if __name__ == "__main__":
    main()
