import time
import schedule
import asyncio
import logging
from src.collectors.steam_collector import SteamCollector

# Logging configuration for persistent monitoring
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def job_steam_sync():
    """
    Scheduled task to synchronize Steam market data.
    Iterates through target AppIDs and persists snapshots.
    """
    logger.info("Scheduler initiated: Starting Steam data synchronization.")
    
    collector = SteamCollector()
    target_app_ids = [
        "1091500", "1245620", "271590", 
        "1086940", "1174180", "379720"
    ]
    
    for app_id in target_app_ids:
        try:
            # API Rate-limiting compliance
            time.sleep(2.0) 
            
            # Executing asynchronous fetch within synchronous schedule context
            raw_data = asyncio.run(collector.fetch_app_data(app_id))
            collector.save_to_db(raw_data)
        except Exception as e:
            logger.error(f"Sync failed for AppID {app_id}: {e}")
        
    logger.info("Batch synchronization cycle completed.")

# Schedule configuration
# Set to 1-minute intervals for testing; production should use daily windows (e.g., .day.at("02:00"))
schedule.every(1).minutes.do(job_steam_sync)

if __name__ == "__main__":
    logger.info("GameDeal Insight Scheduler active. Use Ctrl+C to terminate.")
    
    # Initial execution on startup
    job_steam_sync()
    
    # Main execution loop
    while True:
        schedule.run_pending()
        time.sleep(1)