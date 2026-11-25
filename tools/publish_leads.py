"""
Publish a scraper's output file (xlsx/csv) into the dashboard's dataset and
push it to git.

Used by ../run.py right after a scraper finishes. Can also be run by hand:

    python tools/publish_leads.py PATH\\to\\leads.xlsx "Batch name"

What it does:
  1. Reads the sheet (works with either the Google Maps business-details
     columns or the Low-Rating leads columns — see COLUMN_ALIASES below).
  2. Converts each row into the dashboard's lead shape (same shape the
     in-browser "Import Excel/CSV" button produces) and files every row
     under the given batch name, exactly like a manual import would.
  3. Merges those leads into data_leads.js (window.DEFAULT_LEADS) — existing
     leads are updated in place (matched by name + address/city/phone),
     everything else is appended.
  4. Copies the source file into leads_archive/ for a durable record.
  5. Commits and pushes to git so the live dashboard (once redeployed by
     Vercel's git integration) shows the new batch for everyone, not just
     the browser that ran the import.
"""

from __future__ import annotations

import csv
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # leand compain/
DATA_JS = ROOT / "data_leads.js"
ARCHIVE_DIR = ROOT / "leads_archive"

# Each dashboard field <- first matching column name found in the source file.
COLUMN_ALIASES = {
    "name": ["Name"],
    "category": ["Category"],
    "rating": ["Rating", "Average Rating"],
    "reviews": ["Reviews", "Total Reviews"],
    "hasWebsite": ["Has Website"],
    "website": ["Website"],
    "phone": ["Phone"],
    "whatsapp": ["WhatsApp"],
    "email": ["Email", "Emails"],
    "facebook": ["Facebook"],
    "instagram": ["Instagram"],
    "linkedin": ["LinkedIn"],
    "twitter": ["Twitter", "X"],
    "youtube": ["YouTube"],
    "tiktok": ["TikTok"],
    "address": ["Address"],
    "city": ["City"],
    "state": ["State"],
    "maps": ["Maps URL", "URL", "Source URL"],
    "whyKept": ["Why kept"],
    "scraped": ["Scraped Date"],
}


# ---------------------------------------------------------------------------
# Reading xlsx / csv
# ---------------------------------------------------------------------------

def read_table(path: Path) -> tuple[list[str], list[dict]]:
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
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


def _find_col(headers: list[str], candidates: list[str]) -> str | None:
    norm = {h.strip().lower(): h for h in headers}
    for c in candidates:
        if c.lower() in norm:
            return norm[c.lower()]
    return None


def _to_num(v):
    if v in (None, ""):
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(v)))
    except ValueError:
        return None


def _to_int(v) -> int:
    n = _to_num(v)
    return int(round(n)) if n is not None else 0


def _first_email(value) -> str:
    for piece in re.split(r"[;,]", str(value or "")):
        piece = piece.strip()
        if "@" in piece:
            return piece
    return ""


# ---------------------------------------------------------------------------
# Row -> dashboard lead
# ---------------------------------------------------------------------------

def rows_to_leads(headers: list[str], rows: list[dict], batch_name: str) -> list[dict]:
    col = {key: _find_col(headers, cands) for key, cands in COLUMN_ALIASES.items()}
    leads = []
    for r in rows:
        def g(key):
            c = col.get(key)
            return r.get(c, "") if c else ""

        name = str(g("name") or "").strip()
        if not name:
            continue
        rating = _to_num(g("rating"))
        email = g("email")
        leads.append({
            "name": name,
            "subtype": str(g("category") or "").strip(),
            "category": batch_name,
            "_userCat": True,
            "rating": rating,
            "reviews": _to_int(g("reviews")),
            "hasWebsite": str(g("hasWebsite") or "").strip(),
            "website": str(g("website") or "").strip(),
            "phone": str(g("phone") or "").strip(),
            "whatsapp": str(g("whatsapp") or "").strip(),
            "email": _first_email(email) if col.get("email") else "",
            "facebook": str(g("facebook") or "").strip(),
            "instagram": str(g("instagram") or "").strip(),
            "linkedin": str(g("linkedin") or "").strip(),
            "twitter": str(g("twitter") or "").strip(),
            "youtube": str(g("youtube") or "").strip(),
            "tiktok": str(g("tiktok") or "").strip(),
            "address": str(g("address") or "").strip(),
            "city": str(g("city") or "").strip(),
            "state": str(g("state") or "").strip().upper()[:3],
            "maps": str(g("maps") or "").strip(),
            "whyKept": str(g("whyKept") or "").strip(),
            "segment": _segment_of(str(g("whyKept") or ""), rating),
            "scraped": str(g("scraped") or datetime.datetime.now().strftime(
                "%d-%m-%Y %I:%M:%S %p")),
        })
    return leads


def _segment_of(why_kept: str, rating: float | None) -> str:
    wk = why_kept.lower()
    if "no website" in wk or "social" in wk:
        return "No website"
    if "low rating" in wk:
        return "Low rating"
    if rating is not None and 0 < rating < 4.2:
        return "Low rating"
    return "No website"


def _lead_id(l: dict) -> str:
    name = re.sub(r"\s+", " ", str(l.get("name") or "").lower().strip())
    tail = str(l.get("address") or l.get("city") or l.get("phone") or "").lower()
    tail = re.sub(r"\s+", " ", tail.strip())
    return f"{name}|{tail}"


# ---------------------------------------------------------------------------
# data_leads.js read / write
# ---------------------------------------------------------------------------

_JS_PREFIX_RE = re.compile(r"^\s*window\.DEFAULT_LEADS\s*=\s*")


def load_default_leads() -> dict:
    if not DATA_JS.exists():
        return {"generatedFrom": "", "count": 0, "leads": []}
    text = DATA_JS.read_text(encoding="utf-8")
    for line in text.splitlines():
        if _JS_PREFIX_RE.match(line):
            payload = _JS_PREFIX_RE.sub("", line).strip().rstrip(";").strip()
            return json.loads(payload)
    return {"generatedFrom": "", "count": 0, "leads": []}


def save_default_leads(data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    DATA_JS.write_text(
        "/* Leads dataset, generated by tools/publish_leads.py. "
        "Do not edit by hand. */\n"
        f"window.DEFAULT_LEADS = {payload};\n",
        encoding="utf-8",
    )


def merge_leads(base: list[dict], incoming: list[dict]) -> list[dict]:
    by_id = {_lead_id(l): l for l in base}
    for lead in incoming:
        lid = _lead_id(lead)
        cur = by_id.get(lid)
        if cur is None:
            by_id[lid] = lead
            base.append(lead)
            continue
        cur["category"] = lead["category"]
        cur["_userCat"] = True
        for k, v in lead.items():
            if k in ("category", "_userCat"):
                continue
            if not cur.get(k) and v:
                cur[k] = v
    return base


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), text=True,
                          capture_output=True)


def commit_and_push(paths: list[Path], message: str) -> None:
    rel = [str(p.relative_to(ROOT)) for p in paths]
    add = git("add", *rel)
    if add.returncode != 0:
        print(f"  git add failed: {add.stderr.strip()}")
        return
    status = git("status", "--porcelain", *rel)
    if not status.stdout.strip():
        print("  Nothing changed — skipping commit.")
        return
    commit = git("commit", "-m", message)
    if commit.returncode != 0:
        print(f"  git commit failed: {commit.stderr.strip()}")
        return
    print(f"  Committed: {message}")
    push = git("push")
    if push.returncode != 0:
        print(f"  git push failed (commit is saved locally):\n{push.stderr.strip()}")
    else:
        print("  Pushed to origin.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def publish(source: Path, batch_name: str, mode: str = "merge") -> None:
    """mode: 'merge' updates matching leads and appends new ones (default);
    'replace' drops every existing lead under this batch name first, so a
    re-scrape fully replaces the old data (no stale/closed businesses left
    behind)."""
    source = Path(source)
    print(f"\nPublishing {source.name} as \"{batch_name}\" ({mode})...")

    headers, rows = read_table(source)
    if not rows:
        print("  No rows found in the file — nothing to publish.")
        return

    leads = rows_to_leads(headers, rows, batch_name)
    print(f"  {len(leads)} lead(s) converted.")

    data = load_default_leads()
    base = data.get("leads") or []
    if mode == "replace":
        removed = sum(1 for l in base if l.get("category") == batch_name)
        base = [l for l in base if l.get("category") != batch_name]
        if removed:
            print(f"  Removed {removed} existing lead(s) previously under \"{batch_name}\".")
        base.extend(leads)
        data["leads"] = base
    else:
        data["leads"] = merge_leads(base, leads)
    data["count"] = len(data["leads"])

    meta = data.setdefault("categoryMeta", {})
    meta[batch_name] = {
        "pushedAt": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds").replace("+00:00", "Z")
    }
    save_default_leads(data)
    print(f"  data_leads.js updated ({data['count']} total leads).")

    ARCHIVE_DIR.mkdir(exist_ok=True)
    dest = ARCHIVE_DIR / source.name
    if dest.resolve() != source.resolve():
        shutil.copy2(source, dest)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_and_push(
        [DATA_JS, dest],
        f"{'Replace' if mode == 'replace' else 'Add'} lead batch "
        f"\"{batch_name}\" ({len(leads)} leads) — {stamp}",
    )


def remove_category(batch_name: str) -> int:
    """Delete every lead filed under `batch_name` (and its categoryMeta entry).
    Returns how many leads were removed. Commits + pushes the change."""
    data = load_default_leads()
    base = data.get("leads") or []
    kept = [l for l in base if l.get("category") != batch_name]
    removed = len(base) - len(kept)
    data["leads"] = kept
    data["count"] = len(kept)
    data.get("categoryMeta", {}).pop(batch_name, None)
    save_default_leads(data)
    print(f"Removed {removed} lead(s) under \"{batch_name}\" ({data['count']} total remain).")

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_and_push([DATA_JS], f"Remove lead batch \"{batch_name}\" — {stamp}")
    return removed


def set_category_pitch(batch_name: str, pitch: str) -> None:
    """Attach a suggested pitch template to a category. A browser seeds its
    local per-category pitch from this the first time it sees the category,
    but never overwrites a pitch already customised there. Commits + pushes."""
    data = load_default_leads()
    meta = data.setdefault("categoryMeta", {})
    meta.setdefault(batch_name, {})["pitch"] = pitch
    save_default_leads(data)
    print(f"Set suggested pitch for \"{batch_name}\".")

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_and_push([DATA_JS], f"Set pitch for \"{batch_name}\" — {stamp}")


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: publish_leads.py PATH_TO_FILE \"Batch name\" [merge|replace]")
    mode = sys.argv[3] if len(sys.argv) > 3 else "merge"
    publish(Path(sys.argv[1]), sys.argv[2], mode)


if __name__ == "__main__":
    main()
