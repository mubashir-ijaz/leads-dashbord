"""Per-domain orchestration: homepage → subpages → FB → JS fallback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote

import httpx
import parsel
import tldextract

from .crawler import (
    candidate_subpages,
    fetch,
    fetch_facebook_email,
    js_render,
)
from .extractors import (
    decode_cf_emails,
    extract_emails_mailto,
    extract_emails_text,
    extract_jsonld,
    extract_socials,
)


@dataclass
class ScrapeResult:
    domain: str
    source_url: str
    emails: list[str] = field(default_factory=list)
    mailto_emails: set[str] = field(default_factory=set)
    socials: dict[str, str] = field(default_factory=dict)
    js_used: bool = False
    fb_used: bool = False


def _root_domain(url: str) -> str:
    ext = tldextract.extract(url)
    return f'{ext.domain}.{ext.suffix}' if ext.suffix else ext.domain


def _extract_all(
    selector: parsel.Selector, raw_text: str
) -> tuple[set[str], set[str], dict[str, str]]:
    """Run every extractor over a single page.

    Returns (all_emails, mailto_subset, socials).
    """
    mailto = extract_emails_mailto(selector)
    jsonld_emails = extract_jsonld(selector)
    cf_emails = decode_cf_emails(selector)
    body_emails = extract_emails_text(raw_text)

    socials = extract_socials(raw_text)
    emails = mailto | jsonld_emails | cf_emails | body_emails
    return emails, mailto, socials


def _parse_home(raw_html: str, base_url: str, max_subpages: int):
    """Homepage: run every extractor AND discover contact subpages.

    Pure CPU work (lxml parse + regex). Runs via asyncio.to_thread so it never
    blocks the event loop — otherwise one slow/large page stalls every other
    site being crawled concurrently.
    """
    text = unquote(raw_html.replace('mailto:%20', ''))
    sel = parsel.Selector(text=text)
    extracted = _extract_all(sel, text)
    subs = candidate_subpages(sel, base_url, max_pages=max_subpages)
    return extracted, subs


def _parse_page(raw_html: str):
    """One subpage: run every extractor. CPU work — call via asyncio.to_thread."""
    text = unquote(raw_html.replace('mailto:%20', ''))
    sel = parsel.Selector(text=text)
    return _extract_all(sel, text)


async def scrape_domain(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_subpages: int,
    js_fallback: bool,
    fb_fallback: bool,
) -> Optional[ScrapeResult]:
    home = await fetch(client, url)
    if not home:
        return None

    final_url = str(home.url)
    site_domain = _root_domain(final_url)

    (emails, mailto_set, socials), sub_urls = \
        await asyncio.to_thread(_parse_home, home.text, final_url, max_subpages)

    if sub_urls:
        sub_resps = await asyncio.gather(
            *(fetch(client, u) for u in sub_urls), return_exceptions=False
        )
        parse_tasks = [asyncio.to_thread(_parse_page, r.text)
                       for r in sub_resps if r]
        for e, mt, soc in await asyncio.gather(*parse_tasks):
            emails |= e
            mailto_set |= mt
            for k, v in soc.items():
                if v and not socials.get(k):
                    socials[k] = v

    fb_used = False
    if not emails and fb_fallback:
        fb_url = socials.get('Facebook') or ''
        if fb_url:
            fb_emails = await fetch_facebook_email(client, fb_url)
            if fb_emails:
                emails |= fb_emails
                fb_used = True

    js_used = False
    if not emails and js_fallback:
        rendered = await js_render(final_url)
        if rendered:
            js_used = True
            sel = parsel.Selector(text=rendered)
            e, mt, soc = _extract_all(sel, rendered)
            emails |= e
            mailto_set |= mt
            for k, v in soc.items():
                if v and not socials.get(k):
                    socials[k] = v

    return ScrapeResult(
        domain=site_domain,
        source_url=final_url,
        emails=sorted(emails),
        mailto_emails=mailto_set,
        socials=socials,
        js_used=js_used,
        fb_used=fb_used,
    )
