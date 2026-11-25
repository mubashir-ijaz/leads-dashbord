# Playwright collector: drives a real Chromium browser, scrolls the search
# results sidebar to the end (or a cap), and extracts each result's href.
# Use this when you need more than the API's 20-result-per-query cap.
#
# Driven entirely by settings.py - see run_playwright below.

import re
import time
import datetime
import logging
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Page

from .common import read_lines, write_outputs, write_failures

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

FEED_WAIT_MS = 15000          # how long to wait for the feed to first appear
SCROLL_PAUSE_MS = 1500        # pause between scroll attempts
SCROLL_STAGNANT_LIMIT = 4     # scrolls with no new results before we stop

# Selectors for the desktop /maps/search/ UI (stable as of 2026-04). If Google
# reskins and results stop loading, these are the first lines to update.
FEED_SELECTOR = "[role=feed]"
RESULT_SELECTOR = "[role=feed] a.hfpxzc"
END_OF_LIST_SELECTOR = "p:has-text(\"You've reached the end of the list\")"

# Maps result links use class hfpxzc; ads share the class but point at /aclk.
PLACE_HREF_RE = re.compile(r"/maps/place/")
SPONSORED_HREF_RE = re.compile(r"/aclk\?")


# ---------------------------------------------------------------------------
# Per-result metadata
# ---------------------------------------------------------------------------

def extract_minimal_metadata(href: str, name: str | None) -> dict:
    """Pull the minimal data a place-detail scraper needs from a result href."""
    pid_match = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", href)
    place_id_hex = pid_match.group(1) if pid_match else ""

    cid = ""
    if place_id_hex and ":" in place_id_hex:
        try:
            cid = str(int(place_id_hex.split(":")[1], 16))
        except ValueError:
            pass

    chij_match = re.search(r"!19s([A-Za-z0-9_-]+)", href)
    chij = chij_match.group(1) if chij_match else ""

    coord_match = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", href)
    lat = float(coord_match.group(1)) if coord_match else None
    lng = float(coord_match.group(2)) if coord_match else None

    return {
        "Name": name or "",
        "URL": href,
        "CID": cid,
        "ChIJ Place ID": chij,
        "Latitude": lat if lat is not None else "",
        "Longitude": lng if lng is not None else "",
        "Sponsored": "No",
    }


# ---------------------------------------------------------------------------
# Core scrape per query
# ---------------------------------------------------------------------------

def build_search_url(query: str) -> str:
    return f"https://www.google.com/maps/search/{quote_plus(query)}"


def scroll_and_collect(page: Page, max_results: int, on_row,
                       include_sponsored: bool = False) -> list[dict]:
    """
    Scroll the result feed until it stops growing / hits cap / end-of-list.

    `on_row` is called with each new link the instant it's found, so the data
    is preserved even if the run is interrupted mid-scroll (Ctrl+C). It also
    returns the list of rows for convenience.
    """
    seen_keys: set[str] = set()
    rows: list[dict] = []
    stagnant = 0
    last_count = 0

    try:
        page.wait_for_selector(FEED_SELECTOR, timeout=FEED_WAIT_MS)
    except PWTimeoutError:
        log.warning("Feed never appeared. Page may have failed to load or "
                    "Google served a different layout (mobile? consent gate?).")
        return rows

    while True:
        items = page.query_selector_all(RESULT_SELECTOR)
        for el in items:
            href = el.get_attribute("href") or ""
            aria = el.get_attribute("aria-label") or ""

            if SPONSORED_HREF_RE.search(href):
                # /aclk ad URLs aren't usable by a place-detail scraper, so we
                # skip them regardless of include_sponsored.
                continue
            if not PLACE_HREF_RE.search(href):
                continue

            row = extract_minimal_metadata(href, aria)
            key = row["CID"] or row["ChIJ Place ID"] or row["URL"]
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append(row)
            on_row(row)   # capture immediately, before any further scrolling

            # max_results <= 0 means "collect all" - keep going until the end
            # of the list or scrolling stops producing new results.
            if max_results > 0 and len(rows) >= max_results:
                log.info("    cap reached (%d results)", max_results)
                return rows

        if len(rows) == last_count:
            stagnant += 1
        else:
            stagnant = 0
        last_count = len(rows)

        if page.query_selector(END_OF_LIST_SELECTOR):
            log.info("    end of list reached (%d results)", len(rows))
            return rows

        if stagnant >= SCROLL_STAGNANT_LIMIT:
            log.info("    no new results after %d scrolls - stopping (%d results)",
                     stagnant, len(rows))
            return rows

        page.evaluate(
            """(sel) => { const f = document.querySelector(sel);
                          if (f) f.scrollTo(0, f.scrollHeight); }""",
            FEED_SELECTOR,
        )
        page.wait_for_timeout(SCROLL_PAUSE_MS)


def scrape_query(page: Page, query: str, max_results: int, on_row,
                 include_sponsored: bool = False) -> list[dict]:
    """Navigate to a search query and scroll-collect, reporting each row live."""
    url = build_search_url(query)
    log.info("    -> %s", url)
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
    except PWTimeoutError:
        log.error("    page navigation timed out")
        return []

    try:
        consent = page.query_selector("button:has-text('Accept all')") or \
                  page.query_selector("button:has-text('I agree')")
        if consent:
            consent.click()
            page.wait_for_timeout(1500)
    except Exception:
        pass

    page.wait_for_timeout(2000)
    return scroll_and_collect(page, max_results, on_row, include_sponsored)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_playwright(cfg):
    """Run the Playwright collector using values from the settings module `cfg`."""
    categories = read_lines(cfg.CATEGORIES_FILE)
    locations = read_lines(cfg.LOCATIONS_FILE)
    if not categories:
        raise SystemExit(f"No categories found in {cfg.CATEGORIES_FILE}")
    if not locations:
        raise SystemExit(f"No locations found in {cfg.LOCATIONS_FILE}")

    pairs = [(c, l) for c in categories for l in locations]
    if cfg.PAIR_LIMIT > 0:
        pairs = pairs[:cfg.PAIR_LIMIT]

    log.info("Loaded %d categories x %d locations = %d pairs (Playwright mode)",
             len(categories), len(locations), len(pairs))

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    basename = getattr(cfg, "OUTPUT_NAME", "") or f"links_pw_{ts}"

    all_rows: list[dict] = []
    failed: list[str] = []   # "<category> in <location>" searches that crashed

    # Whatever happens below - finishing normally, Ctrl+C, or an unexpected
    # error - the `finally` block always saves what was collected so far.
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=cfg.HEADLESS)
            ctx = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()

            try:
                for i, (cat, loc) in enumerate(pairs, 1):
                    query = f"{cat} in {loc}"
                    log.info("[%d/%d] === %s ===", i, len(pairs), query)

                    # Tag each link and add it to all_rows the moment it's found,
                    # so an interrupt mid-query still keeps what was collected.
                    def on_row(r, cat=cat, loc=loc, query=query):
                        r["Search Category"] = cat
                        r["Search Location"] = loc
                        r["Search Query"] = query
                        all_rows.append(r)

                    try:
                        rows = scrape_query(page, query, cfg.MAX_RESULTS, on_row,
                                            include_sponsored=cfg.INCLUDE_SPONSORED)
                    except Exception as e:
                        # A single crashed query shouldn't abort the run.
                        log.error("Query crashed: %s", e)
                        failed.append(query)
                        rows = []

                    log.info("    -> %d links", len(rows))

                    if i < len(pairs) and cfg.PER_PAIR_DELAY > 0:
                        time.sleep(cfg.PER_PAIR_DELAY)
            finally:
                browser.close()
    except KeyboardInterrupt:
        log.warning("Interrupted by user - saving data collected so far...")
    except Exception as e:
        log.error("Run stopped by an unexpected error - saving collected data "
                  "first. (%s)", e, exc_info=True)
    finally:
        csv_path = write_outputs(all_rows, cfg.OUTPUT_DIR, basename)
        failed_path = write_failures(failed, cfg.OUTPUT_DIR, basename)
        log.info("=" * 60)
        if csv_path:
            log.info("DONE. Wrote %s (+ .xlsx)", csv_path)
        else:
            log.info("DONE. No links collected.")
        if failed_path:
            log.info("%d search(es) failed - see %s", len(failed), failed_path)
