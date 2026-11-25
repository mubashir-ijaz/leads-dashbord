"""argparse + async run loop. Exposes ``run_async`` for embedding (e.g. the
business-details enrichment) and ``main`` for the terminal entry point."""

from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import sys
import threading
import warnings
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx
import urllib3
from tqdm import tqdm

from .config import DEFAULT_HEADERS, OUTPUT_DIR, WEBSITES_PATH
from .output import (
    CSVWriter,
    build_row,
    csv_to_xlsx,
    load_checkpoint,
    normalize_input_url,
    save_checkpoint,
    select_fieldnames,
)
from .pipeline import scrape_domain

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings('ignore')
logging.getLogger('httpx').setLevel(logging.WARNING)

log = logging.getLogger(__name__)


EmitFunc = Callable[..., None]


def _noop_emit(event: str, **data) -> None:
    return None


async def run_async(
    args,
    *,
    websites_override: Optional[list[str]] = None,
    emit: EmitFunc = _noop_emit,
    cancel_event: Optional[threading.Event] = None,
    write_files: bool = True,
    want_emails: bool = True,
    want_socials: bool = True,
) -> list[dict]:
    """Core run loop. Decoupled from terminal output so any caller can drive it.

    With write_files=True it writes <prefix>.csv / .xlsx into OUTPUT_DIR. With
    write_files=False it only collects rows in memory (used to enrich the
    business-details output). Either way the collected rows are returned.

    want_emails / want_socials choose which columns end up in the written files.

    Events emitted (via ``emit(event, **data)``):
      - start(total, mode, concurrency, fb_fallback, js_fallback)
      - progress(domain, url, emails, js, fb, row)
      - error(url, message)
      - finish(csv, xlsx, message=None, cancelled=False)
    """
    collected_rows: list[dict] = []
    failed_urls: list[str] = []   # websites we couldn't fetch / that errored
    if websites_override is not None:
        raw = [s for s in websites_override if s and s.strip()]
    else:
        raw = [
            ln for ln in WEBSITES_PATH.read_text(encoding='utf-8').splitlines()
            if ln.strip() and not ln.strip().startswith('#')
        ]

    seen_netloc: set[str] = set()
    urls: list[str] = []
    for line in raw:
        u = normalize_input_url(line)
        if not u:
            continue
        netloc = urlparse(u).netloc
        if netloc in seen_netloc:
            continue
        seen_netloc.add(netloc)
        urls.append(u)

    out_prefix = args.output_prefix
    if write_files:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / f'{out_prefix}.csv'
    checkpoint_path = (
        OUTPUT_DIR / f'{out_prefix}.checkpoint.json'
        if (args.resume and write_files) else None
    )
    processed = load_checkpoint(checkpoint_path) if checkpoint_path else set()
    pending = [u for u in urls if u not in processed]

    if not pending:
        emit('finish', csv=None, xlsx=None,
             message='Nothing to scrape — all entries already processed.')
        return collected_rows

    emit('start', total=len(pending), mode=args.mode,
         concurrency=args.concurrency,
         fb_fallback=args.fb_fallback, js_fallback=args.js_fallback)

    fieldnames = select_fieldnames(want_emails, want_socials)
    writer = CSVWriter(csv_path, fieldnames) if write_files else None
    sem = asyncio.Semaphore(args.concurrency)

    transport = httpx.AsyncHTTPTransport(retries=1, verify=False)
    limits = httpx.Limits(
        max_connections=args.concurrency * 2,
        max_keepalive_connections=args.concurrency,
    )
    timeout = httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=20.0)

    # Hard per-site deadline. httpx timeouts are per-operation, so a site that
    # trickles bytes (or ties up the connection pool) can still stall a worker
    # forever — this guarantees every site finishes or is abandoned in time, so
    # one bad site can never freeze the whole crawl. Longer when JS render is on.
    site_timeout = getattr(args, 'site_timeout', 90.0 if args.js_fallback else 45.0)

    cancelled = False

    async def worker(url: str):
        if cancel_event is not None and cancel_event.is_set():
            return
        async with sem:
            if cancel_event is not None and cancel_event.is_set():
                return
            try:
                result = await asyncio.wait_for(
                    scrape_domain(
                        client, url,
                        max_subpages=args.max_subpages,
                        js_fallback=args.js_fallback,
                        fb_fallback=args.fb_fallback,
                    ),
                    timeout=site_timeout,
                )
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                emit('error', url=url, message=f'timed out after {site_timeout:g}s')
                result = None
            except Exception as e:
                emit('error', url=url, message=f'{type(e).__name__}: {e}')
                result = None

            if result:
                row = build_row(result, args.mode)
                collected_rows.append(row)
                if writer is not None:
                    await writer.write(row)
                emit('progress',
                     domain=result.domain,
                     url=result.source_url,
                     emails=len(result.emails),
                     js=result.js_used,
                     fb=result.fb_used,
                     row=row)
            else:
                failed_urls.append(url)
                emit('progress',
                     domain=urlparse(url).netloc,
                     url=url,
                     emails=0,
                     js=False, fb=False, row=None)

            processed.add(url)
            if checkpoint_path:
                save_checkpoint(checkpoint_path, processed)

    async def cancel_watcher(tasks: list[asyncio.Task]):
        if cancel_event is None:
            return
        while not cancel_event.is_set():
            await asyncio.sleep(0.2)
            if all(t.done() for t in tasks):
                return
        nonlocal cancelled
        cancelled = True
        for t in tasks:
            if not t.done():
                t.cancel()

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, transport=transport,
        limits=limits, timeout=timeout,
    ) as client:
        tasks = [asyncio.create_task(worker(u)) for u in pending]
        watcher = asyncio.create_task(cancel_watcher(tasks))
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass

    # Save the URLs that failed to a uniquely-named text file (plain URLs, one
    # per line — re-feedable as websites.txt to retry just the failures).
    failed_path = None
    if write_files and failed_urls:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        failed_path = OUTPUT_DIR / f'{out_prefix}_failed.txt'
        try:
            failed_path.write_text('\n'.join(failed_urls) + '\n', encoding='utf-8')
        except OSError as e:
            emit('error', url='', message=f'Failed-URL file write failed: {e}')
            failed_path = None

    if write_files and csv_path.exists():
        xlsx_path = OUTPUT_DIR / f'{out_prefix}.xlsx'
        try:
            csv_to_xlsx(csv_path, xlsx_path)
        except Exception as e:
            emit('error', url='', message=f'XLSX export failed: {e}')
            xlsx_path = None
        emit('finish', csv=csv_path, xlsx=xlsx_path, failed=failed_path,
             cancelled=cancelled)
    elif write_files:
        emit('finish', csv=None, xlsx=None, failed=failed_path,
             message='No results written.', cancelled=cancelled)

    return collected_rows


# ----------------------------- Terminal CLI ---------------------------------

def _build_cli_emit():
    """Return an emit callable that drives a tqdm bar + prints to stdout."""
    state: dict = {'pbar': None}

    def emit(event: str, **data):
        if event == 'start':
            log.info(
                'Scraping %d domain(s) | mode=%s | concurrency=%s | '
                'fb_fallback=%s | js_fallback=%s',
                data['total'], data['mode'], data['concurrency'],
                data['fb_fallback'], data['js_fallback'],
            )
            state['pbar'] = tqdm(total=data['total'], desc='Scraping')
        elif event == 'progress':
            marker = (
                ' [JS]' if data.get('js')
                else ' [FB]' if data.get('fb') else ''
            )
            line = (
                f'[{data["domain"]}] '
                f'emails={data["emails"]}{marker}'
            )
            # Route through the bar's writer so the progress line and the log
            # don't fight over the terminal; fall back to the logger otherwise.
            if state['pbar']:
                state['pbar'].write(line)
                state['pbar'].update(1)
            else:
                log.info(line)
        elif event == 'error':
            line = f'{data.get("url", "")}: {data["message"]}'
            if state['pbar']:
                state['pbar'].write(f'[error] {line}')
            else:
                log.error(line)
        elif event == 'finish':
            if state['pbar']:
                state['pbar'].close()
            csv = data.get('csv')
            xlsx = data.get('xlsx')
            if csv and xlsx:
                log.info('Wrote %s and %s', csv.name, xlsx.name)
            elif csv:
                log.info('Wrote %s', csv.name)
            else:
                log.info(data.get('message') or 'No results written.')
            failed = data.get('failed')
            if failed:
                log.warning('Some sites failed — saved to %s (re-feed it to retry)',
                            failed.name)

    return emit


def parse_args(argv: Optional[list[str]] = None):
    default_prefix = (
        f'Contacts - {datetime.datetime.now().strftime("%d.%m.%Y %I.%M.%S %p")}'
    )
    p = argparse.ArgumentParser(
        description='Advanced async email/contact scraper.',
    )
    p.add_argument(
        '--mode', choices=['single', 'all'], default='single',
        help='single = pick best email per site; all = include every email found.',
    )
    p.add_argument('--concurrency', type=int, default=20)
    p.add_argument(
        '--max-subpages', type=int, default=3,
        help='Max high-value subpages (contact/about/team...) to fetch per site.',
    )
    p.add_argument(
        '--no-fb-fallback', dest='fb_fallback',
        action='store_false', default=True,
        help='Disable the Facebook-page email fallback.',
    )
    p.add_argument(
        '--js-fallback', action='store_true',
        help='Use Playwright to render JS only when nothing was found (slow).',
    )
    p.add_argument(
        '--no-resume', dest='resume',
        action='store_false', default=True,
        help='Do not load or write the checkpoint file.',
    )
    p.add_argument('--output-prefix', default=default_prefix)
    return p.parse_args(argv)


def main():
    args = parse_args()
    emit = _build_cli_emit()
    try:
        asyncio.run(run_async(args, emit=emit))
    except KeyboardInterrupt:
        log.warning('Interrupted. Checkpoint saved — re-run to resume.')
