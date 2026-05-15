import asyncio
import logging
import threading
import time

import schedule

from src.collectors.platform_collector import (
    bulk_store_platform_prices,
    fetch_all_deals_bulk,
)
from src.collectors.steam_collector import (
    SteamCollector,
    get_pending_app_ids,
    register_discovered_ids,
    seed_static_app_ids,
)
from src.db.database import SessionLocal
from src.services.currency_service import fetch_and_store_rates, rates_are_stale

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# App ID Discovery (background thread, runs at startup)
# ──────────────────────────────────────────────────────────────

def job_discover_app_ids():
    """
    Scrapes Steam Search to find new App IDs and registers them.
    Runs in a separate thread so it does not block startup.
    """
    try:
        from scraping.steam_scraper import discover_app_ids

        logger.info("Discovery: scraping Steam for new App IDs…")
        ids = discover_app_ids(mode="topsellers", limit=150)
        register_discovered_ids(ids)

        logger.info("Discovery: scraping specials / deals…")
        ids_specials = discover_app_ids(mode="specials", limit=100)
        register_discovered_ids(ids_specials)

        logger.info("Discovery: completed background App ID scan.")
    except Exception as e:
        logger.error(f"App ID discovery failed: {e}")


# ──────────────────────────────────────────────────────────────
# Steam price sync (runs every 6 hours, smart update)
# ──────────────────────────────────────────────────────────────

def job_steam_sync():
    """Synchronizes Steam price/metadata for all pending or stale App IDs."""
    logger.info("Scheduler: starting Steam data synchronization.")
    collector = SteamCollector()
    app_ids = get_pending_app_ids()

    if not app_ids:
        logger.info("No App IDs pending refresh.")
        return

    logger.info(f"Syncing {len(app_ids)} App IDs from discovery table…")
    for app_id in app_ids:
        try:
            time.sleep(1.2)
            raw_data = asyncio.run(collector.fetch_app_data(app_id))
            collector.save_to_db(raw_data, app_id)
        except Exception as e:
            logger.error(f"Sync failed for AppID {app_id}: {e}")

    logger.info("Steam sync cycle completed.")


# ──────────────────────────────────────────────────────────────
# Platform price comparison (runs every 12 hours)
# ──────────────────────────────────────────────────────────────

def job_platform_prices():
    """
    Fetches multi-platform prices via CheapShark bulk pagination and stores them.
    Uses ~30 requests total instead of one per game.
    If CheapShark is rate-limited (429 block), waits 70 min and retries once.
    """
    logger.info("Scheduler: bulk-fetching platform prices from CheapShark…")
    for attempt in (1, 2):
        try:
            index = fetch_all_deals_bulk(max_pages=30)
            if not index:
                raise RuntimeError("Empty index — likely still rate-limited")
            stored = bulk_store_platform_prices(index)
            logger.info(f"Platform prices sync complete — {stored} new snapshots.")
            return
        except Exception as e:
            if attempt == 1:
                logger.warning(
                    f"Platform prices attempt 1 failed ({e}). "
                    "CheapShark may be rate-limiting. Retrying in 70 min…"
                )
                time.sleep(70 * 60)  # wait 70 minutes in background thread
            else:
                logger.error(f"Platform price job failed after retry: {e}")


# ──────────────────────────────────────────────────────────────
# Currency rates (runs every 12 hours)
# ──────────────────────────────────────────────────────────────

def job_currency_rates():
    """Refresh exchange rates from open.er-api.com."""
    if rates_are_stale(max_age_hours=12):
        logger.info("Scheduler: refreshing currency exchange rates…")
        fetch_and_store_rates()


# ──────────────────────────────────────────────────────────────
# Schedule configuration
# ──────────────────────────────────────────────────────────────

schedule.every(6).hours.do(job_steam_sync)
schedule.every(12).hours.do(job_platform_prices)
schedule.every(12).hours.do(job_currency_rates)


def run_scheduler():
    """
    Entry point called from main.py lifespan.

    Startup sequence:
      1. Seed static App IDs into discovery table.
      2. Fetch currency rates (or use fallback).
      3. Run first Steam sync immediately.
      4. Launch background discovery thread (non-blocking).
      5. After discovery finishes, schedule will pick up new IDs on next cycle.
    """
    # 1. Seed static IDs so first sync has work to do
    seed_static_app_ids()

    # 2. Currency rates
    job_currency_rates()

    # 3. Immediate first Steam sync
    job_steam_sync()

    # 4. Background App ID discovery (does NOT block the sync loop)
    discovery_thread = threading.Thread(
        target=job_discover_app_ids, daemon=True, name="AppIDDiscovery"
    )
    discovery_thread.start()

    # 5. Platform prices immediately after first Steam sync (background thread)
    platform_thread = threading.Thread(
        target=job_platform_prices, daemon=True, name="PlatformPricesInit"
    )
    platform_thread.start()

    # 6. Scheduler loop
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    logger.info("GameDeal Insight Scheduler active. Use Ctrl+C to terminate.")
    run_scheduler()
