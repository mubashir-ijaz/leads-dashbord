# WhatsApp sender

Sends the dashboard's pitch on **WhatsApp Web** to the leads that are **actually
on WhatsApp** — one at a time, with human-like pauses. Same leads, same
personalised message as the dashboard buttons, just automated.

The scraper's `WhatsApp` column is only a guess (it formats every phone number as
a `wa.me` link). Most of those numbers are **not** real WhatsApp accounts, so
there are two scripts:

| Script | What it does | Sends messages? |
|---|---|---|
| `check_whatsapp.py` | Opens each number on WhatsApp Web, records which ones exist → `whatsapp_numbers.csv` | **No** |
| `send_whatsapp.py` | Messages only the numbers in `whatsapp_numbers.csv` | Yes |

> [!WARNING]
> Bulk-messaging strangers breaks WhatsApp's terms and **can get your number
> banned**. Keep batches small (20–30), keep the delays, message only real
> prospects, stop if people report you, use a number you can afford to lose.

## Setup (once)

```bash
cd "C:\Users\pc\OneDrive\Desktop\claud\leand compain\whatsapp_sender"
pip install -r requirements.txt
```

Needs Google Chrome. Selenium 4 fetches the matching driver itself.

## Step 1 — find who's on WhatsApp

```bash
python check_whatsapp.py                 # check all leads
python check_whatsapp.py --limit 50      # or just 50 at a time
```

A Chrome window opens on WhatsApp Web. **First run only:** scan the QR code with
your phone (WhatsApp → Linked devices → Link a device). Login is saved in
`./chrome_profile`, so later runs skip the QR. Type `go` when prompted.

Each line shows a running tally, e.g.:

```
[ 12/389] +14134435661  FairBridge Inn Express    ON WhatsApp     | on WA 3 / 12  (25%)  | ETA  71m
```

It writes:
- **`whatsapp_numbers.csv`** — numbers confirmed on WhatsApp (the send list)
- **`not_on_whatsapp.csv`** — numbers WhatsApp rejected

Stop with `Ctrl+C` any time; checked numbers are skipped next run. Run
`check_whatsapp.py --recheck` to re-test everything.

Check progress at any point without opening a browser:

```bash
python check_whatsapp.py --summary
```

> The **WhatsApp desktop app** login does not carry over — this script uses
> WhatsApp Web in its own Chrome profile, so you scan the QR once in the window
> it opens. After that `./chrome_profile` remembers it.
> Add `--yes` to skip the `go` prompt once you trust it.

## Step 2 — preview the messages

```bash
python send_whatsapp.py --dry-run
```

Reads `whatsapp_numbers.csv`, builds each message, writes `preview.csv`, sends
nothing. Tweak the wording in `config.py` (`PITCH_TEMPLATE`) and repeat.

## Step 3 — send in small batches

```bash
python send_whatsapp.py --limit 5     # first batch of 5
python send_whatsapp.py              # next BATCH_LIMIT (25)
python send_whatsapp.py              # the next 25 ...
```

Numbers in `sent_log.csv` are skipped, so stopping and re-running is safe.
`--all` ignores the batch limit. `--ignore-checked` sends without a verified list
(not advised — you'll hit lots of dead numbers).

## Options

| Flag | `check_whatsapp.py` | `send_whatsapp.py` |
|---|---|---|
| `--limit N` | check only N | send only N |
| `--segment "No website"` | that segment only (repeatable) | same |
| `--recheck` | re-test already-checked numbers | — |
| `--dry-run` | — | build `preview.csv`, send nothing |
| `--all` | — | ignore `BATCH_LIMIT` |
| `--ignore-checked` | — | send without `whatsapp_numbers.csv` |

## Files it makes (all in this folder, all git-ignored)

| File | What |
|---|---|
| `chrome_profile/` | Saved WhatsApp Web login — don't delete or commit |
| `whatsapp_numbers.csv` | Numbers confirmed on WhatsApp |
| `not_on_whatsapp.csv` | Numbers confirmed not on WhatsApp |
| `sent_log.csv` | Every number messaged (resume list) |
| `failed_log.csv` | Sends that errored |
| `preview.csv` | From `--dry-run` |

## Tuning — `config.py`

- `PITCH_TEMPLATE` — the message. Tokens: `{name} {category} {city} {state} {reason}`.
- `SEGMENTS_TO_SEND` — `["No website", "Low rating"]`.
- `WHATSAPP_COLUMN_ONLY` — ignore the plain `Phone` column (default on).
- `USE_CHECKED_LIST` — send only verified numbers (default on).
- `MIN_DELAY_SECONDS` / `MAX_DELAY_SECONDS` — pause between messages (25–55s).
- `CHECK_MIN_DELAY_SECONDS` / `CHECK_MAX_DELAY_SECONDS` — pause between checks (8–18s).
- `BATCH_LIMIT` — messages per run (25).
- `MIN_REVIEWS`, `SKIP_RATING_ABOVE` — extra filters.
