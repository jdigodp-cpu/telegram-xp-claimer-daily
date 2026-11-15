#!/usr/bin/env python3
"""
Telegram XP Claimer — Method D: requestWebView (FULLY AUTOMATED on GitHub Actions).

Uses Telethon's messages.requestWebView to ask Telegram's servers for a fresh
Web App view URL. The returned URL contains `#tgWebAppData=<initData>` — initData
that is freshly generated and HMAC-signed by Telegram (using the bot's token),
so it's always valid. No manual capture, no SMS in CI, no bot ownership needed.

Flow
----
1. First run (interactive, on your PC): log in once with phone + SMS code.
   The script prints AUTH_SESSION_STRING — save it as a GitHub secret.
2. Every run (incl. GitHub Actions): reuse the session string, call
   requestWebView → extract tgWebAppData → POST to /api/daily → claim XP.

Setup
-----
1. Get API_ID and API_HASH at https://my.telegram.org/apps
2. Copy config.example.json to config.json, fill in API_ID / API_HASH / PHONE /
   BOT_USERNAME.
3. Run interactively once:
       python claim-xp-requestwebview.py --interactive
   Save the printed AUTH_SESSION_STRING.
4. On GitHub Actions, add secrets: TG_API_ID, TG_API_HASH, TG_SESSION_STRING,
   TG_PHONE, TG_BOT_USERNAME.

Why this works
--------------
Telegram's requestWebView endpoint generates initData server-side and returns it
to the client. The initData includes a fresh auth_date and HMAC signature, so
it passes the PZP Sentry backend's validation every run. Your user account is
the one launching the Web App, so the backend sees a legitimate session.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

from telethon import TelegramClient
from telethon.errors import PhoneCodeExpiredError, SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl.functions.messages import RequestWebViewRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("xp-claimer")

ENV_MAP = {
    "API_ID": "TG_API_ID",
    "API_HASH": "TG_API_HASH",
    "PHONE": "TG_PHONE",
    "BOT_USERNAME": "TG_BOT_USERNAME",
    "SESSION_NAME": "TG_SESSION_NAME",
    "SESSION_STRING": "TG_SESSION_STRING",
    "WEB_APP_URL": "TG_WEB_APP_URL",
    "CLAIM_URL": "TG_CLAIM_URL",
    "CODE": "TG_CODE",
    "PASSWORD": "TG_PASSWORD",
    "DRY_RUN": "TG_DRY_RUN",
}


def load_config(path: Optional[str]) -> dict:
    cfg: dict = {}
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    if not isinstance(cfg, dict):
        cfg = {}

    for key, env in ENV_MAP.items():
        if env in os.environ:
            cfg[key] = os.environ[env]

    for int_key in ("API_ID",):
        if int_key in cfg:
            try:
                cfg[int_key] = int(cfg[int_key])
            except (TypeError, ValueError):
                log.warning("Ignoring invalid integer for %s", int_key)
                cfg.pop(int_key, None)

    cfg.setdefault("SESSION_NAME", "xp_claimer_session")
    cfg.setdefault("WEB_APP_URL", "https://app.piratezparty.com/")
    cfg.setdefault("CLAIM_URL", "https://app.piratezparty.com/api/daily")
    cfg.setdefault("DRY_RUN", False)
    return cfg


async def ensure_authorized(client: TelegramClient, cfg: dict) -> bool:
    if await client.is_user_authorized():
        return True

    api_id = cfg.get("API_ID")
    api_hash = cfg.get("API_HASH")
    phone = cfg.get("PHONE")
    if not api_id or not api_hash:
        log.error("TG_API_ID and TG_API_HASH are required to log in.")
        return False
    if not phone:
        log.error("Not authorized and no TG_PHONE configured.")
        return False

    code = cfg.get("CODE")
    try:
        sent = await client.send_code_request(phone)
        log.info("Login code sent to %s.", phone)
        if not code:
            code = input("Enter the login code: ").strip()
        await client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
    except SessionPasswordNeededError:
        password = cfg.get("PASSWORD") or input("2FA password: ")
        await client.sign_in(password=password)
    except PhoneCodeExpiredError:
        log.error("Login code expired.")
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("Login failed: %s", exc)
        return False

    return await client.is_user_authorized()


def extract_init_data_from_url(url: str) -> Optional[str]:
    """Extract tgWebAppData from a Web View result URL."""
    # URL may look like:
    # https://app.piratezparty.com/?tgWebAppData=query_id=...&user=...&hash=...#tgWebAppData=...
    # or with the data in the fragment
    parsed = urlparse(url)

    # Check fragment first (#tgWebAppData=...)
    fragment = parsed.fragment
    if fragment:
        params = parse_qs(fragment)
        if "tgWebAppData" in params:
            return unquote(params["tgWebAppData"][0])

    # Check query string (?tgWebAppData=...)
    query = parse_qs(parsed.query)
    if "tgWebAppData" in query:
        return unquote(query["tgWebAppData"][0])

    return None


async def get_fresh_init_data(client: TelegramClient, cfg: dict) -> Optional[str]:
    """Call requestWebView to get a fresh initData URL from Telegram."""
    bot = await client.get_entity(cfg["BOT_USERNAME"])

    log.info("Requesting Web View from @%s ...", cfg["BOT_USERNAME"])

    result = await client(RequestWebViewRequest(
        peer=bot,
        bot=bot,
        platform="desktop",
        url=cfg["WEB_APP_URL"],
    ))

    # result is a WebViewResultUrl with a .url attribute
    web_view_url = getattr(result, "url", None)
    if not web_view_url:
        log.error("requestWebView returned no URL: %r", result)
        return None

    log.info("Got Web View URL: %s", web_view_url[:200])

    init_data = extract_init_data_from_url(web_view_url)
    if not init_data:
        log.error("Could not extract tgWebAppData from Web View URL.")
        return None

    log.info("Extracted fresh initData (length %d)", len(init_data))
    return init_data


async def claim_xp(init_data: str, cfg: dict, dry_run: bool) -> bool:
    """POST initData to the daily claim endpoint."""
    import aiohttp

    headers = {
        "Content-Type": "application/json",
        "Origin": "https://app.piratezparty.com",
        "Referer": "https://app.piratezparty.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Telegram-Init-Data": init_data,
    }

    if dry_run:
        log.info("[DRY-RUN] Would POST to %s with initData header", cfg["CLAIM_URL"])
        return True

    async with aiohttp.ClientSession() as session:
        async with session.post(cfg["CLAIM_URL"], headers=headers, json={}) as resp:
            text = await resp.text()
            if resp.status == 200:
                log.info("XP claim successful (status 200): %s", text[:300])
                return True
            else:
                log.error("Claim failed with status %s: %s", resp.status, text[:300])
                return False


async def main() -> int:
    argv = sys.argv[1:]
    config_path = "config.json"
    if "--interactive" in argv:
        argv.remove("--interactive")
    if argv:
        config_path = argv[0]

    cfg = load_config(config_path)

    missing = [k for k in ("API_ID", "API_HASH", "PHONE", "BOT_USERNAME") if not cfg.get(k)]
    if missing:
        log.error("Missing required config: %s. Set in config.json or TG_* env vars.",
                  ", ".join(missing))
        return 2

    session_string = cfg.get("SESSION_STRING")
    session_name = cfg.get("SESSION_NAME")
    client = TelegramClient(
        StringSession(session_string) if session_string else session_name,
        int(cfg["API_ID"]),
        cfg["API_HASH"],
    )

    await client.connect()
    try:
        authorized = await ensure_authorized(client, cfg)
        if not authorized:
            if not session_string:
                try:
                    saved = client.session.save()
                    if isinstance(saved, str) and saved:
                        log.info("AUTH_SESSION_STRING=%s", saved)
                        log.info("Save TG_SESSION_STRING='%s' in GitHub Actions secrets.", saved)
                except Exception as exc:  # noqa: BLE001
                    log.debug("Could not produce session string: %s", exc)
            return 2

        # Get fresh initData from Telegram's requestWebView
        init_data = await get_fresh_init_data(client, cfg)
        if not init_data:
            return 1

        # Claim XP
        dry_run = bool(cfg["DRY_RUN"])
        if await claim_xp(init_data, cfg, dry_run):
            log.info("XP claim processed successfully.")
            return 0
        return 1
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        raise SystemExit(130)
