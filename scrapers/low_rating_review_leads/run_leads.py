#!/usr/bin/env python3
"""
Low-Rating / No-Website Review-Leads Scraper — one file to run.

Pipeline (all three stages reuse the engines already in this project):

  1. Link Collector  (Playwright)   scrapers/link_collector
        "<category> in <state>" for every line in input/categories.txt x
        input/states.txt  ->  Google Maps place links
  2. Business Details (+ website email/social crawl)   scrapers/business_details
        every link  ->  name, phone, website, rating, reviews, address, emails,
        social handles …
  3. Lead filter      low_rating_review_leads/lead_filter.py
        keep a business when it has NO website OR rating <= MAX_RATING, add a
        wa.me WhatsApp link, and (for the no-website ones) look up Facebook /
        Instagram / LinkedIn by name.

Usage (run from the project root):

    python low_rating_review_leads/run_leads.py                 # full run
    python low_rating_review_leads/run_leads.py --test          # 1 category x 1 state
    python low_rating_review_leads/run_leads.py --limit 6       # first 6 searches
    python low_rating_review_leads/run_leads.py --no-social     # skip name lookup
    python low_rating_review_leads/run_leads.py --filter-only PATH.xlsx
                                                               # re-filter an
                                                               # existing details file
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _looks_like_project(d: Path) -> bool:
    return (d / "console.py").is_file() and (d / "scrapers").is_dir()


def _find_project_root() -> Path:
    """Locate the main 'Google Maps & Contacts Scraper' project, which holds
    console.py and scrapers/. Works whether this folder sits INSIDE the project
    or has been moved out next to it.

    Override order:
      1. leads_config.PROJECT_ROOT (if set to a real path)
      2. env var  GMAPS_PROJECT_ROOT
      3. this folder's parent, then each ancestor going up
      4. any immediate sub-folder of an ancestor (handles "moved out beside it")
    """
    # 1 + 2 — explicit overrides
    for cand in (globals().get("_CFG_PROJECT_ROOT"), _os.environ.get("GMAPS_PROJECT_ROOT")):
        if cand:
            p = Path(cand).expanduser().resolve()
            if _looks_like_project(p):
                return p

    # 3 — walk up from HERE
    for anc in [HERE, *HERE.parents]:
        if _looks_like_project(anc):
            return anc

    # 4 — scan sub-folders of each ancestor (e.g. moved out beside the project)
    for anc in [HERE.parent, *HERE.parent.parents]:
        try:
            for sub in sorted(anc.iterdir()):
                if sub.is_dir() and _looks_like_project(sub):
                    return sub
        except (PermissionError, OSError):
            pass
        if anc == anc.parent:
            break

    raise SystemExit(
        "Could not find the main 'Google Maps & Contacts Scraper' project "
        "(the folder that contains console.py and scrapers/).\n"
        "Fix: either keep this 'low_rating_review_leads' folder INSIDE that "
        "project, or open leads_config.py and set\n"
        "    PROJECT_ROOT = r\"C:\\full\\path\\to\\Google Maps & Contacts Scraper Transfer\"\n"
        "or set the env var GMAPS_PROJECT_ROOT to that path.")


import os as _os

# leads_config is beside this file — load it first so its optional PROJECT_ROOT
# override is available to _find_project_root().
sys.path.insert(0, str(HERE))
import leads_config as cfg         # our settings (unique name — no clash)
_CFG_PROJECT_ROOT = getattr(cfg, "PROJECT_ROOT", None)

PROJECT_ROOT = _find_project_root()

for p in (str(PROJECT_ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import console                     # project-root shared helpers
import lead_filter
import social_finder

log = logging.getLogger("run_leads")

LC_DIR = PROJECT_ROOT / "scrapers" / "link_collector"
BD_DIR = PROJECT_ROOT / "scrapers" / "business_details"
EM_DIR = PROJECT_ROOT / "scrapers" / "email_scraper"


# ---------------------------------------------------------------------------
# sys.modules hygiene — the reused engines both ship a module called `settings`
# ---------------------------------------------------------------------------

def _purge(names: set[str], prefixes: tuple[str, ...] = ()) -> None:
    for name in list(sys.modules):
        if name in names or any(name == pfx or name.startswith(pfx + ".")
                                for pfx in prefixes):
            sys.modules.pop(name, None)


def _drop_path(path: Path) -> None:
    s = str(path)
    while s in sys.path:
        sys.path.remove(s)


# ---------------------------------------------------------------------------
# Stage 1 — link collection
# ---------------------------------------------------------------------------

def preflight_block_check() -> bool:
    """Quick probe: is this IP currently getting Google's /sorry/ CAPTCHA?
    Returns True when it looks blocked. Playwright-mode only."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    url = "https://www.google.com/maps/search/coffee+in+Denver"
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            try:
                p = b.new_context(locale="en-US").new_page()
                p.goto(url, timeout=30000, wait_until="domcontentloaded")
                p.wait_for_timeout(2500)
                blocked = "/sorry/" in p.url or "unusual traffic" in (
                    p.evaluate("document.body.innerText") or "").lower()
            finally:
                b.close()
        return blocked
    except Exception:
        return False


def collect_links(work_dir: Path, out_name: str, pair_limit: int) -> Path | None:
    mode = (getattr(cfg, "LINK_COLLECTOR", "playwright") or "playwright").lower()
    console.rule(f"Stage 1/3 — collecting Google Maps links ({mode})")

    if mode == "playwright" and preflight_block_check():
        raise SystemExit(
            "Google is serving a /sorry/ CAPTCHA to this IP right now — a "
            "browser run would collect nothing. Options: wait ~30-60 min, set "
            "USE_PROXY / PROXY_URL in leads_config.py, or switch "
            "LINK_COLLECTOR = \"api\".")

    _purge({"settings"}, prefixes=("scraper",))
    sys.path.insert(0, str(LC_DIR))
    try:
        import settings as lc
        lc.COLLECTOR = mode
        lc.HEADLESS = cfg.HEADLESS
        lc.MAX_RESULTS = cfg.MAX_RESULTS_PER_SEARCH
        lc.PER_PAIR_DELAY = cfg.PER_SEARCH_DELAY
        lc.PAIR_LIMIT = pair_limit
        lc.INCLUDE_SPONSORED = False
        lc.CATEGORIES_FILE = Path(cfg.CATEGORIES_FILE)
        lc.LOCATIONS_FILE = Path(cfg.LOCATIONS_FILE)
        lc.OUTPUT_DIR = Path(work_dir)
        lc.OUTPUT_NAME = out_name
        lc.USE_PROXY = getattr(cfg, "USE_PROXY", False)
        lc.PROXY_URL = getattr(cfg, "PROXY_URL", "")
        lc.API_TILE = getattr(cfg, "API_TILE", False)
        lc.API_MAX_WORKERS = getattr(cfg, "API_MAX_WORKERS", 1)
        if mode == "api":
            from scraper.collector_api import run_api
            run_api(lc)
        else:
            from scraper.collector_playwright import run_playwright
            run_playwright(lc)
    finally:
        _drop_path(LC_DIR)
        _purge({"settings"}, prefixes=("scraper",))

    csv_path = Path(work_dir) / f"{out_name}.csv"
    if not csv_path.exists():
        return None
    # An empty collection still writes a header-only file — treat that as None.
    if csv_path.read_text(encoding="utf-8-sig").strip().count("\n") < 1:
        return None
    return csv_path


# ---------------------------------------------------------------------------
# Stage 2 — business details (+ website contact crawl)
# ---------------------------------------------------------------------------

def scrape_details(links_csv: Path, work_dir: Path) -> Path | None:
    console.rule("Stage 2/3 — scraping business details" +
                 (" + website emails/socials" if cfg.CRAWL_WEBSITES_FOR_CONTACTS
                  else ""))
    _purge({"settings", "detail_scraper", "cli"})
    sys.path.insert(0, str(BD_DIR))
    if str(EM_DIR) not in sys.path:
        sys.path.append(str(EM_DIR))
    try:
        import settings as bd
        bd.INPUT_FILE = Path(links_csv)
        bd.OUTPUT_DIR = Path(work_dir)
        bd.DETAIL_LEVEL = cfg.DETAIL_LEVEL
        bd.MAX_WORKERS = cfg.BUSINESS_MAX_WORKERS
        bd.USE_PROXY = getattr(cfg, "USE_PROXY", False)
        bd.PROXY_URL = getattr(cfg, "PROXY_URL", "")
        bd.EMAIL_OPTIONS = (
            {"want_emails": True, "want_socials": True, "mode": cfg.EMAIL_MODE}
            if cfg.CRAWL_WEBSITES_FOR_CONTACTS else None
        )
        import detail_scraper
        detail_scraper.run(bd)
    finally:
        _drop_path(BD_DIR)
        _purge({"settings", "detail_scraper", "cli"})

    xlsx = sorted(Path(work_dir).glob("*.xlsx"), key=lambda p: p.stat().st_mtime)
    return xlsx[-1] if xlsx else None


# ---------------------------------------------------------------------------
# Stage 3 — filter + WhatsApp + name-based social lookup
# ---------------------------------------------------------------------------

def make_leads(details_xlsx: Path, out_stem: Path, do_social: bool) -> None:
    console.rule("Stage 3/3 — filtering leads")
    leads = lead_filter.build_leads(details_xlsx, cfg)
    log.info("Kept %d lead(s) from %s", len(leads), details_xlsx.name)

    if not leads:
        lead_filter.write_leads(leads, out_stem)
        return

    no_site = sum(1 for l in leads if l["Has Website"] == "No")
    log.info("  %d have no website, %d have a website but a low rating",
             no_site, len(leads) - no_site)

    if do_social and cfg.SOCIAL_LOOKUP_ENABLED:
        pending = [l for l in leads if l["Social lookup"] == "pending" and l["Name"]]
        cap = cfg.SOCIAL_LOOKUP_MAX or len(pending)
        pending = pending[:cap]
        if pending:
            console.rule(f"Stage 3/3 — social lookup for {len(pending)} lead(s)")
            _social_lookup(pending, out_stem, leads)
    else:
        log.info("Name-based social lookup skipped.")

    csv_path, xlsx_path = lead_filter.write_leads(leads, out_stem)
    console.rule("Done")
    if xlsx_path:
        log.info("Leads sheet : %s", xlsx_path)
    log.info("Leads CSV   : %s", csv_path)


def _social_lookup(pending: list[dict], out_stem: Path, all_leads: list[dict]) -> None:
    """Look each pending lead up by name; save progress every 25 rows so a
    Ctrl+C or a block partway through still leaves a usable sheet."""
    import time
    import httpx

    try:
        from tqdm import tqdm
        bar = tqdm(total=len(pending), desc="Social lookup")
    except Exception:
        bar = None

    found = 0
    with httpx.Client(headers=social_finder.HEADERS, timeout=15.0,
                      follow_redirects=True) as client:
        for i, lead in enumerate(pending, 1):
            try:
                hits = social_finder.find_socials(
                    lead["Name"], lead.get("City", ""), lead.get("State", ""),
                    client=client)
            except Exception as exc:                     # never let one row abort
                log.debug("lookup crashed for %r: %s", lead["Name"], exc)
                hits = {}
            got = False
            for key in ("Facebook", "Instagram", "LinkedIn"):
                if hits.get(key) and not lead.get(key):
                    lead[key] = hits[key]
                    got = True
            lead["Social lookup"] = "found by name" if got else "not found"
            found += got
            if bar:
                bar.update(1)
            if i % 25 == 0:
                lead_filter.write_leads(all_leads, out_stem)
            time.sleep(cfg.SOCIAL_LOOKUP_DELAY)

    if bar:
        bar.close()
    log.info("Social lookup: added a handle for %d / %d lead(s).",
             found, len(pending))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true",
                    help="Tiny run: first category x first state only.")
    ap.add_argument("--limit", type=int, default=None, metavar="N",
                    help="Run only the first N category x state searches.")
    ap.add_argument("--no-social", action="store_true",
                    help="Skip the name-based Facebook/Instagram/LinkedIn lookup.")
    ap.add_argument("--filter-only", metavar="PATH", default=None,
                    help="Skip stages 1-2; just filter an existing "
                         "business-details .xlsx/.csv into a leads sheet.")
    args = ap.parse_args()

    console.setup_logging()
    console.banner("Low-Rating / No-Website Review-Leads Scraper")

    cfg.WORK_DIR.mkdir(parents=True, exist_ok=True)
    cfg.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_stem = cfg.OUTPUT_DIR / (cfg.OUTPUT_NAME or f"leads_{stamp}")

    if args.filter_only:
        src = Path(args.filter_only)
        if not src.exists():
            raise SystemExit(f"File not found: {src}")
        make_leads(src, out_stem, do_social=not args.no_social)
        return

    pair_limit = cfg.PAIR_LIMIT
    if args.test:
        pair_limit = 1
    elif args.limit is not None:
        pair_limit = args.limit

    links_csv = collect_links(cfg.WORK_DIR, f"links_{stamp}", pair_limit)
    if not links_csv:
        raise SystemExit(
            "Stage 1 collected no links — Google may have blocked the browser, "
            "or the search terms returned nothing. Nothing to do.")
    log.info("Collected links: %s", links_csv)

    details_xlsx = scrape_details(links_csv, cfg.WORK_DIR)
    if not details_xlsx:
        raise SystemExit("Stage 2 produced no business-details file. Stopping.")
    log.info("Business details: %s", details_xlsx)

    make_leads(details_xlsx, out_stem, do_social=not args.no_social)


if __name__ == "__main__":
    main()
