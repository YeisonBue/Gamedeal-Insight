import httpx
import asyncio
import logging
from src.db.database import SessionLocal
from src.models.models import Game, PriceSnapshot

# Standard logger configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ITADCollector:
    def __init__(self, api_key: str = "YOUR_API_KEY"):
        self.api_key = api_key
        self.base_url = "https://api.isthereanydeal.com/games/search/v1"

    async def fetch_game_data(self, title: str):
        """
        Queries IsThereAnyDeal API for game details and pricing.
        Currently using mock data for development.
        """
        async with httpx.AsyncClient() as client:
            try:
                # Rate limit safety
                await asyncio.sleep(1) 
                
                # Mock response structure
                return {
                    "data": [{
                        "id": "018d6a0c-a281-71bc-a7e8-b7d8b5f6a19f",
                        "title": title,
                        "type": "game",
                        "price": {
                            "current": 29.99,
                            "regular": 59.99,
                            "cut": 50.0
                        }
                    }]
                }
            except Exception as e:
                logger.error(f"API connection error: {e}")
                return None

    def save_to_db(self, game_data: dict):
        """
        Handles persistence for Game metadata and PriceSnapshot records.
        """
        if not game_data or not game_data.get("data"):
            return

        payload = game_data["data"][0]
        db = SessionLocal()
        
        try:
            # Upsert Game entity
            game = db.query(Game).filter(Game.nombre == payload["title"]).first()
            
            if not game:
                game = Game(
                    nombre=payload["title"],
                    slug=payload["title"].lower().replace(" ", "-"),
                    genero="RPG", 
                    desarrollador="CD Projekt Red", 
                    publisher="CD Projekt", 
                    plataforma="PC"
                )
                db.add(game)
                db.commit()
                db.refresh(game)
                logger.info(f"New game created: {game.id}")
            else:
                logger.info(f"Game exists: {game.id}. Proceeding with snapshot.")

            # Record price snapshot
            pricing = payload.get("price", {})
            snapshot = PriceSnapshot(
                game_id=game.id,
                source_id=1,  # ITAD Source ID
                precio_actual=pricing.get("current", 0.0),
                precio_base=pricing.get("regular", 0.0),
                descuento_porcentaje=pricing.get("cut", 0.0),
                moneda="USD"
            )
            
            db.add(snapshot)
            db.commit()
            logger.info(f"Snapshot committed: {snapshot.precio_actual} USD")
            
        except Exception as e:
            db.rollback()
            logger.error(f"Database transaction failed: {e}")
        finally:
            db.close()

if __name__ == "__main__":
    collector = ITADCollector()
    data = asyncio.run(collector.fetch_game_data("Cyberpunk 2077"))
    if data:
        collector.save_to_db(data)