"""
Find which lead numbers are actually on WhatsApp.

The scraper's "WhatsApp" column is only a guess (it just formats the phone as a
wa.me link). This script opens each number on WhatsApp Web and records whether
WhatsApp recognises it - WITHOUT sending any message.

    python check_whatsapp.py                 # check everything not checked yet
    python check_whatsapp.py --limit 50      # check only 50 this run
    python check_whatsapp.py --segment "No website"
    python check_whatsapp.py --recheck       # also re-check numbers already checked

Output (next to this script):
    whatsapp_numbers.csv   - numbers CONFIRMED on WhatsApp   <- send_whatsapp.py uses this
    not_on_whatsapp.csv    - numbers confirmed NOT on WhatsApp

First run opens Chrome -> scan the QR code once (saved in ./chrome_profile).
Stop with Ctrl+C any time; already-checked numbers are skipped on the next run.
"""
import argparse
import random
import sys
import time

import config
import leadlib
import wa_web


def main():
    ap = argparse.ArgumentParser(description="Detect which lead numbers are on WhatsApp.")
    ap.add_argument("--limit", type=int, default=None, help="max numbers to check this run")
    ap.add_argument("--segment", action="append",
                    help='only this segment (repeatable): "No website" / "Low rating"')
    ap.add_argument("--recheck", action="store_true",
                    help="also re-check numbers already in the output files")
    args = ap.parse_args()

    if not config.LEADS_XLSX.exists():
        sys.exit(f"Leads file not found: {config.LEADS_XLSX}")

    leads = leadlib.load_leads(segment_filter=args.segment, apply_send_filters=False)

    done = set()
    if not args.recheck:
        done = leadlib.read_numbers(config.CHECKED_CSV) | leadlib.read_numbers(config.NOT_ON_WA_CSV)

    pending = [l for l in leads if l["number"] not in done]
    if args.limit:
        pending = pending[: args.limit]

    already_yes = len(leadlib.read_numbers(config.CHECKED_CSV))
    print(f"{len(leads)} leads with a number "
          f"(segments: {args.segment or config.SEGMENTS_TO_SEND})")
    print(f"{len(done)} already checked ({already_yes} on WhatsApp) "
          f"-> {len(pending)} to check now")
    if not pending:
        print("Nothing to check.")
        return
    if input(f'Type "go" to check {len(pending)} numbers: ').strip().lower() != "go":
        print("Cancelled.")
        return

    driver = wa_web.make_driver()
    yes = no = unknown = 0
    try:
        wa_web.wait_until_logged_in(driver)
        for i, lead in enumerate(pending, 1):
            print(f"[{i}/{len(pending)}] +{lead['number']}  {lead['name'][:38]:<38} ",
                  end="", flush=True)
            try:
                state = wa_web.open_chat(driver, lead["number"], timeout=config.CHECK_TIMEOUT)
            except Exception as e:  # noqa: BLE001
                state = f"error: {e.__class__.__name__}"

            if state == "ready":
                yes += 1
                leadlib.log_check(config.CHECKED_CSV, lead, "on_whatsapp")
                print("on WhatsApp")
            elif state == "invalid":
                no += 1
                leadlib.log_check(config.NOT_ON_WA_CSV, lead, "not_on_whatsapp")
                print("not on WhatsApp")
            else:
                unknown += 1
                print(state)  # timeout / error - left unchecked, retried next run

            if i < len(pending):
                time.sleep(random.uniform(config.CHECK_MIN_DELAY_SECONDS,
                                          config.CHECK_MAX_DELAY_SECONDS))
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        total_yes = len(leadlib.read_numbers(config.CHECKED_CSV))
        print(f"\nThis run: on WhatsApp={yes}  not={no}  unknown={unknown}")
        print(f"Confirmed on WhatsApp so far: {total_yes}  ->  {config.CHECKED_CSV.name}")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
