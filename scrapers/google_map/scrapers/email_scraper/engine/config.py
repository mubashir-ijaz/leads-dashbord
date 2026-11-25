"""Static configuration: paths, rules, headers, hint sets."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # scrapers/email_scraper
PROJECT_ROOT = ROOT.parent.parent                       # suite root
RULES_PATH = ROOT / 'rules.json'

# Inputs/outputs live in the suite's top-level folders (created on demand).
WEBSITES_PATH = PROJECT_ROOT / 'input' / 'email_scraper' / 'websites.txt'
OUTPUT_DIR = PROJECT_ROOT / 'output' / 'email_scraper'

with RULES_PATH.open(encoding='utf-8') as _f:
    _RULES = json.load(_f)['data']

SUFFIX_LIST: set[str] = set(_RULES['suffix'])
GENERIC_FRAGMENTS: list[str] = _RULES['generic_emails']
KEYWORDS: list[str] = _RULES['keywords']
BUSINESS_PREFIXES: set[str] = {p.lower() for p in _RULES['common_business_emails']}

DEFAULT_HEADERS = {
    'connection': 'keep-alive',
    'sec-fetch-mode': 'navigate',
    'accept-language': 'en-US,en;q=0.9',
    'accept-encoding': 'gzip, deflate, br',
    'user-agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    ),
    'accept': (
        'text/html,application/xhtml+xml,application/xml;q=0.9,'
        'image/avif,image/webp,*/*;q=0.8'
    ),
}

# Subpages we bother fetching, in PRIORITY ORDER (highest first). A link is a
# candidate only if its URL path contains one of these; the crawler ranks by
# this order so — when only a few subpages are fetched — it visits the pages
# most likely to list an email (contact/legal) before the rest. Substrings, so
# 'contact' also matches '/contact-us', '/contactus'; 'about' matches '/about-us'.
# Edit this list to change which pages are visited.
CONTACT_PATH_KEYWORDS: list[str] = [
    'contact', 'kontakt', 'contacto', 'contatti', 'contactez',  # contact (multi-lang)
    'impressum', 'imprint', 'legal-notice',                     # legal pages (often list email)
    'about', 'about-us', 'company', 'quienes-somos',            # about / company
    'team', 'meet-the-team', 'staff', 'people',                 # team / people
    'leadership', 'management', 'directory',                    # leadership
]

SOCIAL_BASES = {
    'Facebook': 'https://facebook.com',
    'Instagram': 'https://instagram.com',
    'Twitter': 'https://twitter.com',
    'LinkedIn': 'https://linkedin.com',
    'YouTube': 'https://youtube.com',
    'TikTok': 'https://tiktok.com',
}

FREEMAIL_ROOTS = {
    'gmail', 'yahoo', 'hotmail', 'outlook', 'aol', 'live', 'icloud', 'protonmail',
}

FIELDNAMES = [
    'Domain', 'Source URL', 'Emails', 'JS Rendered',
    'Facebook', 'Instagram', 'Twitter', 'LinkedIn', 'YouTube', 'TikTok',
]
