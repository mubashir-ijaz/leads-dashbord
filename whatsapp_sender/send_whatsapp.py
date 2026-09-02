"""
Bulk WhatsApp sender for the leads list.

It reads the same leads the dashboard uses, builds the same personalised pitch,
and sends it on WhatsApp Web one number at a time with human-like pauses.

    python send_whatsapp.py --dry-run          # build messages, write preview.csv, send nothing
    python send_whatsapp.py                     # send up to BATCH_LIMIT (config.py)
    python send_whatsapp.py --limit 5           # send only 5 this run
    python send_whatsapp.py --all               # ignore the batch limit
    python send_whatsapp.py --segment "No website"

First real run opens Chrome -> scan the WhatsApp QR code with your phone once.
The login is remembered in ./chrome_profile so later runs go straight through.
Numbers already in sent_log.csv are skipped, so you can stop and re-run any time.

WARNING: sending unsolicited bulk messages can get your WhatsApp number banned.
Keep batches small, keep the delays, and only message real prospects.
"""
import argparse
import csv
import math
import random
import sys
import time
from datetime import datetime
from urllib.parse import quote

import config

try:
    import pandas as pd
except ImportError:
    sys.exit("Missing dependency. Run:  pip install -r requirements.txt")


# --------------------------------------------------------------------------- #
# Leads
# --------------------------------------------------------------------------- #
def _clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def segment_of(why_kept: str, rating) -> str:
    wk = why_kept.lower()
    if "no website" in wk or "social page only" in wk or "social" in wk:
        return "No website"
    if "low rating" in wk:
        return "Low rating"
    try:
        if rating and float(rating) < 4.2:
            return "Low rating"
    except (TypeError, ValueError):
        pass
    return "No website"


def reason_for(seg: str, rating) -> str:
    if seg == "No website":
        return config.REASON_NO_WEBSITE
    if seg == "Low rating":
        extra = f" ({rating}★)" if _clean(rating) else ""
        return config.REASON_LOW_RATING + extra
    return config.REASON_DEFAULT


def normalise_number(whatsapp: str, phone: str) -> str:
    """Return digits only, with a country code. '' if it can't be trusted."""
    # A wa.me link was built by the scraper from a valid number - trust it.
    if "wa.me" in (whatsapp or "").lower():
        d = "".join(ch for ch in whatsapp if ch.isdigit())
        return d if 11 <= len(d) <= 15 else ""

    raw = whatsapp or phone or ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10:
        return config.DEFAULT_COUNTRY_CODE + digits
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    if config.STRICT_US_NUMBERS:
        return ""            # malformed for a US/PR dataset - skip it
    return digits if 8 <= len(digits) <= 15 else ""


def build_message(lead: dict) -> str:
    msg = config.PITCH_TEMPLATE
    msg = msg.replace("{name}", lead["name"] or "there")
    msg = msg.replace("{category}", (lead["category"] or "business").lower())
    msg = msg.replace("{city}", lead["city"])
    msg = msg.replace("{state}", lead["state"])
    msg = msg.replace("{reason}", reason_for(lead["segment"], lead["rating"]))
    return " ".join(msg.split())


def load_leads(segment_filter=None):
    df = pd.read_excel(config.LEADS_XLSX)
    out = []
    for _, r in df.iterrows():
        why = _clean(r.get(config.COL_WHYKEPT))
        rating = _clean(r.get(config.COL_RATING))
        seg = segment_of(why, rating)
        lead = {
            "name": _clean(r.get(config.COL_NAME)),
            "category": _clean(r.get(config.COL_CATEGORY)),
            "rating": rating,
            "reviews": int(float(_clean(r.get(config.COL_REVIEWS)) or 0)),
            "city": _clean(r.get(config.COL_CITY)),
            "state": _clean(r.get(config.COL_STATE)),
            "segment": seg,
            "number": normalise_number(
                _clean(r.get(config.COL_WHATSAPP)), _clean(r.get(config.COL_PHONE))
            ),
        }
        if not lead["name"] or not lead["number"]:
            continue
        wanted = segment_filter or config.SEGMENTS_TO_SEND
        if seg not in wanted:
            continue
        if lead["reviews"] < config.MIN_REVIEWS:
            continue
        if config.SKIP_RATING_ABOVE and rating:
            try:
                if float(rating) > config.SKIP_RATING_ABOVE:
                    continue
            except ValueError:
                pass
        lead["message"] = build_message(lead)
        out.append(lead)
    # de-dupe by number, keep first
    seen, uniq = set(), []
    for l in out:
        if l["number"] in seen:
            continue
        seen.add(l["number"])
        uniq.append(l)
    return uniq


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #
def load_done() -> set:
    done = set()
    if config.SENT_LOG.exists():
        with open(config.SENT_LOG, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add(row["number"])
    return done


def log_row(path, lead, status):
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "number", "name", "segment", "status", "message"])
        w.writerow([datetime.now().isoformat(timespec="seconds"),
                    lead["number"], lead["name"], lead["segment"], status, lead["message"]])


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #
def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument(f"--user-data-dir={config.CHROME_PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=opts)


def wait_until_logged_in(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver.get("https://web.whatsapp.com")
    print("\nIf this is the first run, scan the QR code in the Chrome window with")
    print("your phone (WhatsApp > Linked devices > Link a device).")
    print("Waiting up to 3 minutes for WhatsApp Web to be ready...")
    WebDriverWait(driver, 180).until(
        EC.presence_of_element_located(
            (By.XPATH, '//div[@contenteditable="true"][@data-tab="3"] | //*[@aria-label="Search input textbox"]')
        )
    )
    print("WhatsApp Web is ready.\n")
    time.sleep(2)


def send_one(driver, number: str, message: str) -> str:
    """Returns 'sent', 'invalid', or 'error: ...'."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    url = f"https://web.whatsapp.com/send?phone={number}&text={quote(message)}"
    driver.get(url)

    invalid_xpath = ('//div[contains(., "Phone number shared via url is invalid") or '
                     'contains(., "invalid") and @role="dialog"]')
    box_xpath = '//div[@contenteditable="true"][@data-tab="10"] | //footer//div[@contenteditable="true"]'

    end = time.time() + config.SEND_TIMEOUT
    box = None
    while time.time() < end:
        try:
            if driver.find_elements(By.XPATH, '//*[contains(text(),"Phone number shared via url is invalid")]'):
                return "invalid"
        except Exception:
            pass
        els = driver.find_elements(By.XPATH, box_xpath)
        if els:
            box = els[-1]
            break
        time.sleep(1)

    if box is None:
        return "error: chat did not load"

    try:
        box.click()
        time.sleep(0.5)
        box.send_keys(Keys.ENTER)
    except Exception:
        # fallback: click the send button
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


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Bulk WhatsApp sender for the leads list.")
    ap.add_argument("--dry-run", action="store_true",
                    help="build messages, write preview.csv, send nothing")
    ap.add_argument("--limit", type=int, default=None,
                    help="max messages this run (default: BATCH_LIMIT in config.py)")
    ap.add_argument("--all", action="store_true", help="ignore the batch limit")
    ap.add_argument("--segment", action="append",
                    help='only this segment (repeatable): "No website" or "Low rating"')
    args = ap.parse_args()

    if not config.LEADS_XLSX.exists():
        sys.exit(f"Leads file not found: {config.LEADS_XLSX}")

    leads = load_leads(segment_filter=args.segment)
    done = load_done()
    pending = [l for l in leads if l["number"] not in done]

    print(f"{len(leads)} leads with a WhatsApp/phone number "
          f"(segments: {args.segment or config.SEGMENTS_TO_SEND})")
    print(f"{len(done)} already sent (sent_log.csv) -> {len(pending)} still to send")

    if args.dry_run:
        with open(config.PREVIEW_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["number", "name", "segment", "rating", "reviews", "city", "state", "message"])
            for l in pending:
                w.writerow([l["number"], l["name"], l["segment"], l["rating"],
                            l["reviews"], l["city"], l["state"], l["message"]])
        print(f"\nDRY RUN - wrote {len(pending)} rows to {config.PREVIEW_CSV}")
        for l in pending[:3]:
            print(f"\n  -> +{l['number']}  ({l['name']})\n     {l['message']}")
        if len(pending) > 3:
            print(f"\n  ...and {len(pending) - 3} more in preview.csv")
        return

    limit = None if args.all else (args.limit or config.BATCH_LIMIT)
    batch = pending if limit is None else pending[:limit]
    if not batch:
        print("Nothing to send.")
        return

    print(f"\nAbout to send {len(batch)} messages, "
          f"{config.MIN_DELAY_SECONDS}-{config.MAX_DELAY_SECONDS}s apart.")
    if input('Type "go" to start: ').strip().lower() != "go":
        print("Cancelled.")
        return

    driver = make_driver()
    sent = failed = 0
    try:
        wait_until_logged_in(driver)
        for i, lead in enumerate(batch, 1):
            print(f"[{i}/{len(batch)}] +{lead['number']}  {lead['name'][:40]:<40} ", end="", flush=True)
            try:
                status = send_one(driver, lead["number"], lead["message"])
            except Exception as e:  # noqa: BLE001
                status = f"error: {e.__class__.__name__}"
            if status == "sent":
                sent += 1
                log_row(config.SENT_LOG, lead, "sent")
                print("sent")
            else:
                failed += 1
                log_row(config.FAILED_LOG, lead, status)
                print(status)
            if i < len(batch):
                wait = random.uniform(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                time.sleep(wait)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        print(f"\nDone. sent={sent}  failed={failed}")
        print(f"Logs: {config.SENT_LOG.name}, {config.FAILED_LOG.name}")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
