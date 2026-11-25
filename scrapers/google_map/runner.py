#!/usr/bin/env python3
"""
Execution engine for the Google Maps & Contacts Scraper.

This module knows how to actually run the scrapers. run.py calls into here, so
the run logic lives in one place.

Each scraper keeps its own self-contained settings.py. To stop the two
identically-named `settings` modules from clashing, "Both" runs the link
collector first, then resets the import state before running the business
scraper.
"""

import csv
import sys
import logging
from pathlib import Path

import console

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
SCRAPERS_DIR = PROJECT_ROOT / "scrapers"
LINK_COLLECTOR_DIR = SCRAPERS_DIR / "link_collector"
BUSINESS_DETAILS_DIR = SCRAPERS_DIR / "business_details"
EMAIL_SCRAPER_DIR = SCRAPERS_DIR / "email_scraper"
LINK_OUTPUT_DIR = PROJECT_ROOT / "output" / "link_collector"
BUSINESS_OUTPUT_DIR = PROJECT_ROOT / "output" / "business_details"
WEBSITES_TXT = PROJECT_ROOT / "input" / "email_scraper" / "websites.txt"

# Social-handle columns added when enriching a business file in place.
SOCIAL_COLUMNS = ["Facebook", "Instagram", "Twitter", "LinkedIn", "YouTube", "TikTok"]


# ---------------------------------------------------------------------------
# Settings / import plumbing
# ---------------------------------------------------------------------------

def _dispatch_links(settings_mod):
    """Run the link collector in whichever mode its settings select."""
    mode = (settings_mod.COLLECTOR or "api").strip().lower()
    if mode == "api":
        from scraper.collector_api import run_api
        run_api(settings_mod)
    elif mode == "playwright":
        from scraper.collector_playwright import run_playwright
        run_playwright(settings_mod)
    else:
        raise SystemExit(
            f"Unknown COLLECTOR={settings_mod.COLLECTOR!r} in "
            f"scrapers/link_collector/settings.py. Use 'api' or 'playwright'."
        )


def _reset_after_links():
    """
    Drop the link collector's modules so the business scraper can import its own
    (identically named) settings module without a clash.
    """
    for name in list(sys.modules):
        if name in ("settings", "detail_scraper", "cli", "scraper") \
                or name.startswith("scraper."):
            sys.modules.pop(name, None)
    link_dir = str(LINK_COLLECTOR_DIR)
    while link_dir in sys.path:
        sys.path.remove(link_dir)


def exec_emails(overrides: dict | None,
                websites: list[str] | None = None) -> Path | None:
    """Standalone email / social-handle run. Returns the produced xlsx (or csv).

    `websites` overrides the input list; None reads input/email_scraper/websites.txt.
    """
    sys.path.insert(0, str(EMAIL_SCRAPER_DIR))
    console.setup_logging()
    from engine.api import run_emails
    from engine.cli import _build_cli_emit

    opts = overrides or {}
    csv_path, xlsx_path, _rows = run_emails(
        websites=websites,
        mode=opts.get("mode", "single"),
        want_emails=opts.get("want_emails", True),
        want_socials=opts.get("want_socials", True),
        concurrency=opts.get("concurrency", 20),
        js_fallback=opts.get("js_fallback", False),
        emit=_build_cli_emit(),
    )
    return xlsx_path or csv_path


# ---------------------------------------------------------------------------
# Email scraper: input selection + in-place enrichment of a business file
# ---------------------------------------------------------------------------

def _business_output_files() -> list[Path]:
    """Business-details output files (xlsx/csv), newest first."""
    if not BUSINESS_OUTPUT_DIR.exists():
        return []
    files = [p for p in BUSINESS_OUTPUT_DIR.glob("*.xlsx") if not p.name.startswith("~$")]
    files += list(BUSINESS_OUTPUT_DIR.glob("*.csv"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _read_table(path: Path) -> tuple[list[str], list[dict]]:
    """Read an xlsx or csv into (headers, list-of-row-dicts)."""
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        try:
            first = next(it)
        except StopIteration:
            wb.close()
            return [], []
        headers = ["" if h is None else str(h) for h in first]
        rows = []
        for r in it:
            rows.append({h: ("" if i >= len(r) or r[i] is None else r[i])
                         for i, h in enumerate(headers)})
        wb.close()
        return headers, rows

    with open(path, encoding="utf-8-sig", newline="") as f:
        data = list(csv.reader(f))
    if not data:
        return [], []
    headers = list(data[0])
    rows = [{h: (raw[i] if i < len(raw) else "") for i, h in enumerate(headers)}
            for raw in data[1:]]
    return headers, rows


def _write_table(path: Path, headers: list[str], rows: list[dict]) -> Path:
    """Write (headers, rows) to xlsx/csv atomically: write a temp file, then
    replace the target. If the target is locked (e.g. open in Excel), the merged
    copy is kept alongside as '<name> (with contacts)<ext>' rather than hanging
    or corrupting the original. Returns the path actually written.
    """
    tmp = path.with_name(f"~tmp-{path.stem}{path.suffix}")
    if path.suffix.lower() == ".xlsx":
        from openpyxl import Workbook
        wb = Workbook(write_only=True)          # fast + low memory for big sheets
        ws = wb.create_sheet()
        ws.append(headers)
        for r in rows:
            ws.append([r.get(h, "") for h in headers])
        wb.save(str(tmp))
    else:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for r in rows:
                w.writerow([r.get(h, "") for h in headers])

    try:
        tmp.replace(path)                       # atomic on the same volume
        return path
    except PermissionError:
        alt = path.with_name(f"{path.stem} (with contacts){path.suffix}")
        try:
            tmp.replace(alt)
        except PermissionError:
            log.error("Could not write %s or %s (both locked?) — kept %s.",
                      path.name, alt.name, tmp.name)
            return tmp
        log.warning("%s is locked (open in Excel?) — saved merged copy to %s.",
                    path.name, alt.name)
        return alt


def _merge_headers(existing: list[str], extra: list[str]) -> list[str]:
    """Existing columns, plus any new contact columns, keeping Scraped Date last."""
    tail = ["Scraped Date"] if "Scraped Date" in existing else []
    base = [h for h in existing if h not in tail]
    for col in extra:
        if col not in base:
            base.append(col)
    return base + tail


def _ensure_email_engine():
    """Add the email engine to sys.path and import its embedding helpers."""
    if str(EMAIL_SCRAPER_DIR) not in sys.path:
        sys.path.insert(0, str(EMAIL_SCRAPER_DIR))
    console.setup_logging()
    from engine.api import collect_contacts, root_domain, make_bar_emit
    return collect_contacts, root_domain, make_bar_emit


def _websites_from_file(path: Path) -> list[str]:
    """Unique, non-empty values from the 'Website' column of a business file."""
    headers, rows = _read_table(path)
    if "Website" not in headers:
        log.warning("%s has no 'Website' column.", path.name)
        return []
    out, seen = [], set()
    for r in rows:
        w = str(r.get("Website") or "").strip()
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _dedup_websites(websites: list[str], root_domain) -> list[str]:
    """One URL per root domain, http-prefixed, ready to hand to the crawler."""
    seen, out = set(), []
    for w in websites:
        w = str(w or "").strip()
        dom = root_domain(w) if w else ""
        if dom and dom not in seen:
            seen.add(dom)
            out.append(w if w.startswith(("http://", "https://")) else f"http://{w}")
    return out


def _by_domain_from_rows(rows: list[dict], root_domain) -> dict:
    """Index the email engine's result rows by root domain (first wins)."""
    by_domain: dict = {}
    for row in rows:
        dom = root_domain(str(row.get("Domain", "")))
        if dom and dom not in by_domain:
            by_domain[dom] = row
    return by_domain


def _merge_and_write(path: Path, headers: list[str], rows: list[dict],
                     by_domain: dict, want_emails: bool, want_socials: bool,
                     root_domain) -> Path | None:
    """Merge crawled contacts (keyed by root domain) into already-read rows and
    write the file back safely (contact columns before Scraped Date). Takes the
    rows already in memory so the file isn't read a second time. Returns the path
    written, or None when there's nothing to do."""
    if not rows:
        log.warning("No rows found in %s — nothing to enrich.", path.name)
        return None
    if "Website" not in headers:
        log.warning("%s has no 'Website' column — cannot merge contacts.", path.name)
        return None

    extra = (["Emails"] if want_emails else []) + (SOCIAL_COLUMNS if want_socials else [])
    for r in rows:
        w = str(r.get("Website") or "").strip()
        c = by_domain.get(root_domain(w) if w else "")
        for col in extra:
            r[col] = (c.get(col, "") if c else "")

    log.info("Merging contacts into %s (%d rows) — writing...", path.name, len(rows))
    written = _write_table(path, _merge_headers(headers, extra), rows)
    log.info("Wrote %s", written.name)
    return written


def _merge_contacts_into(path: Path, opts: dict) -> Path | None:
    """Crawl the websites in a business file and merge emails/socials back into
    it (written safely in place). No separate contacts file is produced. Returns
    the path written, or None."""
    collect_contacts, root_domain, make_bar_emit = _ensure_email_engine()
    headers, rows = _read_table(path)          # read once, reused for the merge
    websites = _dedup_websites(
        [str(r.get("Website") or "").strip() for r in rows], root_domain)

    by_domain: dict = {}
    if websites:
        log.info("Crawling %d unique website(s) from %s...", len(websites), path.name)
        emit, close_bar = make_bar_emit("Emails/socials")
        try:
            by_domain = collect_contacts(
                websites, mode=opts.get("mode", "single"),
                want_emails=opts.get("want_emails", True),
                want_socials=opts.get("want_socials", True),
                concurrency=opts.get("concurrency", 20),
                js_fallback=opts.get("js_fallback", False), emit=emit,
            )
        finally:
            close_bar()

    return _merge_and_write(path, headers, rows, by_domain,
                            opts.get("want_emails", True),
                            opts.get("want_socials", True), root_domain)


def _emails_separate_then_merge(src: Path, opts: dict) -> Path | None:
    """Write a separate contacts file AND merge those results into `src`.

    Crawls once: run_emails writes the standalone contacts file and returns the
    rows, which are then merged into the selected input file. Returns the path
    of the separate contacts file (or None if nothing was written).
    """
    sys.path.insert(0, str(EMAIL_SCRAPER_DIR))
    console.setup_logging()
    from engine.api import run_emails, root_domain
    from engine.cli import _build_cli_emit

    headers, rows = _read_table(src)           # read once, reused for the merge
    websites = [w for w in (str(r.get("Website") or "").strip() for r in rows) if w]
    csv_path, xlsx_path, crawled = run_emails(
        websites=websites, mode=opts.get("mode", "single"),
        want_emails=opts.get("want_emails", True),
        want_socials=opts.get("want_socials", True),
        concurrency=opts.get("concurrency", 20),
        js_fallback=opts.get("js_fallback", False), emit=_build_cli_emit(),
    )
    by_domain = _by_domain_from_rows(crawled, root_domain)
    _merge_and_write(src, headers, rows, by_domain, opts.get("want_emails", True),
                     opts.get("want_socials", True), root_domain)
    return xlsx_path or csv_path


def _email_speed_options() -> list[tuple]:
    """Speed presets for the (async) email crawl — value = sites fetched at once.

    These requests are direct (no proxy) and async, so concurrency can be much
    higher than the thread-based scrapers.
    """
    return [
        (10, "Normal", "10 sites at once — lightest."),
        (20, "Fast", "20 sites at once — default."),
        (40, "Rapid", "40 sites at once — faster."),
        (64, "Turbo", "64 sites at once — maximum."),
    ]


def _ask_email_input() -> Path | None:
    """Pick the email scraper's input: websites.txt, or a business output file."""
    options = [(None, "websites.txt", str(WEBSITES_TXT))]
    for p in _business_output_files():
        options.append((p, p.name, "business output"))
    return console.select("Which input should the email scraper use?",
                          options, default_value=None)


# ---------------------------------------------------------------------------
# Output-file discovery (so "both" can feed the link CSV into the next step)
# ---------------------------------------------------------------------------

def _files_in(d: Path) -> set:
    if not d.exists():
        return set()
    return set(d.glob("*.csv")) | set(d.glob("*.xlsx"))


def _newest(paths) -> Path | None:
    paths = [p for p in paths if p.exists()]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def _new_since(d: Path, before: set, suffix: str | None = None) -> set:
    new = _files_in(d) - before
    if suffix:
        new = {p for p in new if p.suffix.lower() == suffix}
    return new


def _newest_link_csv(before: set) -> Path | None:
    """The CSV the link collector just wrote (newest one not present before)."""
    fresh = _new_since(LINK_OUTPUT_DIR, before, ".csv")
    return _newest(fresh) or _newest(_files_in(LINK_OUTPUT_DIR))


# ---------------------------------------------------------------------------
# Text-menu (CLI) path — interactive prompts via each scraper's own cli.py
# ---------------------------------------------------------------------------

def cli_links(defaults: bool):
    sys.path.insert(0, str(LINK_COLLECTOR_DIR))
    import settings
    from scraper.common import setup_logging
    if not defaults:
        from scraper.cli import configure
        configure(settings)
    setup_logging()
    _dispatch_links(settings)


def cli_business(defaults: bool, input_override: str | None = None,
                 ask_input: bool = True, output_name_override: str | None = None):
    sys.path.insert(0, str(BUSINESS_DETAILS_DIR))
    if str(EMAIL_SCRAPER_DIR) not in sys.path:
        sys.path.append(str(EMAIL_SCRAPER_DIR))
    console.setup_logging()
    import settings
    if input_override:
        settings.INPUT_FILE = Path(input_override)
    if output_name_override:
        settings.OUTPUT_FILENAME_PATTERN = output_name_override
    if not defaults:
        from cli import configure
        configure(settings, ask_input=ask_input,
                 ask_output_name=not output_name_override)
    import detail_scraper
    detail_scraper.run(settings)


def cli_emails(defaults: bool):
    opts = {"want_emails": True, "want_socials": True, "mode": "single",
            "concurrency": 20, "js_fallback": False}
    src = None            # None = websites.txt, else a Path to a business file
    out_mode = "separate"
    if not defaults and sys.stdin.isatty():
        console.banner("Email / Social-Handle Scraper")
        src = _ask_email_input()
        opts["want_emails"] = console.confirm("Extract emails?", default=True)
        opts["want_socials"] = console.confirm("Extract social handles?", default=True)
        all_emails = console.confirm(
            "Collect ALL emails per site? (No = best one only)", default=False)
        opts["mode"] = "all" if all_emails else "single"
        opts["concurrency"] = console.select(
            "How fast should it crawl? (more = faster; these are direct, no proxy)",
            _email_speed_options(),
            default_value=opts["concurrency"],
        )
        opts["js_fallback"] = console.confirm(
            "Render JavaScript pages when no email is found? "
            "(slower, needs Playwright; off is faster)", default=False)
        # Only a business file can be enriched in place; websites.txt has no
        # dataset to merge into, so those options are skipped for it.
        if src is not None:
            out_mode = console.select(
                "Where should the results be stored?",
                [
                    ("separate", "Separate file",
                     "Write a new contacts file in output/email_scraper."),
                    ("merge", "Into selected file",
                     f"Add the emails/socials columns into {src.name}."),
                    ("both", "Separate + combine",
                     f"Write a contacts file AND merge it into {src.name}."),
                ],
                default_value="separate",
            )

    # Enrich the chosen business file in place (no separate file).
    if src is not None and out_mode == "merge":
        written = _merge_contacts_into(src, opts)
        if written:
            log.info("Done. Contacts written to %s", written.name)
        return

    # Write a separate contacts file AND merge it into the selected file.
    if src is not None and out_mode == "both":
        out = _emails_separate_then_merge(src, opts)
        if out:
            log.info("Done. Wrote separate file %s (and merged into the selected "
                     "file — see above).", out.name)
        else:
            log.info("Done (merged into the selected file — see above).")
        return

    # Otherwise write a separate contacts file (from websites.txt, or from the
    # websites listed in the chosen business file).
    websites = _websites_from_file(src) if src is not None else None
    out = exec_emails(opts, websites=websites)
    if out:
        log.info("Done. Wrote %s", out)
    else:
        log.info("Done. No contacts written.")


def run_cli(target: str, defaults: bool):
    if target == "links":
        cli_links(defaults)
    elif target == "business":
        cli_business(defaults)
    elif target == "emails":
        cli_emails(defaults)
    elif target == "both":
        before = _files_in(LINK_OUTPUT_DIR)
        cli_links(defaults)
        csv = _newest_link_csv(before)
        if not csv:
            log.warning("No links were collected — nothing to scrape for "
                        "business details. Stopping.")
            return
        log.info("Feeding collected links into the business scraper: %s", csv.name)
        # Reuse the name given for the links output (if any) for the business
        # output too, so both files — and the dashboard batch — share one name.
        link_settings = sys.modules.get("settings")
        out_name = getattr(link_settings, "OUTPUT_NAME", "") if link_settings else ""
        _reset_after_links()
        cli_business(defaults, input_override=str(csv), ask_input=False,
                     output_name_override=out_name or None)
