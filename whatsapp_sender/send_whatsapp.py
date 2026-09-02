"""
Send the dashboard's pitch on WhatsApp to the leads that are on WhatsApp.

    python send_whatsapp.py --dry-run       # build messages, write preview.csv, send nothing
    python send_whatsapp.py --limit 5        # send only 5 this run
    python send_whatsapp.py                  # send up to BATCH_LIMIT (config.py)
    python send_whatsapp.py --all            # ignore the batch limit
    python send_whatsapp.py --segment "No website"
    python send_whatsapp.py --ignore-checked # send without a verified list (not advised)

Recommended order:
    1)  python check_whatsapp.py            -> builds whatsapp_numbers.csv
    2)  python send_whatsapp.py --dry-run   -> review preview.csv
    3)  python send_whatsapp.py --limit 5   -> small first batch
    4)  python send_whatsapp.py             -> keep going in batches

First real run opens Chrome -> scan the WhatsApp QR once (saved in ./chrome_profile).
Numbers in sent_log.csv are skipped, so stopping and re-running is safe.

WARNING: unsolicited bulk messaging can get your WhatsApp number banned. Keep
batches small, keep the delays, message only real prospects.
"""
import argparse
import csv
import random
import sys
import time

import config
import leadlib
import wa_web


def main():
    ap = argparse.ArgumentParser(description="Bulk WhatsApp sender for the leads list.")
    ap.add_argument("--dry-run", action="store_true",
                    help="build messages, write preview.csv, send nothing")
    ap.add_argument("--limit", type=int, default=None,
                    help="max messages this run (default: BATCH_LIMIT in config.py)")
    ap.add_argument("--all", action="store_true", help="ignore the batch limit")
    ap.add_argument("--segment", action="append",
                    help='only this segment (repeatable): "No website" / "Low rating"')
    ap.add_argument("--ignore-checked", action="store_true",
                    help="send even to numbers not verified by check_whatsapp.py")
    ap.add_argument("--yes", action="store_true", help='skip the "go" confirmation')
    args = ap.parse_args()

    if not config.LEADS_XLSX.exists():
        sys.exit(f"Leads file not found: {config.LEADS_XLSX}")

    leads = leadlib.load_leads(segment_filter=args.segment)

    # --- restrict to verified WhatsApp numbers -------------------------------
    use_checked = config.USE_CHECKED_LIST and not args.ignore_checked
    checked = leadlib.read_numbers(config.CHECKED_CSV) if use_checked else None
    if use_checked:
        if not checked:
            sys.exit(
                "No verified numbers yet. Run:  python check_whatsapp.py\n"
                "(or pass --ignore-checked to send without verifying)."
            )
        leads = [l for l in leads if l["number"] in checked]

    done = leadlib.read_numbers(config.SENT_LOG)
    pending = [l for l in leads if l["number"] not in done]

    scope = "verified on WhatsApp" if use_checked else "with a number (UNVERIFIED)"
    print(f"{len(leads)} leads {scope} (segments: {args.segment or config.SEGMENTS_TO_SEND})")
    print(f"{len(done)} already sent -> {len(pending)} still to send")

    # --- dry run ----------------------------------------------------------------
    if args.dry_run:
        with open(config.PREVIEW_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["number", "name", "segment", "rating", "reviews",
                        "city", "state", "message"])
            for l in pending:
                w.writerow([l["number"], l["name"], l["segment"], l["rating"],
                            l["reviews"], l["city"], l["state"], l["message"]])
        print(f"\nDRY RUN - wrote {len(pending)} rows to {config.PREVIEW_CSV}")
        for l in pending[:3]:
            print(f"\n  -> +{l['number']}  ({l['name']})\n     {l['message']}")
        if len(pending) > 3:
            print(f"\n  ...and {len(pending) - 3} more in preview.csv")
        return

    # --- send -----------------------------------------------------------------
    limit = None if args.all else (args.limit or config.BATCH_LIMIT)
    batch = pending if limit is None else pending[:limit]
    if not batch:
        print("Nothing to send.")
        return

    print(f"\nAbout to send {len(batch)} messages, "
          f"{config.MIN_DELAY_SECONDS}-{config.MAX_DELAY_SECONDS}s apart.")
    if not args.yes:
        if input('Type "go" to start: ').strip().lower() != "go":
            print("Cancelled.")
            return

    driver = wa_web.make_driver()
    sent = failed = 0
    try:
        wa_web.wait_until_logged_in(driver)
        for i, lead in enumerate(batch, 1):
            print(f"[{i}/{len(batch)}] +{lead['number']}  {lead['name'][:38]:<38} ",
                  end="", flush=True)
            try:
                status = wa_web.send_current_chat(
                    driver, lead["number"], lead["message"], timeout=config.SEND_TIMEOUT)
            except Exception as e:  # noqa: BLE001
                status = f"error: {e.__class__.__name__}"

            if status == "sent":
                sent += 1
                leadlib.log_contact(config.SENT_LOG, lead, "sent")
                print("sent")
            else:
                failed += 1
                leadlib.log_contact(config.FAILED_LOG, lead, status)
                print(status)

            if i < len(batch):
                time.sleep(random.uniform(config.MIN_DELAY_SECONDS,
                                          config.MAX_DELAY_SECONDS))
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
