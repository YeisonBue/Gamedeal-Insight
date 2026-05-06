import asyncio
import datetime
import logging
import re

import httpx
from sqlalchemy import or_

from src.db.database import SessionLocal
from src.models.models import Game, PriceSnapshot, ReputationSnapshot

TARGET_APP_IDS = [
    # Souls / Action RPG
    "1245620", "814380", "374320", "570940", "230050",
    # Cyberpunk / Sci-Fi RPG
    "1091500", "524220", "1138590", "1845910",
    # CRPG / RPG
    "1086940", "435150", "292030", "1145360", "1440510", "1328670", "1203220",
    # Open World
    "271590", "1174180", "275850", "1506830", "990080", "1517290",
    # FPS / Action
    "379720", "2050650", "1237970", "1151340", "433850", "2358720", "1091470", "752590",
    # Monster Hunter
    "582010", "1446780",
    # Survival / Sandbox
    "252490", "105600", "413150", "548430", "427520", "1366540", "242760", "1326470", "736220", "848450",
    # Horror
    "239140", "534380", "952060", "606150", "883710", "1196590", "381210", "739630", "1888930",
    # Indie / Roguelikes
    "367520", "504230", "268910", "1817190", "1113560", "1128640", "387290", "646570", "632360", "1623730", "1341820", "362890", "1624320",
    # Co-op
    "945360", "1426210", "1966720",
    # Strategy
    "394360", "281990", "255710", "219740", "322330", "289070", "108600", "346110", "644360",
    # Sony Ports
    "2280650", "1817070", "1938090", "1151640", "2322010", "1282100",
    # More
    "1580730", "1985790", "1516740", "1517550",
    # Valve Classics
    "620", "400", "220", "550",
    # Competitive / Live Service
    "730", "570", "440", "218620", "359550", "578080", "1172470", "1085660", "236390",
    # Sim / Strategy / Survival
    "960090", "294100", "526870", "892970", "1158310", "236850", "251570", "262060", "1248130",
    # Xbox / Capcom / Action
    "1551360", "1240440", "976730", "1172620", "601150", "418370", "268500", "1144200",
    # RPG/JRPG
    "834530",
    # Adventure
    "1063730",
    # More Action
    "489830", "377160", "22380",
    # Other
    "1448020",
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s-]", "", value.lower())
    normalized = re.sub(r"[\s_]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or "game"


def parse_release_date(app_data: dict):
    raw_date = (app_data.get("release_date") or {}).get("date")
    if not raw_date:
        return None

    for fmt in ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw_date, fmt)
        except ValueError:
            continue
    return None


class SteamCollector:
    def __init__(self):
        self.base_url = "https://store.steampowered.com/api/appdetails"
        self.reviews_url = "https://store.steampowered.com/appreviews"
        self.client_config = {
            "timeout": httpx.Timeout(30.0),
            "headers": {
                "User-Agent": "GameDeal Insight/2.0",
                "Accept": "application/json",
            },
        }

    async def fetch_app_data(self, app_id: str):
        """Fetch game metadata and review aggregates from the Steam Web API."""
        async with httpx.AsyncClient(**self.client_config) as client:
            try:
                app_res = await client.get(
                    self.base_url,
                    params={"appids": app_id, "cc": "us", "l": "english"},
                )
                app_res.raise_for_status()
                payload = app_res.json()

                if not payload.get(app_id, {}).get("success"):
                    logger.warning(f"Steam API returned success=false for AppID: {app_id}")
                    return None

                game_data = payload[app_id]["data"]

                review_res = await client.get(
                    f"{self.reviews_url}/{app_id}",
                    params={
                        "json": 1,
                        "language": "all",
                        "filter": "summary",
                        "purchase_type": "all",
                    },
                )
                review_res.raise_for_status()
                review_payload = review_res.json()

                game_data["reputation_summary"] = review_payload.get("query_summary", {})
                return game_data
            except Exception as e:
                logger.error(f"Network error for AppID {app_id}: {e}")
                return None

    def save_to_db(self, app_data: dict, app_id: str = ""):
        """Persist game metadata plus latest price and reputation snapshots."""
        if not app_data:
            return

        session = SessionLocal()
        try:
            name = app_data.get("name", "Unknown")
            header_image = (
                f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
                if app_id
                else None
            )
            genre = app_data.get("genres", [{}])[0].get("description", "Action")
            developers = app_data.get("developers") or ["Unknown"]
            publishers = app_data.get("publishers") or ["Unknown"]

            game = session.query(Game).filter(
                or_(Game.steam_app_id == app_id, Game.nombre == name)
            ).first()

            if not game:
                game = Game()
                session.add(game)

            game.nombre = name
            game.slug = slugify(name)
            game.genero = genre
            game.desarrollador = developers[0]
            game.publisher = publishers[0]
            game.fecha_lanzamiento = parse_release_date(app_data)
            game.plataforma = "PC"
            game.steam_app_id = app_id or game.steam_app_id
            game.imagen_url = header_image or game.imagen_url

            session.flush()

            pricing = app_data.get("price_overview")
            if pricing:
                session.add(
                    PriceSnapshot(
                        game_id=game.id,
                        source_id=1,
                        precio_actual=pricing.get("final", 0) / 100.0,
                        precio_base=pricing.get("initial", 0) / 100.0,
                        descuento_porcentaje=float(pricing.get("discount_percent", 0)),
                        moneda=pricing.get("currency", "USD"),
                    )
                )
            elif app_data.get("is_free"):
                session.add(
                    PriceSnapshot(
                        game_id=game.id,
                        source_id=1,
                        precio_actual=0.0,
                        precio_base=0.0,
                        descuento_porcentaje=0.0,
                        moneda="USD",
                    )
                )

            rep = app_data.get("reputation_summary") or {}
            total = rep.get("total_reviews", 0)
            positive = rep.get("total_positive", 0)
            score = (positive / total * 100) if total > 0 else 0

            session.add(
                ReputationSnapshot(
                    game_id=game.id,
                    source_id=1,
                    score_promedio=score,
                    cantidad_reseñas=total,
                    score_tipo="Steam Positive %",
                )
            )

            session.commit()
            logger.info(f"Synchronized AppID data for: {name}")
        except Exception as e:
            session.rollback()
            logger.error(f"DB transaction failed for AppID {app_id}: {e}")
        finally:
            session.close()


async def main():
    collector = SteamCollector()
    logger.info("Starting batch data extraction...")
    for app_id in TARGET_APP_IDS:
        await asyncio.sleep(1.2)
        raw_data = await collector.fetch_app_data(app_id)
        collector.save_to_db(raw_data, app_id)


if __name__ == "__main__":
    asyncio.run(main())
