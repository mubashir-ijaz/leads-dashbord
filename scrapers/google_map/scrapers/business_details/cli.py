# Interactive setup for the BUSINESS DETAILS scraper.
#
# Asks a short series of questions, using the values in settings.py as the
# defaults (just press Enter to accept a default). Answers are written back onto
# the settings module, so the rest of the program reads them as usual.
#
# The prompts (colored, arrow-key menus) and logging live in the shared
# project-root module ``console.py``. When input isn't interactive
# (piped/scheduled), the questions are skipped and settings.py is used as-is.

import logging
import os
import re
import sys
from pathlib import Path

# Make the project-root helpers (console.py) importable no matter the CWD.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import console

log = logging.getLogger(__name__)


def _sanitize_basename(name: str) -> str:
    """Reduce arbitrary user text to a safe file name (no path, no extension)."""
    name = name.strip().strip('"').strip("'")
    name = os.path.basename(name)                       # drop any directory part
    name = re.sub(r"\.(csv|xlsx)$", "", name, flags=re.I)  # drop a trailing ext
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)          # replace illegal chars
    return name.strip(" .")


def speed_options() -> list[tuple]:
    """Speed presets as (thread_count, label, description) tuples.

    These are network-bound (not CPU-bound) requests, so Turbo is a high fixed
    concurrency rather than the CPU-core count. The chosen value IS the number
    of worker threads, so it can be stored straight onto settings.MAX_WORKERS.
    """
    turbo = 32
    return [
        (2, "Normal", "2 threads  — safest, least likely to be blocked."),
        (4, "Fast", "4 threads  — quicker on long lists."),
        (8, "Rapid", "8 threads  — faster, more rate-limit risk."),
        (turbo, "Turbo", f"{turbo} threads — maximum (network I/O; highest block risk)."),
    ]


BANNER = "Google Maps Business Details Scraper"


def _list_link_csvs(settings) -> list:
    """CSVs in the link collector's output folder, newest first."""
    out_dir = settings.PROJECT_ROOT / "output" / "link_collector"
    if not out_dir.exists():
        return []
    return sorted(out_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)


def ask_input_source(settings) -> None:
    """Let the user keep links.txt or pick a collected-links CSV."""
    csvs = _list_link_csvs(settings)
    options = [(None, "links.txt", str(settings.INPUT_FILE))]
    for p in csvs:
        options.append((p, p.name, "collected links"))

    choice = console.select("Where should the links come from?", options,
                            default_value=None)
    if choice is not None:
        settings.INPUT_FILE = choice


def configure(settings, ask_input: bool = True, ask_output_name: bool = True) -> None:
    """Run the questionnaire and write answers back onto the settings module."""
    if not sys.stdin.isatty():
        log.info("Non-interactive session detected — using settings.py as-is.")
        return

    console.banner(BANNER)
    console.note('For any question, press Enter to accept the default '
                 '(shown in green / marked "(default)").')

    # 0. Input source -------------------------------------------------------
    if ask_input:
        ask_input_source(settings)
    else:
        console.note(f"Input: {settings.INPUT_FILE}")

    # 1. Detail level -------------------------------------------------------
    settings.DETAIL_LEVEL = console.select(
        "How much detail per business?",
        [
            ("basic", "Basic", "Core fields: name, phone, website, address, hours, rating."),
            ("detailed", "Detailed", "Basic + description, services, photos, IDs, city/street..."),
        ],
        default_value=getattr(settings, "DETAIL_LEVEL", "detailed"),
    )

    # 2. Proxy --------------------------------------------------------------
    if settings.PROXY_URL:
        settings.USE_PROXY = console.confirm(
            "Route requests through the configured proxy?",
            default=settings.USE_PROXY,
        )

    # 3. Speed (parallel threads) ------------------------------------------
    settings.MAX_WORKERS = console.select(
        "How fast should it run? (more threads = faster, but higher block risk)",
        speed_options(),
        default_value=getattr(settings, "MAX_WORKERS", 2),
    )

    # 4. Email / social-handle enrichment -----------------------------------
    want_emails = console.confirm("Also extract emails from each website?", default=True)
    want_socials = console.confirm("Also extract social handles?", default=True)
    if want_emails or want_socials:
        all_emails = console.confirm(
            "Collect ALL emails per site? (No = best one only)", default=False)
        settings.EMAIL_OPTIONS = {
            "want_emails": want_emails,
            "want_socials": want_socials,
            "mode": "all" if all_emails else "single",
        }
    else:
        settings.EMAIL_OPTIONS = None

    # 5. Output file name ----------------------------------------------------
    if ask_output_name:
        current = _sanitize_basename(settings.OUTPUT_FILENAME_PATTERN) \
            if "%" not in settings.OUTPUT_FILENAME_PATTERN else ""
        name = console.ask_text(
            "Name for the output file, without extension? (Enter = auto timestamp)",
            default=current,
            transform=_sanitize_basename,
            validate=lambda v: bool(v),
        )
        if name:
            settings.OUTPUT_FILENAME_PATTERN = name

    _print_summary(settings)


def _print_summary(settings) -> None:
    console.rule("Configuration")
    console.summary_row("Detail level",
                        "Detailed" if settings.DETAIL_LEVEL == "detailed" else "Basic")
    if settings.PROXY_URL:
        console.summary_row("Use proxy", "Yes" if settings.USE_PROXY else "No")
    console.summary_row("Speed", f"{settings.MAX_WORKERS} threads")

    eo = getattr(settings, "EMAIL_OPTIONS", None)
    if eo:
        bits = []
        if eo.get("want_emails"):
            bits.append("emails (%s)" % ("all" if eo.get("mode") == "all" else "best"))
        if eo.get("want_socials"):
            bits.append("socials")
        console.summary_row("Contact extraction", ", ".join(bits))
    else:
        console.summary_row("Contact extraction", "off")
    console.summary_row("Input file", str(settings.INPUT_FILE))
    console.summary_row("Output folder", str(settings.OUTPUT_DIR))
    console.summary_row(
        "Output name",
        settings.OUTPUT_FILENAME_PATTERN if "%" not in settings.OUTPUT_FILENAME_PATTERN
        else "auto timestamp")
    print(f"{console.C_TITLE}{'-' * 60}{console.RESET}")

    if not console.confirm("Start the extraction now?", default=True):
        raise SystemExit("Cancelled. No changes made.")
    print()
