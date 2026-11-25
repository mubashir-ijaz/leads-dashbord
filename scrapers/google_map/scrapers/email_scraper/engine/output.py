"""CSV output, XLSX conversion, checkpointing, and row shaping."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import Workbook

from .config import FIELDNAMES
from .extractors import best_email
from .pipeline import ScrapeResult


class CSVWriter:
    """Async-locked DictWriter — header on first write, append after."""

    def __init__(self, path: Path, fieldnames: list[str]):
        self.path = path
        self.fieldnames = fieldnames
        self._lock = asyncio.Lock()
        self._initialized = path.exists() and path.stat().st_size > 0

    async def write(self, row: dict):
        async with self._lock:
            mode = 'a' if self._initialized else 'w'
            with self.path.open(mode, encoding='utf-8', newline='') as f:
                # extrasaction='ignore' lets us write a subset of columns (e.g.
                # emails-only or socials-only) from a full row dict.
                w = csv.DictWriter(f, fieldnames=self.fieldnames,
                                   extrasaction='ignore')
                if not self._initialized:
                    w.writeheader()
                    self._initialized = True
                w.writerow(row)


def load_checkpoint(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding='utf-8')))
    except Exception:
        return set()


def save_checkpoint(path: Path, processed: set[str]) -> None:
    path.write_text(json.dumps(sorted(processed)), encoding='utf-8')


SOCIAL_COLUMNS = ['Facebook', 'Instagram', 'Twitter', 'LinkedIn', 'YouTube', 'TikTok']


def select_fieldnames(want_emails: bool, want_socials: bool) -> list[str]:
    """Output columns to keep, based on the Extract emails / socials toggles."""
    cols = ['Domain', 'Source URL']
    if want_emails:
        cols += ['Emails', 'JS Rendered']
    if want_socials:
        cols += list(SOCIAL_COLUMNS)
    return cols


def normalize_input_url(s: str) -> str:
    s = s.strip()
    if not s:
        return ''
    if not urlparse(s).scheme:
        s = 'http://' + s
    return s


def build_row(result: ScrapeResult, mode: str) -> dict:
    if mode == 'single':
        emails_field = best_email(
            set(result.emails), result.domain, result.mailto_emails
        ) or ''
    else:
        emails_field = '; '.join(result.emails)

    js_marker = 'yes' if result.js_used else ('fb' if result.fb_used else '')

    return {
        'Domain': result.domain,
        'Source URL': result.source_url,
        'Emails': emails_field,
        'JS Rendered': js_marker,
        'Facebook': result.socials.get('Facebook', ''),
        'Instagram': result.socials.get('Instagram', ''),
        'Twitter': result.socials.get('Twitter', ''),
        'LinkedIn': result.socials.get('LinkedIn', ''),
        'YouTube': result.socials.get('YouTube', ''),
        'TikTok': result.socials.get('TikTok', ''),
    }


def csv_to_xlsx(csv_path: Path, xlsx_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    with csv_path.open(encoding='utf-8') as f:
        for row in csv.reader(f):
            ws.append(row)
    wb.save(xlsx_path)


__all__ = [
    'CSVWriter',
    'FIELDNAMES',
    'SOCIAL_COLUMNS',
    'build_row',
    'csv_to_xlsx',
    'load_checkpoint',
    'normalize_input_url',
    'save_checkpoint',
    'select_fieldnames',
]
