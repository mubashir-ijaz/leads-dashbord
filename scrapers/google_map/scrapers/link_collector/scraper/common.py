# Shared helpers used by both collectors: input parsing, filename sanitizing,
# and writing the output files (per-pair lists, combined links.txt, xlsx).

import csv
import logging
import sys
from pathlib import Path

from openpyxl import Workbook

# Make the project-root helpers (console.py) importable no matter the CWD.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import console

log = logging.getLogger(__name__)

# The three columns every output file has: the extracted link, the category
# that was searched, and the location that was searched.
OUTPUT_COLUMNS = ["Link", "Category", "Location"]


def setup_logging(level=logging.INFO):
    """Configure root logging once, with the shared colored format."""
    console.setup_logging(level)


def read_lines(path) -> list[str]:
    """Read non-empty, non-comment lines from a file, preserving order, deduped."""
    path = Path(path)
    if not path.exists():
        log.error("File not found: %s", path)
        return []
    seen, out = set(), []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def dedupe_rows(rows: list[dict]) -> list[dict]:
    """Dedupe across the whole run, preferring CID, then ChIJ ID, then URL."""
    seen, out = set(), []
    for r in rows:
        key = r.get("CID") or r.get("ChIJ Place ID") or r.get("URL")
        if key and key not in seen:
            seen.add(key)
            out.append(r)
    return out


def write_failures(failures: list[str], output_dir: Path, basename: str) -> Path | None:
    """
    Write the searches/URLs that failed during a run to a uniquely-named text
    file (one per line) so they can be inspected or retried.

    File: <output_dir>/<basename>_failed.txt
    Returns the path, or None when there were no failures (no file is created).
    """
    if not failures:
        return None
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{basename}_failed.txt"
    try:
        with open(path, "w", encoding="utf-8") as f:
            for item in failures:
                f.write(f"{item}\n")
        log.info("Wrote %s (%d failed)", path, len(failures))
    except OSError as e:
        log.error("Could not write %s: %s", path, e)
        return None
    return path


def write_outputs(rows: list[dict], output_dir: Path, basename: str) -> Path | None:
    """
    Write ONE CSV and ONE Excel file for the whole extraction, deduped globally.

    Both files have the same three columns: Link, Category, Location.
      - <basename>.csv
      - <basename>.xlsx

    Returns the path to the CSV (or None if there was nothing to write).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not rows:
        log.info("No rows to write - skipping output files")
        return None

    deduped = dedupe_rows(rows)
    log.info("%d rows -> %d unique after global dedup", len(rows), len(deduped))

    records = [
        [r.get("URL", ""), r.get("Search Category", ""), r.get("Search Location", "")]
        for r in deduped
    ]

    # CSV - utf-8-sig so Excel opens non-ASCII names correctly on double-click.
    # Written first so the data is safe even if the Excel step fails (e.g. the
    # .xlsx is currently open in Excel and locked).
    csv_path = output_dir / f"{basename}.csv"
    try:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(OUTPUT_COLUMNS)
            writer.writerows(records)
        log.info("Wrote %s (%d links)", csv_path, len(records))
    except OSError as e:
        log.error("Could not write %s: %s", csv_path, e)
        csv_path = None

    # Excel
    xlsx_path = output_dir / f"{basename}.xlsx"
    try:
        wb = Workbook()
        ws = wb.active
        ws.append(OUTPUT_COLUMNS)
        for rec in records:
            ws.append(rec)
        wb.save(str(xlsx_path))
        log.info("Wrote %s (%d links)", xlsx_path, len(records))
    except OSError as e:
        log.error("Could not write %s (is it open in Excel?): %s", xlsx_path, e)

    return csv_path
