#!/usr/bin/env python3
"""
Google Maps & Contacts Scraper — command-line entry point.

Run it with no arguments to pick a scraper from a text menu:

    python run.py

Or run a scraper directly:

    python run.py links                 # ask the questions, then run
    python run.py links     --defaults  # skip the questions, use settings.py as-is
    python run.py business  --defaults
    python run.py both      --defaults
    python run.py emails    --defaults

It bundles three scrapers:

  1. Link Collector    — searches "<category> in <location>" and collects the
                         Google Maps place links. (scrapers/link_collector)
  2. Business Details  — takes a file of place links and extracts full business
                         details for each. (scrapers/business_details)
  3. Emails & Socials  — crawls websites for emails / social handles.
                         (scrapers/email_scraper)

  Inputs : input/   Outputs: output/   (one subfolder per scraper)
"""

import argparse

import console
import runner


def _cli_choose() -> str:
    console.banner("Google Maps & Contacts Scraper")
    console.note("(Up/Down to move, Enter to select)")
    return console.select(
        "Which scraper would you like to run?",
        [
            ("links", "Link Collector", "collect place links"),
            ("business", "Business Details", "extract details for a list of links"),
            ("both", "Both", "collect links, then scrape their details"),
            ("emails", "Emails & Socials", "crawl websites for emails / social handles"),
        ],
        default_value="links",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run the Google Maps scrapers (link collector, business "
                    "details, emails, or both). With no arguments, shows a text "
                    "menu to choose from."
    )
    parser.add_argument(
        "scraper", nargs="?", choices=["links", "business", "both", "emails"],
        help="Run this scraper directly. Omit to choose from the text menu.",
    )
    parser.add_argument("--defaults", "-d", action="store_true",
                        help="Skip the questions and use settings.py as-is.")
    args = parser.parse_args()

    console.setup_logging()

    # A scraper named on the command line runs directly; otherwise show the menu.
    target = args.scraper or _cli_choose()
    runner.run_cli(target, args.defaults)


if __name__ == "__main__":
    main()
