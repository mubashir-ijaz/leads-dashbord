#!/usr/bin/env python3
"""
Lead Campaign — master entry point.

    python run.py

Pick a scraper, run it (each one has its own menu / options — choose
whatever you need there), and when it finishes the new leads it wrote are
published to the dashboard (data_leads.js) and pushed to git automatically.

Bundles:
  1. Google Maps scraper   (scrapers/google_map)              — its own menu:
     link collector / business details / both / emails.
  2. Low-Rating / No-Website leads   (scrapers/low_rating_review_leads) —
     full pipeline: collect links -> scrape details -> filter into leads.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRAPERS_DIR = HERE / "scrapers"
GOOGLE_MAP_DIR = SCRAPERS_DIR / "google_map"
LOW_RATING_DIR = SCRAPERS_DIR / "low_rating_review_leads"

sys.path.insert(0, str(GOOGLE_MAP_DIR))       # for the shared console.py helper
sys.path.insert(0, str(HERE))
import console                                 # noqa: E402  (google_map/console.py)
from tools.publish_leads import publish        # noqa: E402

OUTPUT_DIRS = [
    GOOGLE_MAP_DIR / "output" / "business_details",
    LOW_RATING_DIR / "output",
]


# ---------------------------------------------------------------------------
# Track which output file a run produced
# ---------------------------------------------------------------------------

def _snapshot() -> dict[Path, set[Path]]:
    return {
        d: (set(d.glob("*.xlsx")) | set(d.glob("*.csv")))
        for d in OUTPUT_DIRS if d.exists()
    }


def _new_files(before: dict[Path, set[Path]]) -> list[Path]:
    after = _snapshot()
    new: list[Path] = []
    for d, files_after in after.items():
        new.extend(files_after - before.get(d, set()))
    # Drop Excel's own lock files and anything mid-write.
    new = [p for p in new if not p.name.startswith("~$")]
    return sorted(new, key=lambda p: p.stat().st_mtime)


# ---------------------------------------------------------------------------
# Run each scraper (each one owns its own menu / prompts)
# ---------------------------------------------------------------------------

def run_google_map() -> list[Path]:
    console.rule("Google Maps scraper")
    console.note("Its own menu will ask which part to run "
                 "(links / business details / both / emails).")
    before = _snapshot()
    subprocess.run([sys.executable, "run.py"], cwd=str(GOOGLE_MAP_DIR))
    return _new_files(before)


def _ask_low_rating_args() -> list[str]:
    mode = console.select(
        "Low-Rating / No-Website Leads — how much do you want to run?",
        [
            ("full", "Full run", "every category x every state — the full pipeline"),
            ("test", "Quick test", "1 category x 1 state, to check everything works"),
            ("limit", "Limited run", "only the first N category x state searches"),
        ],
        default_value="full",
    )
    args: list[str] = []
    if mode == "test":
        args.append("--test")
    elif mode == "limit":
        n = console.ask_int("How many searches to run?", default=10, minimum=1)
        args += ["--limit", str(n)]
    if not console.confirm(
        "Also look up Facebook / Instagram / LinkedIn by name for no-website leads?",
        default=True,
    ):
        args.append("--no-social")
    return args


def run_low_rating() -> list[Path]:
    console.rule("Low-Rating / No-Website Leads scraper")
    args = _ask_low_rating_args()
    before = _snapshot()
    subprocess.run([sys.executable, "run_leads.py", *args], cwd=str(LOW_RATING_DIR))
    return _new_files(before)


# ---------------------------------------------------------------------------
# Publish whatever the run produced
# ---------------------------------------------------------------------------

def publish_new_files(new_files: list[Path]) -> None:
    if not new_files:
        console.note("No new output file was produced — nothing to publish.")
        return

    out_file = new_files[-1]           # newest
    console.rule("Publish to dashboard")
    label = console.ask_text(
        "What name should this batch show as on the dashboard (category)?",
        default=out_file.stem,
        allow_empty=False,
    )
    publish(out_file, label)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    console.setup_logging()
    console.banner("Lead Campaign")
    choice = console.select(
        "Which scraper do you want to run?",
        [
            ("google_map", "Google Maps scraper",
             "link collector / business details / emails — pick options in its own menu"),
            ("low_rating", "Low-Rating / No-Website leads",
             "full pipeline: links -> business details -> filter -> leads"),
        ],
        default_value="google_map",
    )

    new_files = run_google_map() if choice == "google_map" else run_low_rating()
    publish_new_files(new_files)


if __name__ == "__main__":
    main()
