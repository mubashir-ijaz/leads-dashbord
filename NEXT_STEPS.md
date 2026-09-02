# Leads Outreach Dashboard — Progress & Next Steps

_Last updated: 2026-09-02_

## Done

- **`index.html`** — rebuilt dashboard (replaces `outreach_queue.html`, kept in git
  history). Self-contained HTML + CSS + JS. Features:
  - Two segments as filter chips: **No website** (149) / **Low rating** (263).
  - Filters: business **Category**, **US State**, search, sort, "hide contacted".
  - **Auto-click outreach panel**: pick a button (WhatsApp/FB/IG/LinkedIn/Email),
    set the delay in seconds, set a From#–To# row range, Start — it opens each
    lead's link in one reused tab on a timer, marks it contacted, Stop halts it.
    Pure browser JS (no Python); user must allow pop-ups for the site once.
  - **Editable pitch template** with `{name} {category} {city} {state} {reason}`
    tokens; `{reason}` auto-set from the segment. Per-lead filled message shown.
  - **One-click outreach**: WhatsApp (message pre-typed), Facebook, LinkedIn,
    Instagram, Email (subject + body), Call, Maps — only channels the lead has.
    Every button remembers it was opened; per-lead "Mark contacted".
  - **Import Excel / CSV** — client-side parse via bundled SheetJS
    (`vendor/xlsx.full.min.js`, no CDN), auto column-detect, merge or replace,
    saved to `localStorage`.
  - **Backup** (JSON export) and **Reset to built-in leads**.
- **`data_leads.js`** — `window.DEFAULT_LEADS`, 412 leads generated from
  `leads_20260827_160011.xlsx`. Loads automatically on first visit.
- **`middleware.js`** — Vercel Edge Middleware, HTTP Basic Auth over the whole
  site. Default `sam` / `samsam`; override with `DASH_USER` / `DASH_PASS` env
  vars in Vercel.
- **`vercel.json`** — static config, noindex headers, no-cache on the HTML.
- **`README.md`** — usage + deploy steps.

## Next steps (interactive — the user runs these)

### 1. Push to GitHub — remote already created: `https://github.com/mubashir-ijaz/leads-dashbord`

```
git remote add origin https://github.com/mubashir-ijaz/leads-dashbord.git
git push -u origin master
```

Git Credential Manager will pop up a browser window to sign in to GitHub the
first time — approve it there.

### 2. Deploy on Vercel (interactive login in browser)

```
npx vercel        # links the project on first run
npx vercel --prod
```

### 3. Set a private password (optional but recommended — repo is public)

```
npx vercel env add DASH_USER production      # e.g. sam
npx vercel env add DASH_PASS production      # your real password
npx vercel --prod                            # redeploy so it takes effect
```

Until then the live login is **sam / samsam** (visible in `middleware.js`).

## Files in this folder

- `index.html` — the dashboard (open directly, works offline).
- `data_leads.js` — starter 412-lead dataset.
- `vendor/xlsx.full.min.js` — SheetJS (vendored).
- `middleware.js` — password gate (Vercel only).
- `vercel.json` — hosting config.
- `leads_20260827_160011.xlsx` — original scraped source.
- `.gitignore` — excludes `.claude/`, `.vercel/`, `node_modules/`.
