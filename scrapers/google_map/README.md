# Google Maps & Contacts Scraper

Three scrapers behind one command-line launcher:

1. **Link Collector** — runs `"<category> in <location>"` searches and collects
   the Google Maps place links.
2. **Business Details** — takes a file of place links and extracts full business
   details (name, phone, website, address, hours, rating, and more) for each.
   It can also crawl each business's website for **emails and social handles**.
3. **Emails & Social Handles** — crawls a list of websites and extracts emails
   and social media links.

You run **one file** — `run.py`. With no arguments it shows a short text menu:
pick what to scrape, answer a few questions (press Enter to accept each default),
and it runs right there in your terminal, streaming progress and logs as it goes.

---

## Quick start

```bash
pip install -r requirements.txt
# Only if you'll use the Link Collector's "playwright" mode:
playwright install chromium

python run.py
```

The menu offers these choices:

- **Link Collector** — collect place links from category × location searches.
- **Business Details** — extract details for a list of place links.
- **Both** — collect links first, then scrape business details from them.
- **Emails & Social Handles** — crawl a list of websites for emails / socials.

Pick one and answer the questions it asks (each shows its default in brackets —
press Enter to accept). Fill in your input files first (see each scraper's
section below); the run writes its output under `output/`.

The Link Collector's questions adapt to the collector you choose: **api** asks
the API options (search mode, parallel searches, proxy), while **playwright**
asks the browser options (headless, max results, delay). The proxy applies to
API mode only.

### Other ways to start it

```bash
python run.py links               # ask the questions, then run
python run.py links    --defaults # link collector, settings.py as-is (no questions)
python run.py business --defaults # business details
python run.py both     --defaults # links then business details
python run.py emails   --defaults # emails & social handles
```

---

## Folder layout

```
Google Maps Scraper/
├── run.py                      ← the only file you run
├── runner.py                   ← shared run engine
├── requirements.txt
├── input/
│   ├── link_collector/         ← categories.txt, locations.txt
│   ├── business_details/       ← links.txt
│   └── email_scraper/          ← websites.txt
├── output/
│   ├── link_collector/         ← collected links (CSV + xlsx)
│   ├── business_details/       ← business details (xlsx)
│   └── email_scraper/          ← emails & socials (CSV + xlsx)
└── scrapers/
    ├── link_collector/         ← code + settings.py
    ├── business_details/       ← code + settings.py
    └── email_scraper/          ← contact engine (rules.json + engine/)
```

Each scraper has its **own** `settings.py` (inside its folder under `scrapers/`).
The text menu asks the common options for you; edit those files for the advanced
settings (proxy URL, network tuning, search center/bounding box, field maps).

---

## 1. Link Collector

**Inputs** (`input/link_collector/`):

- `categories.txt` — one category per line (e.g. `coffee shops`).
- `locations.txt` — one location per line (e.g. `Brooklyn NY`).

Every category is paired with every location and searched as
`"<category> in <location>"`. Fill these in by editing the two files.

**Options:** collector (API vs Playwright), search mode, proxy, sponsored
results, how many searches to run (blank = all), output file name (blank = auto
timestamp), plus Playwright-only options (headless, max results, delay).

**Output** (`output/link_collector/`): one `.csv` and one `.xlsx` per run with
columns `Link, Category, Location`.

## 2. Business Details

**Input** — either:

- `input/business_details/links.txt` (one place URL per line, the default), or
- a **collected-links CSV** from `output/link_collector/` — the menu lists the
  CSVs the Link Collector has produced so you can scrape one directly.

(In **Both** mode the input is wired up automatically: the links collected in
step 1 are fed straight into the business scraper.)

**Options:**

- **Detail level** — `Basic` (core fields) or `Detailed` (adds description,
  services, photos, CID/ChIJ IDs, city/street/region, language, profile photo…).
- **Proxy** — route requests through the configured proxy or not.
- **Parallel workers** — how many links to scrape at once (blank = default 3;
  keep it low to avoid blocks).
- **Contact extraction** — optionally crawl each business's website for **emails**
  and **social handles** (both on by default). This adds `Emails` and social
  columns to the output, but makes the run slower. Untick both to skip it.

**Output** (`output/business_details/`): one timestamped `.xlsx` per run.

## 3. Emails & Social Handles

**Input** (`input/email_scraper/websites.txt`): one website per line (domain or
full URL).

**Options:**

- **Extract emails** / **Extract social handles** — what to collect (both on by
  default; at least one must be ticked).
- **Emails per website** — `Best match (1)` (the single best email) or
  `All found` (every email discovered).

It fetches each homepage, follows a few contact-ish subpages, and (when an email
is still missing) falls back to the site's Facebook page.

**Output** (`output/email_scraper/`): one `.csv` and one `.xlsx` per run.

---

## Notes

- The Maps scrapers hit Google's internal Maps endpoints, which can rate-limit.
  Keep concurrency low and use a proxy for larger jobs (configure in each
  `settings.py`).
- Field positions in Google's responses drift over time. If fields start coming
  back empty, the response shape changed — update the `FIELD_PATHS` maps in the
  scraper code to the new indices.
- Each run also writes a `*_failed.txt` next to its output listing any URLs /
  searches that failed, so you can re-feed just those to retry.
- Press **Ctrl+C** to stop a run early — whatever was collected so far is still
  saved before it exits.
