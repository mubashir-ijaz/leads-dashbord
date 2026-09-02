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

- **Two segments** — `No website` and `Low rating` — as one-click filter chips,
  plus filters for business **category** and **US state**, free-text search, sort,
  and a "hide contacted" toggle.
- **Editable pitch template** with tokens `{name}`, `{category}`, `{city}`,
  `{state}`, `{reason}`. Each lead gets its own filled-in message; `{reason}` is
  chosen from the segment automatically.
- **One-click outreach** — WhatsApp (`wa.me` with the message pre-typed),
  Facebook page, LinkedIn, Instagram, `mailto:` with subject + body, `tel:`, and
  Google Maps. Only the channels a lead actually has are shown. Each button
  remembers it was opened.
- **Import your own leads** — the *Import Excel / CSV* button parses an `.xlsx` /
  `.csv` fully in the browser (bundled [SheetJS](https://sheetjs.com), no CDN),
  auto-detects the columns, and merges (or replaces) the working list.
- **Backup / Reset** — export a JSON snapshot, or reset to the original built-in
  leads.

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
