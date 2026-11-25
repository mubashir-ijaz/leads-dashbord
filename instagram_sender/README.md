# Instagram sender

Walks the live leads dashboard page by page and DMs every lead's **Instagram**
with the same pitch shown on the dashboard. Same idea as
`whatsapp_sender/whatsapp_dm.py`, same rules, same three questions - just
pointed at the Instagram button instead of the WhatsApp one, and fully
separate: its own folder, its own `config.py`, its own Chrome profile.

When you click a lead's Instagram button, the dashboard itself copies that
lead's pitch message to your clipboard. This script clicks the button, opens
the profile, clicks **Message**, pastes that clipboard content into the
compose box, and sends it - then moves to the next lead, and to the next
page when a page is done.

> [!WARNING]
> Bulk-DMing strangers on Instagram breaks its terms and **can get the
> account restricted or banned**. Keep batches small, keep the delays,
> message only real prospects, stop if the account gets flagged, use an
> account you can afford to lose.

## Setup (once)

```bash
cd "C:\Users\pc\OneDrive\Desktop\claud\leand compain\instagram_sender"
pip install -r requirements.txt
```

Needs Google Chrome. Selenium 4 fetches the matching driver itself.

## Run it

```bash
python instagram_dm.py
```

It asks three things, same as the WhatsApp runner:

- seconds to wait after each Instagram DM
- which page to start on
- which page to stop after

Then it opens the dashboard, gives you ~25 seconds to:
- pick the category / filters you want in the sidebar
- log in to Instagram in the Chrome window it opens (**first run only** - a
  check tab opens on `instagram.com`; log in there, then let the countdown
  finish). After that, `./chrome_profile` remembers the login.

It then DMs every Instagram-able lead on each page in your range, clicking
the dashboard's Next-page button itself in between, and logs every attempt
to `instagram_dm_clicks.csv` (page, lead, link, status).

Stop any time with `Ctrl+C` - Chrome stays open so you can review.

## Use your real Chrome instead (looks like a real person, not a bot)

By default this drives a fresh, empty automation profile - fine, but it's a
browser Instagram has never seen before, which can look more "bot-like".
If you'd rather it drive **your actual office Chrome** - your real profile,
real cookies, already logged in - use one of these:

```bash
# A) let the script start your real Chrome for you (easiest)
#    close ALL Chrome windows first, then:
python instagram_dm.py --real-chrome

# B) start Chrome yourself with the debug port, then attach (Chrome can stay open)
start_chrome_debug.bat            # double-click it
python instagram_dm.py --attach
```

Both drive the same Chrome you use every day (via its remote-debugging port),
so if you're already logged in to Instagram there, it skips straight to the
run instead of asking you to log in again.

> [!NOTE]
> This automates your **real** Instagram account in your **real** browser.
> That's more convincing to anti-bot checks, but it also means a ban/restriction
> risk lands on your actual account, not a throwaway profile - keep the same
> small-batch, real-delay discipline either way.

## Status values in `instagram_dm_clicks.csv`

| Status | Meaning |
|---|---|
| `sent` | Message pasted and sent |
| `no_message_button` | Couldn't find/click "Message" (private account, not logged in, layout changed, etc.) |
| `no_compose_box` | "Message" opened something but no text box appeared |
| `no_tab` | Clicking the Instagram button didn't open a new tab (popup blocked?) |
| `error: ...` | Unexpected error - the run keeps going |

If you see a lot of `no_message_button` / `no_compose_box`, it usually means
either you're not logged in on this Chrome profile, or Instagram changed its
page markup and the selectors in `ig_web.py` need a small update.

## Files it makes (all in this folder, all git-ignored)

| File | What |
|---|---|
| `chrome_profile/` | Saved Instagram login - don't delete or commit |
| `instagram_dm_clicks.csv` | Every DM attempt, logged |

## Tuning - `config.py`

- `DASHBOARD_URL` / `DASHBOARD_USER` / `DASHBOARD_PASS` - the dashboard and its login.
- `CLICK_WAIT` - default seconds to wait after each DM.
