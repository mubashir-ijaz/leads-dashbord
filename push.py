#!/usr/bin/env python3
"""
Push a scraper's finished output file to the dashboard.

    python push.py

Asks which scraper the file came from (Low-Rating leads or Google Maps),
lists the files sitting in that scraper's output folder, lets you pick one,
asks what to call the batch (and whether to replace or merge with anything
already published under that name), then updates data_leads.js, archives the
source file, and commits + pushes to git.

Run this any time after a scraper has produced a file — it does not need to
run right after run.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRAPERS_DIR = HERE / "scrapers"

sys.path.insert(0, str(SCRAPERS_DIR / "google_map"))   # shared console.py helper
sys.path.insert(0, str(HERE))
import console                                          # noqa: E402
from tools.publish_leads import publish                 # noqa: E402

SOURCES = {
    "google_map": ("Google Maps scraper",
                   SCRAPERS_DIR / "google_map" / "output" / "business_details"),
    "low_rating": ("Low-Rating / No-Website leads",
                   SCRAPERS_DIR / "low_rating_review_leads" / "output"),
}


def _list_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files = [p for p in folder.glob("*.xlsx") if not p.name.startswith("~$")]
    files += list(folder.glob("*.csv"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def choose_scraper() -> Path:
    key = console.select(
        "Which scraper's output do you want to push?",
        [(k, label, str(folder)) for k, (label, folder) in SOURCES.items()],
        default_value="google_map",
    )
    return SOURCES[key][1]


def choose_file(folder: Path) -> Path:
    files = _list_files(folder)
    if not files:
        raise SystemExit(f"No output files found in {folder}")
    return console.select(
        "Which file do you want to push?",
        [(p, p.name, f"{p.stat().st_size // 1024} KB") for p in files],
        default_value=files[0],
    )


def choose_mode() -> str:
    return console.select(
        "If this batch name already has leads on the dashboard, what should happen?",
        [
            ("replace", "Replace",
             "delete the old leads under this name first, then add this file"),
            ("merge", "Merge",
             "keep old leads, update matches, add anything new"),
        ],
        default_value="replace",
    )


def main() -> None:
    console.setup_logging()
    console.banner("Push leads to dashboard")

    folder = choose_scraper()
    file = choose_file(folder)
    label = console.ask_text(
        "What name should this batch show as on the dashboard (category)?",
        default=file.stem,
        allow_empty=False,
    )
    mode = choose_mode()
    publish(file, label, mode)


if __name__ == "__main__":
    main()
