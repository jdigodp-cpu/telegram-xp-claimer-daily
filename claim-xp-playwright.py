#!/usr/bin/env python3
"""
Telegram XP Claimer — Method C: Playwright browser automation (FULLY AUTOMATED).

Launches a real Chromium browser, logs into Telegram Web, opens the PZP Sentry
mini app, extracts the live initData from window.Telegram.WebApp, and POSTs it
to /api/daily to claim XP. No manual initData capture needed.

Prerequisites
-------------
1. pip install playwright && playwright install chromium
2. Your phone number, 2FA password (if enabled)

Usage
-----
# First run (interactive — you provide the SMS code):
python claim-xp-playwright.py --interactive

# Subsequent runs (reuses browser storage state if saved):
python claim-xp-playwright.py

GitHub Actions
--------------
See .github/workflows/daily-claim.yml — the Playwright job runs headless.
NOTE: Telegram Web login requires an SMS code which GitHub Actions cannot
receive. For fully unattended CI runs, either:
  • Run this script on a persistent machine (Windows Task Scheduler, cron, etc.)
  • Or, if you own the bot @pzpsentrybot, get its Bot Token from @BotFather
    and use the initData-generation approach (no browser needed).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("xp-claimer")

STATE_FILE = "telegram_web_state.json"
TELEGRAM_WEB_URL = "https://web.telegram.org/k/"
MINI_APP_BOT = "pzpsentrybot"
CLAIM_URL = "https://app.piratezparty.com/api/daily"

PHONE = os.environ.get("TG_PHONE", "")
PASSWORD = os.environ.get("TG_PASSWORD", "")


async def save_storage(context: BrowserContext) -> None:
    """Persist browser cookies/localStorage so we don't re-log in every run."""
    state = await context.storage_state()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)
    log.info("Saved browser session state to %s", STATE_FILE)


async def load_storage(context: BrowserContext) -> bool:
    """Restore previously saved browser session state."""
    if not os.path.exists(STATE_FILE):
        return False
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    await context.add_cookies(state.get("cookies", []))
    # localStorage is restored per-origin via page.evaluate after navigation
    log.info("Restored browser session state from %s", STATE_FILE)
    return True


async def restore_local_storage(page: Page, state: dict) -> None:
    """Replay localStorage entries for the Telegram origin."""
    origins = state.get("origins", [])
    for origin in origins:
        if "web.telegram.org" in origin.get("origin", ""):
            for item in origin.get("localStorage", []):
                await page.evaluate(
                    """([k, v]) => localStorage.setItem(k, v)""",
                    [item["name"], item["value"]],
                )
            break


async def login_to_telegram_web(page: Page, interactive: bool) -> bool:
    """Log into Telegram Web. Returns True when logged in."""
    await page.goto(TELEGRAM_WEB_URL, wait_until="networkidle")

    # Check if already logged in (chat list visible)
    try:
        await page.wait_for_selector(".chatlist, [class*='chatlist']", timeout=5000)
        log.info("Already logged into Telegram Web.")
        return True
    except Exception:
        pass

    # Click "Log in by phone number" or similar
    log.info("Starting Telegram Web login...")

    # Try to find the phone input
    try:
        phone_input = page.locator('input[type="tel"], input[name="phone"], input[placeholder*="phone" i]').first
        await phone_input.wait_for(timeout=5000)
    except Exception:
        log.error("Could not find phone input on Telegram Web login page.")
        return False

    await phone_input.fill(PHONE)
    log.info("Filled phone number: %s", PHONE)

    # Click next / continue
    next_btn = page.locator('button:has-text("Next"), button:has-text("Continue"), button[type="submit"]').first
    await next_btn.click()

    # Wait for code input
    try:
        code_input = page.locator('input[type="tel"], input[placeholder*="code" i], input[inputmode="numeric"]').first
        await code_input.wait_for(timeout=10000)
    except Exception:
        log.error("Code input not found after sending phone.")
        return False

    if interactive:
        code = input("Enter the Telegram login code sent to your phone: ").strip()
    else:
        code = os.environ.get("TG_CODE", "")
        if not code:
            log.error("TG_CODE not set and not interactive — cannot complete login.")
            return False

    await code_input.fill(code)
    log.info("Entered login code.")

    # Click next
    next_btn2 = page.locator('button:has-text("Next"), button:has-text("Continue"), button[type="submit"]').first
    await next_btn2.click()

    # Handle 2FA if needed
    try:
        pwd_input = page.locator('input[type="password"], input[placeholder*="password" i]').first
        await pwd_input.wait_for(timeout=5000)
        if interactive:
            pwd = input("Enter your 2FA password: ").strip()
        else:
            pwd = PASSWORD
        if not pwd:
            log.error("2FA password required but not provided.")
            return False
        await pwd_input.fill(pwd)
        await page.locator('button:has-text("Next"), button:has-text("Continue"), button[type="submit"]').first.click()
        log.info("Submitted 2FA password.")
    except Exception:
        log.info("No 2FA prompt — proceeding.")

    # Wait for chat list to appear (logged in)
    try:
        await page.wait_for_selector(".chatlist, [class*='chatlist']", timeout=15000)
        log.info("Successfully logged into Telegram Web.")
        return True
    except Exception:
        log.error("Login did not complete — chat list not found.")
        return False


async def open_mini_app(page: Page) -> bool:
    """Open the PZP Sentry mini app in Telegram Web."""
    log.info("Looking for bot @%s ...", MINI_APP_BOT)

    # Search for the bot
    try:
        search = page.locator('input[placeholder*="search" i], input[placeholder*="Search" i]').first
        await search.wait_for(timeout=5000)
        await search.fill(f"@{MINI_APP_BOT}")
        await search.press("Enter")
    except Exception:
        log.error("Could not search for bot.")
        return False

    # Wait for search results / bot chat
    try:
        await page.wait_for_timeout(3000)
        # Click on the bot result / open chat
        bot_link = page.locator(f'text=@{MINI_APP_BOT}, text={MINI_APP_BOT}').first
        await bot_link.click()
        await page.wait_for_timeout(3000)
    except Exception:
        log.error("Could not open bot chat.")
        return False

    log.info("Opened @%s chat.", MINI_APP_BOT)
    return True


async def extract_init_data(page: Page) -> Optional[str]:
    """Extract initData from Telegram.WebApp in the mini app context."""
    # Try to evaluate initData directly
    try:
        init_data = await page.evaluate("window.Telegram.WebApp?.initData || null")
        if init_data:
            log.info("Extracted initData from window.Telegram.WebApp")
            return init_data
    except Exception:
        pass

    # Try localStorage
    try:
        init_data = await page.evaluate("localStorage.getItem('web_app_init_data') || localStorage.getItem('tgWebAppData') || null")
        if init_data:
            log.info("Extracted initData from localStorage")
            return init_data
    except Exception:
        pass

    log.warning("Could not extract initData from page.")
    return None


async def claim_xp(init_data: str) -> bool:
    """POST initData to the daily claim endpoint."""
    import aiohttp

    headers = {
        "Content-Type": "application/json",
        "Origin": "https://app.piratezparty.com",
        "Referer": "https://app.piratezparty.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
        "X-Telegram-Init-Data": init_data,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(CLAIM_URL, headers=headers, json={}) as resp:
            text = await resp.text()
            if resp.status == 200:
                log.info("XP claim successful: %s", text[:200])
                return True
            else:
                log.error("Claim failed with status %s: %s", resp.status, text[:200])
                return False


async def main() -> int:
    interactive = "--interactive" in sys.argv

    if not PHONE:
        log.error("TG_PHONE environment variable is required.")
        return 2

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=not interactive)
        context: BrowserContext = await browser.new_context()

        # Try restoring session
        state_loaded = await load_storage(context)

        page: Page = await context.new_page()

        # If we have saved state, restore localStorage after navigation
        if state_loaded:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            # Navigate first, then restore localStorage
            await page.goto(TELEGRAM_WEB_URL, wait_until="networkidle")
            await restore_local_storage(page, state)
            await page.reload(wait_until="networkidle")

            # Check if still logged in
            try:
                await page.wait_for_selector(".chatlist, [class*='chatlist']", timeout=5000)
                log.info("Session restored — already logged in.")
            except Exception:
                log.info("Session expired — re-logging in.")
                if not await login_to_telegram_web(page, interactive):
                    await browser.close()
                    return 2
        else:
            if not await login_to_telegram_web(page, interactive):
                await browser.close()
                return 2

        # Save session state for next run
        await save_storage(context)

        # Open mini app
        if not await open_mini_app(page):
            await browser.close()
            return 2

        # Extract initData
        init_data = await extract_init_data(page)
        if not init_data:
            log.error("Could not extract initData — mini app may not have loaded properly.")
            await browser.close()
            return 2

        log.info("initData extracted (length %d)", len(init_data))

        # Claim XP
        if await claim_xp(init_data):
            await browser.close()
            return 0
        else:
            await browser.close()
            return 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        raise SystemExit(130)
