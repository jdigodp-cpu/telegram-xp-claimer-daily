# Telegram XP Claimer

Automates the daily "Claim XP" / "Daily reward" button in your Telegram group's
mini app and can run on GitHub Actions every day.

## Your setup (PZP Sentry)

Your "Claim" button for "Daily reward: +5 XP" lives **inside the mini app/Web
App** (`app.piratezparty.com`), not as a regular inline button in the Telegram
chat. That means Method A (Telethon button-clicking) cannot reach it — **Method B
(HTTP replay) is the working approach** for your case.

## Method B — replay the mini app's HTTP request (WORKING ✅)

When you click "Claim" in the mini app, it sends:

```
POST https://app.piratezparty.com/api/daily
Body: {}
Header: x-telegram-init-data = <captured from DevTools>
```

### 1. Capture initData (do this once, refresh when it expires)

1. Open Telegram → launch the PZP Sentry mini app
2. Press **F12** → **Network tab**
3. Click the **"Claim"** button
4. Find the `POST /api/daily` request → copy the `x-telegram-init-data` header value
5. The initData looks like:
   `query_id=...&user=...&auth_date=...&hash=...`

### 2. Run locally to test

```powershell
cd C:\Users\raaaaaaj\VSCode\telegram-xp-claimer
./reverse-engineer.ps1 -DryRun
# Then for real:
./reverse-engineer.ps1 -InitData "PASTE_YOUR_INIT_DATA_HERE"
```

### 3. GitHub Actions (daily, automatic)

The workflow in `.github/workflows/daily-claim.yml` runs every day at 09:00 UTC
(and can be triggered manually from the Actions tab).

#### Secrets to add in your repo
(Settings → Secrets and variables → Actions → New repository secret)

| Secret | Value |
|--------|-------|
| `TG_INIT_DATA` | The `x-telegram-init-data` value captured from DevTools (required) |
| `TG_CLAIM_URL` | Optional — defaults to `https://app.piratezparty.com/api/daily` |
| `TG_CLAIM_BODY` | Optional — defaults to `{}` |

#### One-time setup

1. Push this repo to GitHub (credentials are gitignored — never commit them)
2. Add `TG_INIT_DATA` secret with your captured initData value
3. The workflow will now claim XP daily
4. Check the Actions tab or the `xp-claim-logs` artifact for results

#### initData expiry

The initData hash expires over time. If claims start failing (check the Actions
logs), re-capture a fresh initData from DevTools and update the `TG_INIT_DATA`
secret.

## Method A — Telethon (MTProto) — NOT needed for your setup

Included for reference. It clicks inline keyboard buttons in the bot's chat using
your Telegram account, but cannot click inside Web Apps. Your "Claim" button is
inside the PZP Sentry mini app, so Method B is used instead.

Files:
- `reverse-engineer.ps1` — Method B: replays the mini app's HTTP claim request
- `claim-xp-telethon.py` — Method A: Telethon button-clicker (not used for your mini app)
- `claim-xp.ps1` — PowerShell runner for Method A
- `.github/workflows/daily-claim.yml` — GitHub Actions daily schedule
- `config.example.json` — credential template (gitignored)

## Safety notes

* This automates YOUR OWN account in YOUR OWN group. Do not use it to mass-target
  or spam other groups — that may get your Telegram account limited.
* `initData` is a bearer-like credential: never log it or commit it to git.
  `config.json` and `*.session` are gitignored.
