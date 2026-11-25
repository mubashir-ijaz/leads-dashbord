# API collector: runs every category x location pair through the search API
# (single or tiled mode) and writes the link files. Driven entirely by
# settings.py - see run_api below.

import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .common import read_lines, write_outputs, write_failures
from .search_api import scrape_search_links, scrape_search_links_tiled

log = logging.getLogger(__name__)


def _collect_pair(cfg, cat, loc) -> list[dict]:
    """Run a single "<category> in <location>" search and tag its rows.

    Safe to call from a worker thread: the search_api helpers create their own
    requests session per call, so nothing is shared between threads.
    """
    query = f"{cat} in {loc}"
    if cfg.API_TILE:
        rows = scrape_search_links_tiled(
            query, cfg.API_BBOX,
            tile_size_deg=cfg.API_TILE_SIZE_DEG,
            zoom=cfg.API_TILE_ZOOM,
            include_sponsored=cfg.INCLUDE_SPONSORED,
        )
    else:
        rows = scrape_search_links(
            query, cfg.API_LAT, cfg.API_LNG, zoom=cfg.API_ZOOM,
            include_sponsored=cfg.INCLUDE_SPONSORED,
        )
    for r in rows:
        r["Search Category"] = cat
        r["Search Location"] = loc
        r["Search Query"] = query
    return rows


def run_api(cfg):
    """Run the API collector using values from the settings module `cfg`."""
    categories = read_lines(cfg.CATEGORIES_FILE)
    locations = read_lines(cfg.LOCATIONS_FILE)
    if not categories:
        raise SystemExit(f"No categories found in {cfg.CATEGORIES_FILE}")
    if not locations:
        raise SystemExit(f"No locations found in {cfg.LOCATIONS_FILE}")

    pairs = [(c, l) for c in categories for l in locations]
    if cfg.PAIR_LIMIT > 0:
        pairs = pairs[:cfg.PAIR_LIMIT]

    workers = max(1, int(getattr(cfg, "API_MAX_WORKERS", 1) or 1))

    log.info("Loaded %d categories x %d locations = %d pairs (mode=%s, workers=%d)",
             len(categories), len(locations), len(pairs),
             "TILED" if cfg.API_TILE else "SINGLE", workers)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    basename = getattr(cfg, "OUTPUT_NAME", "") or f"links_{ts}"

    all_rows: list[dict] = []
    failed: list[str] = []   # "<category> in <location>" searches that errored
    # Whatever happens below - finishing normally, Ctrl+C, or an unexpected
    # error - the `finally` block always saves what was collected so far.
    try:
        if workers <= 1:
            _run_sequential(cfg, pairs, all_rows, failed)
        else:
            _run_parallel(cfg, pairs, all_rows, failed, workers)
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


def _run_sequential(cfg, pairs, all_rows, failed):
    """Process each pair one at a time (API_MAX_WORKERS = 1)."""
    for i, (cat, loc) in enumerate(pairs, 1):
        query = f"{cat} in {loc}"
        log.info("[%d/%d] === %s ===", i, len(pairs), query)
        try:
            rows = _collect_pair(cfg, cat, loc)
        except Exception as e:
            # A single failed pair shouldn't abort the run.
            log.error("Pair (%s, %s) failed: %s", cat, loc, e)
            failed.append(query)
            continue
        log.info("    -> %d links", len(rows))
        all_rows.extend(rows)


def _run_parallel(cfg, pairs, all_rows, failed, workers):
    """Process several pairs at once with a thread pool (API_MAX_WORKERS > 1)."""
    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {ex.submit(_collect_pair, cfg, cat, loc): (cat, loc)
                   for cat, loc in pairs}
        # Results arrive as each search finishes (not in submit order); only the
        # main thread touches all_rows / failed, so no extra locking is needed.
        for done, fut in enumerate(as_completed(futures), 1):
            cat, loc = futures[fut]
            query = f"{cat} in {loc}"
            try:
                rows = fut.result()
            except Exception as e:
                log.error("Pair (%s, %s) failed: %s", cat, loc, e)
                failed.append(query)
                continue
            log.info("[%d/%d] %s -> %d links", done, len(pairs), query, len(rows))
            all_rows.extend(rows)
    finally:
        # On Ctrl+C / error, stop promptly instead of waiting for every queued
        # search; the outer finally still saves whatever was gathered.
        ex.shutdown(wait=False, cancel_futures=True)
