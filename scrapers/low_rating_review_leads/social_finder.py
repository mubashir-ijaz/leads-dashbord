"""Best-effort name-based social-profile lookup.

For a business with no website there's nothing to crawl, so we fall back to a
plain web search ("<name>" <city> <state>) and pick the first Facebook /
Instagram / LinkedIn URL out of the results.

Primary engine: DuckDuckGo Lite (https://lite.duckduckgo.com/lite/) — a tiny
no-JS results page that tolerates light scraping. Bing is tried as a fallback.

This is a heuristic: it misses sometimes and, for generic business names, can
grab the wrong page — treat results as leads to eyeball, not confirmed accounts.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import httpx

log = logging.getLogger(__name__)

DDG_LITE = "https://lite.duckduckgo.com/lite/"
BING = "https://www.bing.com/search"

HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
}

_PLATFORM_RE = {
    "Facebook":  re.compile(
        r"https?://(?:[\w-]+\.)?facebook\.com/[^\s\"'<>\\)]+", re.I),
    "Instagram": re.compile(
        r"https?://(?:[\w-]+\.)?instagram\.com/[^\s\"'<>\\)]+", re.I),
    "LinkedIn":  re.compile(
        r"https?://(?:[\w-]+\.)?linkedin\.com/(?:company|in|pub|school)/[^\s\"'<>\\)]+",
        re.I),
}

# URL fragments that mean "not an actual business profile".
_JUNK = (
    "facebook.com/tr", "/sharer", "/plugins/", "l.facebook.com", "/login",
    "/help/", "/policies", "/legal", "/pages/create", "facebook.com/business",
    "/dialog/", "/l.php", "/recover", "/watch",
    "instagram.com/p/", "instagram.com/reel/", "instagram.com/explore/",
    "instagram.com/accounts/", "instagram.com/about", "instagram.com/directory",
    "linkedin.com/sharearticle", "linkedin.com/feed", "linkedin.com/jobs",
    "/uas/login", "duckduckgo.com", "bing.com", "microsoft.com", "msn.com",
)


def _clean(url: str) -> str:
    url = unescape(url).split("#", 1)[0]
    url = url.split("&", 1)[0].split("?", 1)[0]
    return url.rstrip("/.,;)")


def _canonical(platform: str, url: str) -> str:
    """Trim a result URL down to the profile/page itself (drop deep subpages)
    and normalise the host to www.<platform>.com."""
    p = urlparse(url)
    segs = [s for s in p.path.split("/") if s]
    if not segs:
        return ""
    if platform == "LinkedIn":
        if len(segs) >= 2 and segs[0].lower() in ("company", "in", "pub", "school"):
            keep = segs[:2]
        else:
            return ""
        host = "www.linkedin.com"
    else:  # Facebook / Instagram
        host = f"www.{platform.lower()}.com"
        first = segs[0].lower()
        if first in ("pages", "people") and len(segs) >= 3:
            keep = segs[:3]
        elif first == "profile.php":
            keep = segs[:1]
        else:
            keep = segs[:1]
    return f"https://{host}/" + "/".join(keep)


def _unwrap(href: str) -> str:
    """DDG/Bing sometimes wrap the real URL in a redirect."""
    if href.startswith("//"):
        href = "https:" + href
    p = urlparse(href)
    q = parse_qs(p.query)
    if "duckduckgo.com" in p.netloc and "uddg" in q:
        return unquote(q["uddg"][0])
    if p.netloc.endswith("bing.com") and p.path.startswith("/ck/") and "u" in q:
        val = q["u"][0]
        # Bing base64-ish "a1<base64>" form — best effort
        return unquote(val)
    return href


def _scan(text: str) -> dict:
    out = {"Facebook": "", "Instagram": "", "LinkedIn": ""}
    text = unescape(text)
    for platform, rx in _PLATFORM_RE.items():
        for m in rx.finditer(text):
            url = _clean(_unwrap(m.group(0)))
            low = url.lower()
            if any(j in low for j in _JUNK):
                continue
            tail = low.split(".com/", 1)[-1]
            if not tail or tail in ("home", "explore", "help", "about",
                                    "dir", "directory", "web", "www"):
                continue
            canon = _canonical(platform, url)
            if canon:
                out[platform] = canon
                break
    return out


def _query(name: str, city: str, state: str) -> str:
    bits = [f'"{name.strip()}"']
    if city:
        bits.append(city.strip())
    if state:
        bits.append(state.strip())
    bits.append("facebook instagram linkedin")
    return " ".join(bits)


def find_socials(name: str, city: str = "", state: str = "",
                 client: httpx.Client | None = None, timeout: float = 20.0) -> dict:
    """Return {"Facebook": url|"", "Instagram": url|"", "LinkedIn": url|""}."""
    out = {"Facebook": "", "Instagram": "", "LinkedIn": ""}
    if not name or not name.strip():
        return out

    own = client or httpx.Client(headers=HEADERS, timeout=timeout,
                                 follow_redirects=True)
    q = _query(name, city, state)
    try:
        # 1) DuckDuckGo Lite (POST form)
        try:
            r = own.post(DDG_LITE, data={"q": q}, headers=HEADERS)
            if r.status_code < 400:
                out = _scan(r.text)
        except httpx.HTTPError as exc:
            log.debug("ddglite failed for %r: %s", name, exc)

        # 2) Bing fallback for anything still missing
        if not all(out.values()):
            try:
                r = own.get(BING, params={"q": q}, headers=HEADERS)
                if r.status_code < 400:
                    for k, v in _scan(r.text).items():
                        if v and not out[k]:
                            out[k] = v
            except httpx.HTTPError as exc:
                log.debug("bing failed for %r: %s", name, exc)

        return out
    finally:
        if client is None:
            own.close()


if __name__ == "__main__":  # e.g.  python social_finder.py "Beachside Resort Hotel" "Gulf Shores" "Alabama"
    import sys
    logging.basicConfig(level=logging.INFO)
    a = sys.argv[1:] + ["", "", ""]
    print(find_socials(a[0], a[1], a[2]))
