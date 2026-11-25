"""Turn a business-details sheet into a filtered leads sheet.

Keeps a business when it has NO website OR its rating <= MAX_RATING, then:
  * builds a wa.me WhatsApp link from its phone number,
  * carries over any email / social handles the website crawl already found,
  * derives City / State from Google's own address fields,
  * marks WHY the row was kept and whether it still needs a social lookup.

The name-based social lookup itself lives in social_finder.py and is driven by
run_leads.py (so it can be rate-limited and logged); this module just prepares
the rows and writes the file.
"""

from __future__ import annotations

import csv
import datetime
import logging
import re
from pathlib import Path

import tldextract
from openpyxl import Workbook, load_workbook

log = logging.getLogger(__name__)

# Final column order in the leads sheet.
LEAD_COLUMNS = [
    "Name", "Category", "Rating", "Reviews",
    "Has Website", "Website Type", "Website",
    "Phone", "WhatsApp", "Email",
    "Facebook", "Instagram", "LinkedIn", "LinkedIn (owner) - enrich",
    "Address", "City", "State",
    "Maps URL",
    "Why kept", "Social lookup", "Scraped Date",
]


def _domain(url: str) -> str:
    ext = tldextract.extract(str(url or ""))
    return f"{ext.domain}.{ext.suffix}".lower() if ext.suffix else ""


def _host_in(dom: str, domains) -> bool:
    for d in domains:
        d = str(d).lower().strip()
        if d and (dom == d or dom.endswith("." + d)):
            return True
    return False


def classify_website(url: str, social_domains, chain_domains) -> str:
    """none | social-only | chain/booking | own"""
    if not str(url or "").strip():
        return "none"
    dom = _domain(url)
    if not dom:
        return "none"
    if _host_in(dom, social_domains):
        return "social-only"
    if _host_in(dom, chain_domains):
        return "chain/booking"
    return "own"


# ---------------------------------------------------------------------------
# Reading the business-details file (xlsx or csv)
# ---------------------------------------------------------------------------

def read_table(path: Path) -> tuple[list[str], list[dict]]:
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        try:
            first = next(it)
        except StopIteration:
            wb.close()
            return [], []
        headers = ["" if h is None else str(h) for h in first]
        rows = [
            {h: ("" if i >= len(r) or r[i] is None else r[i])
             for i, h in enumerate(headers)}
            for r in it
        ]
        wb.close()
        return headers, rows

    with open(path, encoding="utf-8-sig", newline="") as f:
        data = list(csv.reader(f))
    if not data:
        return [], []
    headers = list(data[0])
    rows = [{h: (raw[i] if i < len(raw) else "") for i, h in enumerate(headers)}
            for raw in data[1:]]
    return headers, rows


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _to_float(value) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def whatsapp_link(phone_e164: str, phone_local: str, country_code: str) -> str:
    """wa.me wants a full international number, digits only, no '+'."""
    num = _digits(phone_e164)
    if not num:
        d = _digits(phone_local)
        if not d:
            return ""
        if country_code.upper() == "US" and len(d) == 10:
            num = "1" + d
        elif len(d) >= 10:
            num = d
        else:
            return ""
    # E.164 numbers are 8-15 digits; anything outside that is a bad source parse.
    if not (8 <= len(num) <= 15):
        return ""
    # US numbers must be 10 digits, or 11 with the leading country code.
    if country_code.upper() == "US":
        if len(num) == 10:
            num = "1" + num
        elif len(num) != 11:
            return ""
    return f"https://wa.me/{num}"


def parse_state(region: str, fallback_city: str = "") -> str:
    """Google's Region label looks like 'Akron, OH, United States'."""
    parts = [p.strip() for p in str(region or "").split(",") if p.strip()]
    if not parts:
        return ""
    tail = parts[-1].lower()
    if tail in ("united states", "usa", "us") and len(parts) >= 2:
        return parts[-2]
    return parts[-1] if len(parts) > 1 else ""


def _first_email(value: str) -> str:
    """The 'Emails' column may hold several, separated by ; or ,."""
    for piece in re.split(r"[;,]", str(value or "")):
        piece = piece.strip()
        if "@" in piece:
            return piece
    return ""


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

def build_leads(details_path: Path, cfg) -> list[dict]:
    headers, rows = read_table(details_path)
    if not rows:
        log.warning("No rows found in %s", details_path)
        return []

    chain_domains = getattr(cfg, "CHAIN_OR_AGGREGATOR_DOMAINS", [])
    social_domains = getattr(cfg, "SOCIAL_ONLY_DOMAINS", [])
    social_as_none = getattr(cfg, "SOCIAL_AS_NO_WEBSITE", True)
    drop_chain_rows = getattr(cfg, "DROP_CHAIN_SITE_ROWS", False)

    leads: list[dict] = []
    for r in rows:
        website = str(r.get("Website") or "").strip()
        rating = _to_float(r.get("Average Rating"))
        reviews = r.get("Total Reviews", "")
        country = str(r.get("Country Code") or "").strip()

        if cfg.REQUIRE_US and country and country.upper() != "US":
            continue

        site_type = classify_website(website, social_domains, chain_domains)
        if site_type == "chain/booking" and drop_chain_rows:
            continue
        # A no-website lead = truly blank, or (by default) only a social page.
        no_site = site_type == "none" or (social_as_none
                                          and site_type == "social-only")

        low_rating = rating is not None and rating <= cfg.MAX_RATING
        no_rating = rating is None

        reasons: list[str] = []
        keep = False
        if cfg.KEEP_IF_NO_WEBSITE and no_site:
            keep = True
            reasons.append("social page only" if site_type == "social-only"
                           else "no website")
        if cfg.KEEP_IF_LOW_RATING and low_rating:
            keep = True
            reasons.append(f"low rating ({rating:g})")
        if no_rating and no_site:
            keep = True
            reasons.append("no rating yet")
        elif no_rating and not no_site and not cfg.KEEP_NO_RATING_ONLY_IF_NO_WEBSITE:
            # only reachable if someone flips that flag off
            keep = True
            reasons.append("no rating yet")

        if not keep:
            continue

        phone = str(r.get("Phone") or "").strip()
        phone_e164 = str(r.get("Phone (E.164)") or "").strip()
        city = str(r.get("City") or "").strip()
        state = parse_state(r.get("Region"), city)

        facebook = str(r.get("Facebook") or "").strip()
        instagram = str(r.get("Instagram") or "").strip()
        linkedin = str(r.get("LinkedIn") or "").strip()

        # A business whose "website" is really just its Facebook/Instagram page:
        # lift it into the right social column, and blank the Website column.
        show_website = website
        if site_type == "social-only":
            wdom = _domain(website)
            if wdom in ("facebook.com", "m.facebook.com") and not facebook:
                facebook = website
            elif wdom == "instagram.com" and not instagram:
                instagram = website
            if wdom in ("facebook.com", "m.facebook.com", "instagram.com"):
                show_website = ""

        needs_lookup = not (facebook or instagram or linkedin)

        has_website = {
            "none": "No",
            "social-only": "Social only",
            "chain/booking": "Chain",
            "own": "Yes",
        }[site_type]

        leads.append({
            "Name": str(r.get("Name") or "").strip(),
            "Category": str(r.get("Category") or "").strip(),
            "Rating": rating if rating is not None else "",
            "Reviews": reviews if reviews != "" else 0,
            "Has Website": has_website,
            "Website Type": site_type,
            "Website": show_website,
            "Phone": phone,
            "WhatsApp": whatsapp_link(phone_e164, phone, country or "US"),
            "Email": _first_email(r.get("Emails")),
            "Facebook": facebook,
            "Instagram": instagram,
            "LinkedIn": linkedin,
            "LinkedIn (owner) - enrich": "",   # fill via Apollo/Hunter/etc.
            "Address": str(r.get("Address") or "").strip(),
            "City": city,
            "State": state,
            "Maps URL": str(r.get("URL") or r.get("Source URL") or "").strip(),
            "Why kept": "; ".join(reasons),
            "Social lookup": "pending" if needs_lookup else "from website",
            "Scraped Date": str(r.get("Scraped Date")
                                or datetime.datetime.now().strftime(
                                    "%d-%m-%Y %I:%M:%S %p")),
        })

    # No-website leads first (strongest fit), then chain, then own site;
    # within each, worst-rated first, then most-reviewed.
    rank = {"No": 0, "Social only": 1, "Chain": 2, "Yes": 3}
    leads.sort(key=lambda l: (
        rank.get(l["Has Website"], 3),
        l["Rating"] if isinstance(l["Rating"], (int, float)) else 99,
        -(int(l["Reviews"]) if str(l["Reviews"]).isdigit() else 0),
    ))
    return leads


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_leads(leads: list[dict], out_path: Path) -> tuple[Path | None, Path | None]:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = out_path.with_suffix(".csv")
    xlsx_path = out_path.with_suffix(".xlsx")

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(LEAD_COLUMNS)
        for lead in leads:
            w.writerow([lead.get(c, "") for c in LEAD_COLUMNS])

    wb = Workbook()
    ws = wb.active
    ws.title = "leads"
    ws.append(LEAD_COLUMNS)
    for lead in leads:
        ws.append([lead.get(c, "") for c in LEAD_COLUMNS])
    try:
        wb.save(str(xlsx_path))
    except OSError as e:
        log.error("Could not write %s (open in Excel?): %s", xlsx_path, e)
        xlsx_path = None

    return csv_path, xlsx_path
