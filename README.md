# Telegram XP Claimer

Fully automated daily "Claim XP" for your Telegram mini app, running on GitHub
Actions with **no manual steps** — no initData capture, no SMS codes in CI, no
bot ownership needed.

## How it works

Uses Telegram's `messages.requestWebView` API via Telethon. When you request a
Web App view, Telegram's servers generate a **freshly signed initData** URL
(`#tgWebAppData=...`) and return it to your client. The script extracts this
initData and POSTs it to the mini app's `/api/daily` endpoint to claim XP.

Since Telegram generates the initData server-side every time, it's always valid
— no expiration, no manual capture needed.

## Your setup (PZP Sentry)

Verified working against `app.piratezparty.com/api/daily`:
- `{"claimed":true,"balance":210,...}` — XP claimed successfully ✅

## Prerequisites

* Telegram API ID and API Hash from https://my.telegram.org/apps
* Your phone number (international format, e.g. +919370208002)

## 1. First-time login (on your PC, one-time only)

```powershell
cd C:\Users\raaaaaaj\VSCode\telegram-xp-claimer

# Copy config template
copy config.example.json config.json
# Edit config.json with your API_ID, API_HASH, PHONE, BOT_USERNAME

# Run interactively — enter the SMS code Telegram sends you
& "C:\Users\raaaaaaj\AppData\Local\Programs\Python\Python311\python.exe" claim-xp-requestwebview.py --interactive
```

When login succeeds, the script prints `AUTH_SESSION_STRING=...` — **copy this
value**. You'll use it as a GitHub secret so you never log in again.

## 2. Re-run locally (no login needed)

```powershell
& "C:\Users\raaaaaaj\AppData\Local\Programs\Python\Python311\python.exe" claim-xp-requestwebview.py config.json
```

Add `-DryRun` to test without actually claiming.

## 3. GitHub Actions (fully automated, daily)

The workflow in `.github/workflows/daily-claim.yml` runs every day at 09:00 UTC
(and can be triggered manually from the Actions tab).

### Secrets to add
(Settings → Secrets and variables → Actions → New repository secret)

| Secret | Value |
|--------|-------|
| `TG_API_ID` | Your Telegram API ID |
| `TG_API_HASH` | Your Telegram API Hash |
| `TG_SESSION_STRING` | The `AUTH_SESSION_STRING` from step 1 |
| `TG_PHONE` | Your phone number (fallback only) |
| `TG_BOT_USERNAME` | The bot username, without `@` (e.g. `pzpsentrybot`) |

### One-time setup

1. Push this repo to GitHub
2. Add the 5 secrets above
3. The workflow will claim XP daily — check the Actions tab or the
   `xp-claim-logs` artifact for results

### No initData refresh needed

Unlike the old HTTP-replay approach, `requestWebView` gets **fresh initData from
Telegram's servers every run**. There's nothing to expire and nothing to
manually update.

## Files

| File | Purpose |
|------|---------|
| `claim-xp-requestwebview.py` | Main script — fully automated via requestWebView |
| `claim-xp-telethon.py` | Method A — inline button clicker (reference, not used for Web Apps) |
| `claim-xp.ps1` | PowerShell runner for Method A |
| `reverse-engineer.ps1` | Method B — manual HTTP replay (reference) |
| `config.example.json` | Credential template |
| `.github/workflows/daily-claim.yml` | GitHub Actions daily schedule |
| `README.md` | These instructions |

## Safety notes

* This automates YOUR OWN account in YOUR OWN group. Do not mass-target or spam.
* The session string is a bearer-like credential — never log it or commit it.
  `config.json`, `*.session`, and session strings are gitignored.
