#!/usr/bin/env python3
"""
Telegram XP Claimer — Method A: Telethon (MTProto user client)

Automates clicking a "Claim XP"-style button in a Telegram bot / mini-app chat
using your own Telegram account (API ID + API Hash from my.telegram.org).

Two situations are handled:

1. Callback-button bots (most common) — the "Claim XP" button is an inline
   keyboard button in the chat. Telethon clicks it with
   GetBotCallbackAnswerRequest. This works from a user account.

2. Pure Web-App / Mini App bots — the button lives *inside* the embedded Web
   App. MTProto cannot click inside a Web App. For that case use
   reverse-engineer.ps1 (Method B) to replay the app's HTTP "Claim XP" request
   directly.

Setup
-----
1. Get API_ID and API_HASH at https://my.telegram.org/apps
2. Copy config.example.json to config.json and fill it in (or use env vars,
   see below). Never commit real credentials.
3. Run interactively ONCE to log in:

       python claim-xp-telethon.py --interactive

   This prints a SESSION_STRING. Save it — reuse it in GitHub Actions so you
   never have to re-authenticate (and never enter the login code in CI).
4. Re-runs (incl. GitHub Actions) reuse the session string:

       python claim-xp-telethon.py
       TG_SESSION_STRING=... python claim-xp-telethon.py

Env vars (TG_* prefix) override config.json keys.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Optional

from telethon import TelegramClient
from telethon.errors import PhoneCodeExpiredError, SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl.custom.messagebutton import MessageButton
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("xp-claimer")

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_ERROR = 2

ENV_MAP = {
    "API_ID": "TG_API_ID",
    "API_HASH": "TG_API_HASH",
    "PHONE": "TG_PHONE",
    "BOT_USERNAME": "TG_BOT_USERNAME",
    "SESSION_NAME": "TG_SESSION_NAME",
    "SESSION_STRING": "TG_SESSION_STRING",
    "BUTTON_TEXT": "TG_BUTTON_TEXT",
    "BUTTON_INDEX": "TG_BUTTON_INDEX",
    "CODE": "TG_CODE",
    "PASSWORD": "TG_PASSWORD",
    "MESSAGE_LIMIT": "TG_MESSAGE_LIMIT",
    "DRY_RUN": "TG_DRY_RUN",
}


def load_config(path: Optional[str]) -> dict:
    cfg: dict = {}
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    if not isinstance(cfg, dict):
        log.warning("Config file %s did not contain a JSON object; ignoring it.", path)
        cfg = {}

    # Env vars override the config file.
    for key, env in ENV_MAP.items():
        if env in os.environ:
            cfg[key] = os.environ[env]

    for int_key in ("API_ID", "BUTTON_INDEX", "MESSAGE_LIMIT"):
        if int_key in cfg:
            try:
                cfg[int_key] = int(cfg[int_key])
            except (TypeError, ValueError):
                log.warning("Ignoring invalid integer for %s", int_key)
                cfg.pop(int_key, None)

    cfg.setdefault("BUTTON_TEXT", "Claim XP")
    cfg.setdefault("SESSION_NAME", "xp_claimer_session")
    cfg.setdefault("MESSAGE_LIMIT", 100)
    cfg.setdefault("DRY_RUN", False)
    return cfg


HASH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".phone_code_hash")


async def ensure_authorized(client: TelegramClient, cfg: dict) -> bool:
    """Log in interactively if needed. Returns True when authorized.

    Two-step flow to avoid code/hash mismatch across runs:

    Step 1 (no TG_CODE): call send_code_request, save phone_code_hash to a
    temp file, print instructions, return False. User provides the code they
    received.

    Step 2 (with TG_CODE): read the saved hash, call sign_in with it, delete
    the temp file, return True on success.
    """
    if await client.is_user_authorized():
        return True

    api_id = cfg.get("API_ID")
    api_hash = cfg.get("API_HASH")
    phone = cfg.get("PHONE")
    if not api_id or not api_hash:
        log.error("TG_API_ID and TG_API_HASH are required to log in.")
        return False
    if not phone:
        log.error("Not authorized and no TG_PHONE configured. Run with --interactive once to log in.")
        return False

    code = cfg.get("CODE")
    password = cfg.get("PASSWORD")

    try:
        if not code:
            # Step 1: request a code and persist the hash for the next run.
            sent = await client.send_code_request(phone)
            with open(HASH_FILE, "w", encoding="utf-8") as f:
                json.dump({"phone_code_hash": sent.phone_code_hash, "phone": phone}, f)
            log.info("Login code sent to %s.", phone)
            log.info("Re-run this script with -Code <the-code-you-just-received> to complete login.")
            if password:
                log.info("2FA password is configured; it will be used on the next run.")
            return False

        # Step 2: code provided — use the saved hash to sign in.
        if not os.path.exists(HASH_FILE):
            log.error("No saved login hash found. Run without -Code first to request a login code.")
            return False

        with open(HASH_FILE, "r", encoding="utf-8") as f:
            hash_data = json.load(f)
        saved_phone = hash_data.get("phone")
        phone_code_hash = hash_data.get("phone_code_hash")
        if saved_phone and saved_phone != phone:
            log.error("Saved hash is for a different phone number (%s). Delete .phone_code_hash and retry.", saved_phone)
            return False

        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        try:
            os.remove(HASH_FILE)
        except OSError:
            pass
    except SessionPasswordNeededError:
        if not password:
            log.error("Two-step verification is enabled. Set TG_PASSWORD and re-run with -Code <code>.")
            return False
        await client.sign_in(password=password)
        try:
            os.remove(HASH_FILE)
        except OSError:
            pass
    except PhoneCodeExpiredError:
        log.error("Login code expired. Re-run without -Code to request a new one.")
        return False
    except Exception as exc:  # noqa: BLE001 — report and let caller decide
        log.error("Login failed: %s", exc)
        return False

    return await client.is_user_authorized()


async def find_and_click(client: TelegramClient, cfg: dict) -> bool:
    """Scan recent messages from the bot and click matching buttons."""
    bot = await client.get_entity(cfg["BOT_USERNAME"])
    button_text = str(cfg["BUTTON_TEXT"]).lower()
    button_index = cfg.get("BUTTON_INDEX")  # None = match by text
    dry_run = bool(cfg["DRY_RUN"])
    clicked_any = False
    match_count = 0

    async for message in client.iter_messages(bot, limit=int(cfg["MESSAGE_LIMIT"])):
        if not message.buttons:
            continue
        for row_idx, row in enumerate(message.buttons):
            for col_idx, button in enumerate(row):
                text = getattr(button, "text", "") or ""
                if button_index is not None:
                    if match_count != button_index:
                        match_count += 1
                        continue
                elif button_text not in text.lower():
                    continue

                match_count += 1
                button_data = getattr(button, "data", None)  # bytes for callback buttons, None otherwise

                log.info(
                    "Found button %r on message id %s (row %s, col %s, has_callback_data=%s)",
                    text, message.id, row_idx, col_idx, bool(button_data),
                )

                if not button_data:
                    log.warning(
                        "Button %r is not a clickable inline-callback button (Web-App / URL / switch-inline). "
                        "MTProto cannot click inside Web Apps — use reverse-engineer.ps1 (Method B) to replay "
                        "the app's HTTP 'Claim XP' request.",
                        text,
                    )
                    continue

                if dry_run:
                    log.info("[DRY-RUN] Would click button %r on message id %s", text, message.id)
                    clicked_any = True
                    continue

                try:
                    # MessageButton.click() internally calls GetBotCallbackAnswerRequest.
                    result = await button.click()
                    answer = getattr(result, "message", None) or "ok"
                    log.info("Clicked button %r on message id %s -> %s", text, message.id, answer)
                    clicked_any = True
                except Exception as exc:  # noqa: BLE001
                    log.error("Failed to click button %r on message id %s: %s", text, message.id, exc)

                # Only one claim per run is usually wanted; stop after first success.
                if clicked_any and not dry_run:
                    return True

    return clicked_any


async def main() -> int:
    argv = sys.argv[1:]
    config_path = "config.json"
    if "--interactive" in argv:
        argv.remove("--interactive")
    if argv:
        config_path = argv[0]

    cfg = load_config(config_path)

    missing = [k for k in ("API_ID", "API_HASH") if not cfg.get(k)]
    if missing:
        log.error(
            "Missing required credentials: %s. Get them at https://my.telegram.org/apps "
            "and set them in config.json or as TG_* environment variables.",
            ", ".join(missing),
        )
        return EXIT_ERROR

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
            # Help the user bootstrap CI: show them a reusable session string.
            if not session_string:
                try:
                    saved = client.session.save()
                    if isinstance(saved, str) and saved:
                        log.info("AUTH_SESSION_STRING=%s", saved)
                        log.info("Save TG_SESSION_STRING='%s' in GitHub Actions secrets to avoid re-logging in.", saved)
                except Exception as exc:  # noqa: BLE001
                    log.debug("Could not produce session string: %s", exc)
            return EXIT_ERROR

        clicked = await find_and_click(client, cfg)
        if clicked:
            log.info("XP claim processed successfully.")
            return EXIT_OK
        if bool(cfg["DRY_RUN"]):
            log.info("[DRY-RUN] Complete. No button was actually clicked.")
            return EXIT_OK
        log.warning("No matching button (%r) found in the last %s messages from %s.",
                    cfg["BUTTON_TEXT"], cfg["MESSAGE_LIMIT"], cfg.get("BOT_USERNAME"))
        return EXIT_NOT_FOUND
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        raise SystemExit(130)
