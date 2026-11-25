# Interactive setup shown when you run `python run.py`.
#
# It asks a short series of questions, using the values in settings.py as the
# defaults (just press Enter to accept a default). The answers are applied back
# onto the settings module, so the rest of the program reads them as usual.
#
# The prompts (colored, arrow-key menus) and logging live in the shared
# project-root module ``console.py``. When input isn't interactive (a scheduled
# job, piped input, or --defaults), the questions are skipped and settings.py is
# used as-is.

import logging
import os
import re
import sys
from pathlib import Path

# Make the project-root helpers (console.py) importable no matter the CWD.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import console

log = logging.getLogger(__name__)


def speed_options() -> list[tuple]:
    """Speed presets as (thread_count, label, description) tuples.

    These are network-bound (not CPU-bound) requests, so Turbo is a high fixed
    concurrency rather than the CPU-core count. The chosen value IS the number
    of parallel searches, so it can be stored straight onto API_MAX_WORKERS.
    """
    turbo = 32
    return [
        (2, "Normal", "2 threads  — safest, least likely to be rate-limited."),
        (4, "Fast", "4 threads  — quicker on long lists."),
        (8, "Rapid", "8 threads  — faster, more 429 (rate-limit) risk."),
        (turbo, "Turbo", f"{turbo} threads — maximum (network I/O; highest 429 risk)."),
    ]


def _sanitize_basename(name: str) -> str:
    """Reduce arbitrary user text to a safe file name (no path, no extension)."""
    name = name.strip().strip('"').strip("'")
    name = os.path.basename(name)                       # drop any directory part
    name = re.sub(r"\.(csv|xlsx)$", "", name, flags=re.I)  # drop a trailing ext
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)          # replace illegal chars
    return name.strip(" .")


BANNER = "Google Maps Link Collector"


def configure(settings) -> None:
    """
    Run the interactive questionnaire and write the answers back onto the
    settings module. Skipped automatically when input isn't a terminal.
    """
    if not sys.stdin.isatty():
        log.info("Non-interactive session detected — using settings.py as-is.")
        return

    console.banner(BANNER)
    console.note('For any question, press Enter to accept the default '
                 '(shown in green / marked "(default)").')

    # 1. Collector ----------------------------------------------------------
    settings.COLLECTOR = console.select(
        "Which collector would you like to use?",
        [
            ("api", "API", "Fast. Up to ~20 results per query (or 100s tiled)."),
            ("playwright", "Playwright", "Browser-based. Up to ~120 results per query."),
        ],
        default_value=settings.COLLECTOR,
    )

    # 2. Collector-specific questions --------------------------------------
    if settings.COLLECTOR == "api":
        settings.API_TILE = console.select(
            "Which search mode?",
            [
                (False, "Single", "One request per query (~20 results). Fastest."),
                (True, "Tiled", "Grid of requests per query (100s of results)."),
            ],
            default_value=settings.API_TILE,
        )
        if settings.API_TILE:
            console.note(f"  Tiled mode will cover the bounding box set in "
                         f"settings.py:\n    API_BBOX = {settings.API_BBOX}")

        # Speed (parallel searches) ----------------------------------------
        settings.API_MAX_WORKERS = console.select(
            "How fast should searches run? (more threads = faster, but more "
            "rate-limit errors)",
            speed_options(),
            default_value=getattr(settings, "API_MAX_WORKERS", 2),
        )

        if settings.PROXY_URL:
            settings.USE_PROXY = console.confirm(
                "Route requests through the configured proxy?",
                default=settings.USE_PROXY,
            )
    else:  # playwright
        settings.HEADLESS = console.confirm(
            "Run the browser in headless mode (no visible window)?",
            default=settings.HEADLESS,
        )
        settings.MAX_RESULTS = console.ask_int(
            "Maximum results to collect per query? (0 = all)",
            default=settings.MAX_RESULTS,
            minimum=0,
        )
        settings.PER_PAIR_DELAY = console.ask_float(
            "Delay between queries, in seconds (helps avoid rate limits)?",
            default=settings.PER_PAIR_DELAY,
            minimum=0.0,
        )

    # 3. Common questions ---------------------------------------------------
    settings.INCLUDE_SPONSORED = console.confirm(
        "Include sponsored (ad) results?",
        default=settings.INCLUDE_SPONSORED,
    )
    settings.PAIR_LIMIT = console.ask_int(
        "How many category x location searches to run? (0 = all)",
        default=settings.PAIR_LIMIT,
        minimum=0,
    )

    # 4. Output file name ---------------------------------------------------
    settings.OUTPUT_NAME = console.ask_text(
        "Name for the output files, without extension? (Enter = auto timestamp)",
        default=settings.OUTPUT_NAME,
        transform=_sanitize_basename,
        validate=lambda v: bool(v),
    )

    _print_summary(settings)


def _print_summary(settings) -> None:
    """Show a tidy recap of the chosen configuration before the run starts."""
    console.rule("Configuration")
    console.summary_row("Collector",
                        "API" if settings.COLLECTOR == "api" else "Playwright", width=22)

    if settings.COLLECTOR == "api":
        console.summary_row("Search mode",
                            "Tiled" if settings.API_TILE else "Single", width=22)
        workers = getattr(settings, "API_MAX_WORKERS", 2)
        console.summary_row("Speed", f"{workers} threads", width=22)
        if settings.PROXY_URL:
            console.summary_row("Use proxy", "Yes" if settings.USE_PROXY else "No", width=22)
    else:
        console.summary_row("Headless", "Yes" if settings.HEADLESS else "No", width=22)
        console.summary_row("Max results/query",
                            "All" if settings.MAX_RESULTS == 0 else str(settings.MAX_RESULTS),
                            width=22)
        console.summary_row("Delay between queries", f"{settings.PER_PAIR_DELAY:g}s", width=22)

    console.summary_row("Include sponsored",
                        "Yes" if settings.INCLUDE_SPONSORED else "No", width=22)
    console.summary_row("Searches to run",
                        "All" if settings.PAIR_LIMIT == 0 else str(settings.PAIR_LIMIT),
                        width=22)
    console.summary_row("Output file",
                        f"{settings.OUTPUT_NAME}.csv / .xlsx" if settings.OUTPUT_NAME
                        else "Auto (timestamped)", width=22)
    print(f"{console.C_TITLE}{'-' * 60}{console.RESET}")

    if not console.confirm("Start the collection now?", default=True):
        raise SystemExit("Cancelled. No changes made.")
    print()
