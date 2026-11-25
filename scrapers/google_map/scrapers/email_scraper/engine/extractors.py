"""All page-content extractors plus email scoring.

Email extraction sources, in priority order during scoring:
    mailto: links  >  JSON-LD  >  Cloudflare-encoded  >  raw-text regex
"""

from __future__ import annotations

import html
import json
import re
from typing import Iterable, Optional
from urllib.parse import unquote

import parsel
import tldextract

from .config import (
    BUSINESS_PREFIXES,
    FREEMAIL_ROOTS,
    GENERIC_FRAGMENTS,
    SOCIAL_BASES,
    SUFFIX_LIST,
)


# ----------------------------- Patterns -------------------------------------

EMAIL_PATTERNS = [
    re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}'),
    re.compile(
        r'[A-Za-z0-9._%+\-]+\s*[\[\(]\s*at\s*[\]\)]\s*'
        r'[A-Za-z0-9.\-]+\s*[\[\(]\s*dot\s*[\]\)]\s*[A-Za-z]{2,24}',
        re.IGNORECASE,
    ),
    re.compile(
        r'[A-Za-z0-9._%+\-]+\s+at\s+[A-Za-z0-9.\-]+\s+dot\s+[A-Za-z]{2,24}',
        re.IGNORECASE,
    ),
]

# Backstop: never scan more than this many characters of a page's text with the
# regexes (a light guard against pathologically large pages).
MAX_SCAN_CHARS = 2_000_000

ASSET_TLD_RE = re.compile(
    r'\.(png|jpg|jpeg|gif|svg|webp|ico|css|js|woff2?|ttf)$', re.I,
)


# ----------------------------- Email helpers --------------------------------

def normalize_email(raw: str) -> str:
    e = raw.strip().lower()
    e = re.sub(r'\s*\[\s*at\s*\]\s*', '@', e, flags=re.I)
    e = re.sub(r'\s*\(\s*at\s*\)\s*', '@', e, flags=re.I)
    e = re.sub(r'\s+at\s+', '@', e, flags=re.I)
    e = re.sub(r'\s*\[\s*dot\s*\]\s*', '.', e, flags=re.I)
    e = re.sub(r'\s*\(\s*dot\s*\)\s*', '.', e, flags=re.I)
    e = re.sub(r'\s+dot\s+', '.', e, flags=re.I)
    return re.sub(r'\s+', '', e)


def is_generic(email: str) -> bool:
    """Match the generic-email rules with category-aware semantics.

    Why: a flat substring check incorrectly drops legitimate ccTLDs — e.g.
    `@email.com` would falsely filter `info@email.com.au`. So:
      - `@<domain>` (no trailing dot)  -> exact match on post-@ portion
      - `@<prefix>.` (trailing dot)    -> prefix match on post-@ portion
      - `<word>@`                      -> match if local-part == word
      - `<bare>` (no @)                -> general substring
    """
    e = email.lower()
    local, _, domain_part = e.partition('@')
    if not domain_part:
        return False
    post_at = '@' + domain_part

    for frag in GENERIC_FRAGMENTS:
        f = frag.lower()
        if f.startswith('@') and f.endswith('.'):
            if post_at.startswith(f):
                return True
        elif f.startswith('@'):
            if post_at == f:
                return True
        elif f.endswith('@'):
            if local + '@' == f:
                return True
        else:
            if f in e:
                return True
    return False


def has_valid_suffix(email: str) -> bool:
    return tldextract.extract(email).suffix in SUFFIX_LIST


def looks_like_asset(email: str) -> bool:
    return bool(ASSET_TLD_RE.search(email))


def valid_email(email: str) -> bool:
    if email.count('@') != 1:
        return False
    if looks_like_asset(email):
        return False
    if is_generic(email):
        return False
    return has_valid_suffix(email)


# ----------------------------- Extractors -----------------------------------

def extract_emails_text(text: str) -> set[str]:
    found: set[str] = set()
    decoded = html.unescape(text[:MAX_SCAN_CHARS])
    for pat in EMAIL_PATTERNS:
        for m in pat.findall(decoded):
            e = normalize_email(m)
            if valid_email(e):
                found.add(e)
    return found


def extract_emails_mailto(selector: parsel.Selector) -> set[str]:
    found: set[str] = set()
    for href in selector.xpath('//a[starts-with(@href, "mailto:")]/@href').getall():
        addr = unquote(href[7:]).split('?', 1)[0]
        e = normalize_email(addr)
        if valid_email(e):
            found.add(e)
    return found


def _walk_jsonld(data, key: str) -> Iterable:
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and k.lower() == key:
                if isinstance(v, list):
                    yield from v
                else:
                    yield v
            else:
                yield from _walk_jsonld(v, key)
    elif isinstance(data, list):
        for item in data:
            yield from _walk_jsonld(item, key)


def extract_jsonld(selector: parsel.Selector) -> set[str]:
    emails: set[str] = set()
    for blob in selector.xpath(
        '//script[@type="application/ld+json"]/text()'
    ).getall():
        text = blob.strip()
        try:
            data = json.loads(text)
        except Exception:
            try:
                data = json.loads(text.rstrip(','))
            except Exception:
                continue
        for v in _walk_jsonld(data, 'email'):
            e = normalize_email(str(v).removeprefix('mailto:'))
            if valid_email(e):
                emails.add(e)
    return emails


def decode_cf_emails(selector: parsel.Selector) -> set[str]:
    found: set[str] = set()
    for enc in selector.xpath('//*[@data-cfemail]/@data-cfemail').getall():
        try:
            r = int(enc[:2], 16)
            decoded = ''.join(
                chr(int(enc[i:i + 2], 16) ^ r) for i in range(2, len(enc), 2)
            )
            e = normalize_email(decoded)
            if valid_email(e):
                found.add(e)
        except Exception:
            continue
    return found


def extract_socials(text: str) -> dict[str, str]:
    text = text[:MAX_SCAN_CHARS]
    result = {p: '' for p in SOCIAL_BASES}
    for platform, _base in SOCIAL_BASES.items():
        pat = re.compile(
            r'(?:https?://)?(?:www\.)?'
            + re.escape(platform.lower())
            + r'\.com/[^\s",<>\'\\]+',
            re.I,
        )
        for link in pat.findall(text):
            clean = link.replace('www.', '')
            if not clean.startswith('http'):
                clean = 'https://' + clean
            if len(clean) > 200:
                continue
            clean = clean.split('?', 1)[0].rstrip('/.,);')
            low = clean.lower()
            if platform == 'Facebook' and any(
                s in low for s in ('/watch/', '/search/', 'facebook.com/tr', '/sharer', '/plugins/')
            ):
                continue
            if platform == 'Twitter' and any(
                s in low for s in ('/home', '/intent/', '/share', '/hashtag/')
            ):
                continue
            if platform == 'LinkedIn' and not any(
                s in low for s in ('/in/', '/company/', '/school/', '/pub/')
            ):
                continue
            if platform == 'YouTube' and not any(
                s in low for s in ('/channel/', '/user/', '/@', '/c/')
            ):
                continue
            if platform == 'TikTok' and ('/tag/' in low or '/discover/' in low):
                continue
            if platform == 'Instagram' and any(
                s in low for s in ('/p/', '/reel/', '/explore/')
            ):
                continue
            result[platform] = clean
            break
    return result


# ----------------------------- Scoring --------------------------------------

def score_email(email: str, site_domain: str, mailto_set: set[str]) -> int:
    local, _, dom = email.partition('@')
    site_root = tldextract.extract(site_domain).domain.lower()
    email_root = tldextract.extract(dom).domain.lower()

    score = 0
    if email_root == site_root:
        score += 100
    if local.lower() in BUSINESS_PREFIXES:
        score += 30
    if re.match(r'^[a-z]+\.[a-z]+$', local.lower()):
        score += 15
    if email in mailto_set:
        score += 25
    if email_root in FREEMAIL_ROOTS and email_root != site_root:
        score -= 10
    return score


def best_email(
    emails: set[str], site_domain: str, mailto_set: set[str]
) -> Optional[str]:
    if not emails:
        return None
    return max(emails, key=lambda e: (score_email(e, site_domain, mailto_set), e))
