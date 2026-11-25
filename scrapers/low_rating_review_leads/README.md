# Low-Rating / No-Website Review-Leads Scraper

A thin **leads layer** on top of the three engines in the main
**"Google Maps & Contacts Scraper"** project. It finds businesses worth
pitching web / reputation services to:

> keep a business when it has **no real website** *or* a rating **≤ 4.0**

…then gives you their **phone, a WhatsApp (`wa.me`) link, email, and
Facebook / Instagram / LinkedIn** — pulling socials from their website when they
have one, and searching for them by name when they don't.

Nothing in the main project is changed. This folder only adds files; it *calls*
`scrapers/link_collector`, `scrapers/business_details` and
`scrapers/email_scraper` from that project.

**Where this folder lives:** inside the main project, or right next to it — both
work. `run_leads.py` auto-detects the project (the folder that has `console.py`
and `scrapers/`). If it can't, set `PROJECT_ROOT` at the top of `leads_config.py`
to the full path of `Google Maps & Contacts Scraper Transfer`.

---

## Run it

`cd` to wherever this `low_rating_review_leads` folder is, then:

```bat
python run_leads.py                 :: full run — every category x state
python run_leads.py --test          :: 1 category x 1 state (quick check)
python run_leads.py --limit 6       :: only the first 6 category x state searches
python run_leads.py --no-social     :: skip the name-based social lookup
python run_leads.py --filter-only "output\_work\Google Maps - SOMEFILE.xlsx"
```

(Or run it by full path from anywhere:
`python "C:\...\low_rating_review_leads\run_leads.py"`.)

`--filter-only` re-runs just the leads filter (stage 3) on an existing
business-details sheet — fast, no scraping, handy for re-tuning the thresholds.

Press **Ctrl+C** any time. Each stage saves what it has; the social-lookup pass
rewrites the leads sheet every 25 rows.

---

## What it does (3 stages)

| # | Stage | Engine | Output |
|---|-------|--------|--------|
| 1 | Collect Maps links for `"<category> in <state>"` (Playwright browser) | `scrapers/link_collector` | `output/_work/links_*.csv` |
| 2 | Scrape full business details + crawl each website for emails / socials | `scrapers/business_details` | `output/_work/Google Maps - *.xlsx` |
| 3 | Filter to leads, add WhatsApp, look up socials by name | this folder | `output/leads_*.xlsx` + `.csv` |

### Stage 3 — the leads sheet columns

`Name, Category, Rating, Reviews, Has Website, Website Type, Website, Phone,
WhatsApp, Email, Facebook, Instagram, LinkedIn, LinkedIn (owner) - enrich,
Address, City, State, Maps URL, Why kept, Social lookup, Scraped Date`

- **Has Website / Website Type** — `No` / `Social only` (FB/IG/Linktree page) /
  `Chain` (corporate or booking-site domain) / `Yes` (own real site).
  `No` and `Social only` are the prime web-design leads and sort to the top.
- **WhatsApp** — `https://wa.me/<number>` built from the Maps phone (digits
  only, US country code added). It is *not* verified as an active WhatsApp
  account — it's the phone they published, formatted for a one-tap message.
- **Email / Facebook / Instagram / LinkedIn** — from the website crawl when
  `Social lookup = from website`; from a name search when `found by name`;
  blank when `not found`.
- **LinkedIn (owner) - enrich** — always blank. Owner names/emails aren't
  scrapable from LinkedIn; run this column through Apollo / Hunter / Clearbit
  if you need decision-maker contacts.
- **Why kept** — e.g. `no website`, `low rating (3.2)`, `social page only`.

---

## Settings — `leads_config.py`

| Setting | Default | Meaning |
|---|---|---|
| `MAX_RATING` | `4.0` | "low rating" = at or below this |
| `KEEP_IF_NO_WEBSITE` / `KEEP_IF_LOW_RATING` | `True` / `True` | the two keep rules (OR'd) |
| `SOCIAL_AS_NO_WEBSITE` | `True` | a FB/IG/Linktree-only "website" counts as no website |
| `DROP_CHAIN_SITE_ROWS` | `False` | `True` = drop chain/booking-site rows entirely |
| `CHAIN_OR_AGGREGATOR_DOMAINS` / `SOCIAL_ONLY_DOMAINS` | lists | edit to taste |
| `LINK_COLLECTOR` | `"playwright"` | `"playwright"` (~120/search, blocks easily) or `"api"` (~20/search, proxy-capable, block-resistant) |
| `USE_PROXY` / `PROXY_URL` | `False` / `""` | rotating residential proxy — used by API link collection **and** business details |
| `MAX_RESULTS_PER_SEARCH` | `0` | playwright: 0 = scroll to end of list (~120/search) |
| `PER_SEARCH_DELAY` | `8.0` | seconds between Maps searches |
| `API_TILE` | `False` | api mode: grid of requests per search (100s of results) instead of ~20 |
| `BUSINESS_MAX_WORKERS` | `2` | keep low — Google rate-limits |
| `CRAWL_WEBSITES_FOR_CONTACTS` | `True` | crawl each real website for email/socials |
| `SOCIAL_LOOKUP_ENABLED` | `True` | name-based FB/IG/LinkedIn search for no-website leads |
| `SOCIAL_LOOKUP_MAX` | `0` | 0 = every lead missing socials; set e.g. `400` to cap |
| `SOCIAL_LOOKUP_DELAY` | `2.5` | seconds between search queries |

**Search terms:** `input/categories.txt` (one per line) × `input/states.txt`.
Swap state names for city names (`"Birmingham, AL"`) for deeper local coverage.

---

## Scale & limits — read before the full run

- **`hotels` + `restaurants` × 50 states = 100 searches.** Expect **several
  hours** and 10k+ businesses.
- **Google WILL CAPTCHA a bare IP on a run this size.** In testing, ~250
  requests was enough to trigger `google.com/sorry/` ("unusual traffic"), after
  which the Playwright browser collects nothing. `run_leads.py` now does a
  pre-flight check and aborts immediately if the IP is already blocked. To
  actually complete a nationwide run you need **one of**:
    1. a **rotating residential proxy** — set `USE_PROXY` / `PROXY_URL`
       (works with `LINK_COLLECTOR = "api"` and with business details);
    2. `LINK_COLLECTOR = "api"` + small `--limit` batches spread over time;
    3. run **10-15 states at a time** (`--limit`), hours apart, and accept it
       takes days.
  A soft block clears on its own after ~30-60 min of no traffic.
- **No website = little to crawl.** Email and LinkedIn are usually blank for
  exactly the no-website leads — that's why stage 3 does the name-based social
  search. It's best-effort: it misses, and for common names it can grab the
  wrong page. Eyeball before sending.
- **Chain franchises** (Days Inn, Hampton Inn…) show as `Website Type = Chain`.
  They're kept only when also low-rated. Set `DROP_CHAIN_SITE_ROWS = True` to
  exclude them and focus purely on independents.
- **LinkedIn owner data** is not scraped (LinkedIn blocks bots / ToS). Use the
  `LinkedIn` page URL + an enrichment service for decision-maker contacts.
- Be mindful of local laws (GDPR/CAN-SPAM/TCPA etc.) when contacting these
  businesses.
