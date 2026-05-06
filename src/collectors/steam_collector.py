import httpx
import asyncio
import logging
from src.db.database import SessionLocal
from src.models.models import Game, PriceSnapshot, ReputationSnapshot

# Setup professional logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SteamCollector:
    def __init__(self):
        self.base_url = "https://store.steampowered.com/api/appdetails"
        self.reviews_url = "https://store.steampowered.com/appreviews"

    async def fetch_app_data(self, app_id: str):
        """
        Fetches game details and user reviews from the Steam Web API.
        """
        async with httpx.AsyncClient() as client:
            try:
                # Request app metadata
                app_res = await client.get(f"{self.base_url}?appids={app_id}&cc=us")
                app_res.raise_for_status()
                payload = app_res.json()

                if not payload.get(app_id, {}).get("success"):
                    logger.warning(f"Steam API returned success=false for AppID: {app_id}")
                    return None

                game_data = payload[app_id]["data"]

                # Request user review summary
                review_res = await client.get(f"{self.reviews_url}/{app_id}?json=1&language=all")
                review_res.raise_for_status()
                review_payload = review_res.json()
                
                game_data["reputation_summary"] = review_payload.get("query_summary", {})
                return game_data

            except Exception as e:
                logger.error(f"Network error for AppID {app_id}: {e}")
                return None

    def save_to_db(self, app_data: dict):
        """
        Persists game metadata, pricing, and reputation snapshots to the database.
        """
        if not app_data:
            return

        session = SessionLocal()
        try:
            # 1. Manage Game Record
            name = app_data.get("name", "Unknown")
            game = session.query(Game).filter(Game.nombre == name).first()
            
            if not game:
                game = Game(
                    nombre=name,
                    slug=name.lower().replace(" ", "-").replace(":", ""),
                    genero="Various",
                    desarrollador=app_data.get("developers", ["Unknown"])[0],
                    publisher=app_data.get("publishers", ["Unknown"])[0],
                    plataforma="PC"
                )
                session.add(game)
                session.commit()
                session.refresh(game)
            
            # 2. Process Price Overviews
            if "price_overview" in app_data:
                pricing = app_data["price_overview"]
                snapshot = PriceSnapshot(
                    game_id=game.id,
                    source_id=1, # Steam Source
                    precio_actual=pricing.get("final", 0) / 100.0,
                    precio_base=pricing.get("initial", 0) / 100.0,
                    descuento_porcentaje=float(pricing.get("discount_percent", 0)),
                    moneda=pricing.get("currency", "USD")
                )
                session.add(snapshot)

            # 3. Process Reputation Metrics
            if "reputation_summary" in app_data:
                rep = app_data["reputation_summary"]
                total = rep.get("total_reviews", 0)
                positive = rep.get("total_positive", 0)
                score = (positive / total * 100) if total > 0 else 0

                reputation = ReputationSnapshot(
                    game_id=game.id,
                    source_id=1,
                    score_promedio=score,
                    cantidad_reseñas=total,
                    score_tipo="Steam Positive %"
                )
                session.add(reputation)

            session.commit()
            logger.info(f"Synchronized AppID data for: {name}")

        except Exception as e:
            session.rollback()
            logger.error(f"DB Transaction failed: {e}")
        finally:
            session.close()

async def main():
    collector = SteamCollector()
    app_ids = ["1091500", "1245620", "271590", "1086940", "1174180", "379720"]
    
    logger.info("Starting batch data extraction...")
    for app_id in app_ids:
        # Throttle requests to respect Steam's rate limits
        await asyncio.sleep(1.5)
        raw_data = await collector.fetch_app_data(app_id)
        collector.save_to_db(raw_data)

if __name__ == "__main__":
    asyncio.run(main())