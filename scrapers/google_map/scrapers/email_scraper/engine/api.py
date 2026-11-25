"""High-level synchronous API for embedding the contact engine in the suite.

Two entry points:
  run_emails()       — standalone run; writes CSV + XLSX to output/email_scraper.
  collect_contacts() — in-memory run; returns {root_domain: row} for enriching
                       the business-details output (no files written).
"""

from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace

import tldextract

from .config import OUTPUT_DIR
from .cli import _noop_emit, run_async


def default_prefix() -> str:
    return f'Contacts - {datetime.datetime.now().strftime("%d.%m.%Y %I.%M.%S %p")}'


def _args(mode, max_subpages, concurrency, fb_fallback, js_fallback, output_prefix):
    return SimpleNamespace(
        mode=mode,
        concurrency=concurrency,
        max_subpages=max_subpages,
        fb_fallback=fb_fallback,
        js_fallback=js_fallback,
        resume=False,
        output_prefix=output_prefix,
    )


def root_domain(value: str) -> str:
    ext = tldextract.extract(value or '')
    if ext.suffix:
        return f'{ext.domain}.{ext.suffix}'.lower()
    return (ext.domain or '').lower()


def make_bar_emit(desc: str = 'Contacts'):
    """Return (emit, close): a lightweight tqdm progress bar driven by the
    run_async events, for embedded/batched runs that would otherwise be silent.

    Call the returned `close` when the run finishes to tidy the bar up (the
    embedded run does not emit a 'finish' event, so it won't close itself).
    """
    from tqdm import tqdm
    state = {'bar': None}

    def emit(event, **data):
        if event == 'start':
            state['bar'] = tqdm(total=data.get('total', 0), desc=desc)
        elif event == 'progress' and state['bar'] is not None:
            state['bar'].update(1)
        elif event == 'error' and state['bar'] is not None:
            state['bar'].write(f"[skip] {data.get('url', '')}: {data.get('message', '')}")

    def close():
        if state['bar'] is not None:
            state['bar'].close()
            state['bar'] = None

    return emit, close


def run_emails(*, websites=None, mode='single', want_emails=True, want_socials=True,
               max_subpages=3, concurrency=20, fb_fallback=True, js_fallback=False,
               output_prefix=None, emit=_noop_emit, cancel_event=None):
    """Standalone run. Writes CSV + XLSX to output/email_scraper.

    Returns (csv_path | None, xlsx_path | None, rows).
    """
    prefix = output_prefix or default_prefix()
    args = _args(mode, max_subpages, concurrency, fb_fallback, js_fallback, prefix)
    rows = asyncio.run(run_async(
        args, websites_override=websites, emit=emit, cancel_event=cancel_event,
        write_files=True, want_emails=want_emails, want_socials=want_socials,
    ))
    csv_path = OUTPUT_DIR / f'{prefix}.csv'
    xlsx_path = OUTPUT_DIR / f'{prefix}.xlsx'
    return (csv_path if csv_path.exists() else None,
            xlsx_path if xlsx_path.exists() else None,
            rows)


def collect_contacts(websites, *, mode='single', want_emails=True, want_socials=True,
                     max_subpages=3, concurrency=20, fb_fallback=True,
                     js_fallback=False, emit=_noop_emit):
    """In-memory run used to enrich another scraper's output.

    Returns {root_domain: full_row_dict}. No files are written.
    """
    prefix = default_prefix()
    args = _args(mode, max_subpages, concurrency, fb_fallback, js_fallback, prefix)
    rows = asyncio.run(run_async(
        args, websites_override=list(websites), emit=emit,
        write_files=False, want_emails=want_emails, want_socials=want_socials,
    ))
    by_domain: dict[str, dict] = {}
    for row in rows:
        dom = root_domain(row.get('Domain', ''))
        if dom and dom not in by_domain:
            by_domain[dom] = row
    return by_domain
