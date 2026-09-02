"""
Shared helpers used by both check_whatsapp.py and send_whatsapp.py:
loading leads, building the pitch, normalising numbers, and CSV logs.
"""
import csv
import math
from datetime import datetime

import config

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    raise SystemExit("Missing dependency. Run:  pip install -r requirements.txt")


# --------------------------------------------------------------------------- #
# small utils
# --------------------------------------------------------------------------- #
def clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def segment_of(why_kept: str, rating) -> str:
    wk = why_kept.lower()
    if "no website" in wk or "social page only" in wk or "social" in wk:
        return "No website"
    if "low rating" in wk:
        return "Low rating"
    try:
        if rating and float(rating) < 4.2:
            return "Low rating"
    except (TypeError, ValueError):
        pass
    return "No website"


def reason_for(seg: str, rating) -> str:
    if seg == "No website":
        return config.REASON_NO_WEBSITE
    if seg == "Low rating":
        extra = f" ({rating}★)" if clean(rating) else ""
        return config.REASON_LOW_RATING + extra
    return config.REASON_DEFAULT


def normalise_number(whatsapp: str, phone: str) -> str:
    """Digits + country code, or '' if it can't be trusted."""
    has_wa_link = "wa.me" in (whatsapp or "").lower()

    if has_wa_link:
        d = "".join(ch for ch in whatsapp if ch.isdigit())
        return d if 11 <= len(d) <= 15 else ""

    # No wa.me link in the WhatsApp column.
    if config.WHATSAPP_COLUMN_ONLY:
        # only accept a bare number that was actually in the WhatsApp column
        src = whatsapp or ""
        if not any(ch.isdigit() for ch in src):
            return ""
    else:
        src = whatsapp or phone or ""

    digits = "".join(ch for ch in src if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10:
        return config.DEFAULT_COUNTRY_CODE + digits
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    if config.STRICT_US_NUMBERS:
        return ""
    return digits if 8 <= len(digits) <= 15 else ""


def build_message(lead: dict) -> str:
    msg = config.PITCH_TEMPLATE
    msg = msg.replace("{name}", lead["name"] or "there")
    msg = msg.replace("{category}", (lead["category"] or "business").lower())
    msg = msg.replace("{city}", lead["city"])
    msg = msg.replace("{state}", lead["state"])
    msg = msg.replace("{reason}", reason_for(lead["segment"], lead["rating"]))
    return " ".join(msg.split())


# --------------------------------------------------------------------------- #
# leads
# --------------------------------------------------------------------------- #
def load_leads(segment_filter=None, apply_send_filters=True):
    """
    Return de-duped leads that have a usable number.
    Each lead: name, category, rating, reviews, city, state, segment, number, message.
    """
    df = pd.read_excel(config.LEADS_XLSX)
    out = []
    for _, r in df.iterrows():
        why = clean(r.get(config.COL_WHYKEPT))
        rating = clean(r.get(config.COL_RATING))
        seg = segment_of(why, rating)
        number = normalise_number(
            clean(r.get(config.COL_WHATSAPP)), clean(r.get(config.COL_PHONE))
        )
        name = clean(r.get(config.COL_NAME))
        if not name or not number:
            continue

        wanted = segment_filter or config.SEGMENTS_TO_SEND
        if seg not in wanted:
            continue

        lead = {
            "name": name,
            "category": clean(r.get(config.COL_CATEGORY)),
            "rating": rating,
            "reviews": int(float(clean(r.get(config.COL_REVIEWS)) or 0)),
            "city": clean(r.get(config.COL_CITY)),
            "state": clean(r.get(config.COL_STATE)),
            "segment": seg,
            "number": number,
        }

        if apply_send_filters:
            if lead["reviews"] < config.MIN_REVIEWS:
                continue
            if config.SKIP_RATING_ABOVE and rating:
                try:
                    if float(rating) > config.SKIP_RATING_ABOVE:
                        continue
                except ValueError:
                    pass

        lead["message"] = build_message(lead)
        out.append(lead)

    seen, uniq = set(), []
    for l in out:
        if l["number"] in seen:
            continue
        seen.add(l["number"])
        uniq.append(l)
    return uniq


# --------------------------------------------------------------------------- #
# CSV logs
# --------------------------------------------------------------------------- #
def read_numbers(path) -> set:
    """Set of the 'number' column of a CSV, or empty set."""
    nums = set()
    if path and path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("number"):
                    nums.add(row["number"].strip())
    return nums


def append_row(path, header, values):
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(values)


def log_contact(path, lead, status):
    append_row(
        path,
        ["timestamp", "number", "name", "segment", "status", "message"],
        [datetime.now().isoformat(timespec="seconds"), lead["number"], lead["name"],
         lead["segment"], status, lead.get("message", "")],
    )


def log_check(path, lead, status):
    append_row(
        path,
        ["timestamp", "number", "name", "segment", "status"],
        [datetime.now().isoformat(timespec="seconds"), lead["number"], lead["name"],
         lead["segment"], status],
    )
