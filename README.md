# Leads Outreach Dashboard

A single-page dashboard for working a list of business leads: filter them, open a
pre-written pitch in WhatsApp / Facebook / LinkedIn / Instagram / Email / Phone in
one click, and track who you've already contacted — all saved in your browser.

## Live use

1. Open the site — the browser asks for a login (HTTP Basic Auth).
   - Default: user `sam`, password `samsam`.
   - To change it: Vercel → Project → **Settings → Environment Variables** →
     add `DASH_USER` and `DASH_PASS`, then redeploy.
2. The 412 starter leads load automatically. Everything you do (imports, contacted
   marks, edited pitch text) is stored in **your browser** (`localStorage`).

## Features

- **CRM-style category sidebar** — a left panel lists every category with its
  live lead count. Click one to work only that category. The 412 starter leads
  are pre-sorted into **Hotels / Restaurants / Coffee Shops**; imports add
  whatever category you name. "All leads" shows everything.
- **Done → Follow-up** — the ✓ next to a category (or the button in the main
  header) marks it done and moves it to a **Follow-up** section at the bottom of
  the sidebar; ↩ moves it back to active.
- **Import = name the category first** — the *Import Excel / CSV* button opens a
  two-step modal: (1) type the category name for the file (quick-pick chips for
  existing categories), (2) choose the `.xlsx` / `.csv`. **Every row** in the
  sheet is filed under that category. Parsed fully in the browser with bundled
  [SheetJS](https://sheetjs.com) (no CDN); merges by default, or replaces just
  that category's leads.
- **Pagination** — 25 leads per page with a numbered pager.
- **Two segments** (`No website` / `Low rating`) as filter chips, plus **US
  state**, free-text search, sort, an "Under 200 reviews" toggle and a "hide
  contacted" toggle. KPI tiles reflect the current view.
- **Editable pitch template** with tokens `{name}`, `{category}`, `{group}`,
  `{city}`, `{state}`, `{reason}`, `{review_offer}`. `{category}` is the specific
  business type, `{group}` is the sidebar category; `{reason}` comes from the
  segment; `{review_offer}` (an offer to grow their Google reviews) only appears
  for leads under 200 reviews.
- **Copy message** — a prominent button on every card copies that lead's
  personalised message (with a `file://` clipboard fallback).
- **One-click outreach** — WhatsApp (`wa.me` with the message pre-typed),
  Facebook page, LinkedIn, Instagram, `mailto:` with subject + body, `tel:`, and
  Google Maps. Only the channels a lead actually has are shown. Each button
  remembers it was opened.
- **Auto-click outreach** — walk the whole filtered list opening one channel link
  every N seconds (collapsible panel).
- **Backup / Reset** — export a JSON snapshot (leads + categories + history), or
  reset to the original built-in leads.

## Files

| File | Purpose |
|---|---|
| `index.html` | The whole dashboard (HTML + CSS + JS in one file). |
| `data_leads.js` | Starter dataset — `window.DEFAULT_LEADS`, generated from `leads_20260827_160011.xlsx`. |
| `vendor/xlsx.full.min.js` | SheetJS, vendored so the import works offline. |
| `middleware.js` | Vercel Edge Middleware — the Basic Auth password gate. |
| `vercel.json` | Static hosting config (no-index headers, no-cache on the HTML). |
| `leads_20260827_160011.xlsx` | Original scraped source. |

## Deploy

```bash
npm i -g vercel        # or: npx vercel
vercel                 # first run links the project
vercel --prod          # deploy
```

Set a private password before sharing the URL:

```bash
vercel env add DASH_USER production
vercel env add DASH_PASS production
vercel --prod
```

## Run locally

Just open `index.html` in a browser — it works from `file://`. (The password gate
only runs on Vercel.)
