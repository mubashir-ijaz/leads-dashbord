"""Network layer: HTTP fetch, subpage discovery, FB/JS fallbacks."""

from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

import httpx
import parsel

from .config import CONTACT_PATH_KEYWORDS, DEFAULT_HEADERS
from .extractors import extract_emails_text


async def fetch(client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
    """GET with one retry; only return text/html responses."""
    for attempt in range(2):
        try:
            resp = await client.get(url, follow_redirects=True)
        except (httpx.HTTPError, httpx.InvalidURL):
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
            return None
        ctype = resp.headers.get('content-type', '')
        if resp.status_code < 400 and ('html' in ctype or 'text' in ctype or not ctype):
            return resp
        return None
    return None


def candidate_subpages(
    selector: parsel.Selector, base_url: str, max_pages: int
) -> list[str]:
    """Same-domain links to the pages most likely to hold an email, best first.

    Only links whose URL path contains one of CONTACT_PATH_KEYWORDS are kept, and
    they're ranked by that keyword's priority (contact > legal > about > team …),
    then by page order — so with a small `max_pages` we fetch the highest-value
    pages (contact/legal) and skip everything else.
    """
    base_netloc = urlparse(base_url).netloc.lower().replace('www.', '')
    seen: set[str] = set()
    ranked: list[tuple[int, int, str]] = []   # (priority, page order, url)

    for order, href in enumerate(selector.xpath('//a/@href').getall()):
        if not href or href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        url = urljoin(base_url, href).split('#', 1)[0]
        if url in seen:
            continue
        netloc = urlparse(url).netloc.lower().replace('www.', '')
        if netloc != base_netloc:
            continue
        path = urlparse(url).path.lower()
        priority = next(
            (i for i, k in enumerate(CONTACT_PATH_KEYWORDS) if k in path), None
        )
        if priority is None:
            continue
        seen.add(url)
        ranked.append((priority, order, url))

    ranked.sort(key=lambda t: (t[0], t[1]))
    return [url for _priority, _order, url in ranked[:max_pages]]


async def fetch_facebook_email(
    client: httpx.AsyncClient, facebook_url: str
) -> set[str]:
    """Try to pull an email from a Facebook page's embedded JSON.

    Why kept: many small businesses (esp. lodges/real-estate) only publish
    their email on their FB page, so this is often the only signal available
    when the website itself hides contact info behind JS or images.
    """
    if not facebook_url:
        return set()
    try:
        resp = await client.get(
            facebook_url, headers=DEFAULT_HEADERS,
            follow_redirects=True, timeout=15,
        )
    except (httpx.HTTPError, httpx.InvalidURL):
        return set()
    if resp.status_code >= 400:
        return set()

    text = unquote(resp.text.replace('mailto:%20', ''))
    sel = parsel.Selector(text=text)
    json_blob = sel.xpath(
        'normalize-space(//script[@type="application/json"'
        ' and contains(text(), "website")])'
    ).get() or ''
    # FB often encodes '@' as '\u0040' inside JSON.
    cleaned = json_blob.replace('u0040', '@').replace('\\', '')
    return extract_emails_text(cleaned)


async def js_render(url: str) -> Optional[str]:
    """Last-resort Playwright render. Heavy; only call when nothing else works."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                ctx = await browser.new_context(user_agent=DEFAULT_HEADERS['user-agent'])
                page = await ctx.new_page()
                await page.goto(url, timeout=30000, wait_until='domcontentloaded')
                try:
                    await page.wait_for_load_state('networkidle', timeout=8000)
                except Exception:
                    pass
                return await page.content()
            finally:
                await browser.close()
    except Exception:
        return None
