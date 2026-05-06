import asyncio
import logging
import time

import schedule

from src.collectors.steam_collector import SteamCollector, TARGET_APP_IDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def job_steam_sync():
    """Scheduled task that synchronizes Steam data for the full catalog."""
    logger.info("Scheduler initiated: starting Steam data synchronization.")
    collector = SteamCollector()

    for app_id in TARGET_APP_IDS:
        try:
            time.sleep(1.2)
            raw_data = asyncio.run(collector.fetch_app_data(app_id))
            collector.save_to_db(raw_data, app_id)
        except Exception as e:
            logger.error(f"Sync failed for AppID {app_id}: {e}")

    logger.info("Batch synchronization cycle completed.")


schedule.every(6).hours.do(job_steam_sync)


def run_scheduler():
    job_steam_sync()
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    logger.info("GameDeal Insight Scheduler active. Use Ctrl+C to terminate.")
    run_scheduler()
