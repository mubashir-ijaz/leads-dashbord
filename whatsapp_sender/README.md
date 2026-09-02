# WhatsApp sender

Sends the dashboard's pitch to every lead that has a WhatsApp / phone number,
one at a time on **WhatsApp Web**, with human-like pauses. Same leads, same
personalised message as the dashboard buttons — just automated.

> [!WARNING]
> Sending unsolicited bulk messages is against WhatsApp's terms and **can get
> your number banned**. Keep batches small (20–30), keep the delays, message
> only real prospects, and stop if people report you. Use a number you can
> afford to lose. This tool is yours to use responsibly.

## Setup (once)

```bash
cd "C:\Users\pc\OneDrive\Desktop\claud\leand compain\whatsapp_sender"
pip install -r requirements.txt
```

You need Google Chrome installed. Selenium 4 downloads the matching driver itself.

## Use

**1. Preview first — builds the messages, sends nothing:**
```bash
python send_whatsapp.py --dry-run
```
Open `preview.csv` and read the messages. Edit the wording in `config.py`
(`PITCH_TEMPLATE`) until you're happy, then re-run the dry run.

**2. Send a small first batch:**
```bash
python send_whatsapp.py --limit 5
```
A Chrome window opens on WhatsApp Web. **First run only:** scan the QR code with
your phone (WhatsApp → Linked devices → Link a device). The login is saved in
`./chrome_profile`, so later runs skip the QR.
Type `go` when prompted. Watch the first few send, then leave it.

**3. Keep going in batches:**
```bash
python send_whatsapp.py            # next BATCH_LIMIT (25) numbers
python send_whatsapp.py            # the next 25 ...
```
Numbers in `sent_log.csv` are skipped automatically, so you can stop with
`Ctrl+C` and re-run any time. `python send_whatsapp.py --all` ignores the limit.

## Options

| Flag | Meaning |
|---|---|
| `--dry-run` | Build messages, write `preview.csv`, send nothing |
| `--limit N` | Send only N this run |
| `--all` | Ignore `BATCH_LIMIT` |
| `--segment "No website"` | Only that segment (repeatable) |

## Files it makes (all in this folder)

| File | What |
|---|---|
| `chrome_profile/` | Your saved WhatsApp Web login — do not delete or commit |
| `sent_log.csv` | Every number successfully messaged (the resume list) |
| `failed_log.csv` | Numbers that were invalid or errored |
| `preview.csv` | Written by `--dry-run` |

## Tuning — `config.py`

- `PITCH_TEMPLATE` — the message. Tokens: `{name} {category} {city} {state} {reason}`.
- `SEGMENTS_TO_SEND` — `["No website", "Low rating"]`.
- `MIN_DELAY_SECONDS` / `MAX_DELAY_SECONDS` — pause between messages (default 25–55s).
- `BATCH_LIMIT` — messages per run (default 25).
- `MIN_REVIEWS`, `SKIP_RATING_ABOVE` — extra filters.
- `LEADS_XLSX` — point at a different export if you like.
