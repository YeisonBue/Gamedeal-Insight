import asyncio
import datetime
import logging
import re

import httpx
from sqlalchemy import or_

from src.db.database import SessionLocal
from src.models.models import DiscoveredAppId, Game, PriceSnapshot, ReputationSnapshot

# Static seed list kept as fallback for first run before discovery completes
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


def _price_changed(session, game_id: int, new_price: float, new_discount: float) -> bool:
    """Return True only when Steam price or discount changed since the last snapshot."""
    last = (
        session.query(PriceSnapshot)
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.platform == "steam",
        )
        .order_by(PriceSnapshot.fecha_captura.desc())
        .first()
    )
    if not last:
        return True
    price_delta = abs((last.precio_actual or 0) - new_price)
    discount_delta = abs((last.descuento_porcentaje or 0) - new_discount)
    return price_delta > 0.01 or discount_delta > 0.5


def get_pending_app_ids() -> list[str]:
    """Return App IDs that have never been processed or are due for a 24-hour refresh."""
    db = SessionLocal()
    try:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
        rows = (
            db.query(DiscoveredAppId)
            .filter(
                or_(
                    DiscoveredAppId.processed == False,  # noqa: E712
                    DiscoveredAppId.last_check < cutoff,
                )
            )
            .all()
        )
        return [r.app_id for r in rows]
    finally:
        db.close()


def seed_static_app_ids():
    """Persist TARGET_APP_IDS to discovered_app_ids if not already there."""
    db = SessionLocal()
    try:
        existing = {r.app_id for r in db.query(DiscoveredAppId.app_id).all()}
        new_rows = [
            DiscoveredAppId(app_id=aid)
            for aid in TARGET_APP_IDS
            if aid not in existing
        ]
        if new_rows:
            db.add_all(new_rows)
            db.commit()
            logger.info(f"Seeded {len(new_rows)} static App IDs into discovery table.")
    except Exception as e:
        db.rollback()
        logger.error(f"Static seed failed: {e}")
    finally:
        db.close()


def register_discovered_ids(app_ids: list[str]):
    """Upsert a batch of discovered App IDs without resetting already-processed ones."""
    if not app_ids:
        return
    db = SessionLocal()
    try:
        existing = {r.app_id for r in db.query(DiscoveredAppId.app_id).all()}
        new_rows = [
            DiscoveredAppId(app_id=aid)
            for aid in app_ids
            if aid not in existing
        ]
        if new_rows:
            db.add_all(new_rows)
            db.commit()
            logger.info(f"Registered {len(new_rows)} newly discovered App IDs.")
    except Exception as e:
        db.rollback()
        logger.error(f"Discovery registration failed: {e}")
    finally:
        db.close()


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
        """Persist game metadata and snapshot only if price/data changed."""
        if not app_data:
            self._mark_checked(app_id)
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
            short_desc = app_data.get("short_description") or ""

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
            game.descripcion = short_desc or game.descripcion
            game.last_scraped_at = datetime.datetime.now(datetime.timezone.utc)

            session.flush()

            pricing = app_data.get("price_overview")
            if pricing:
                new_price = pricing.get("final", 0) / 100.0
                new_base = pricing.get("initial", 0) / 100.0
                new_discount = float(pricing.get("discount_percent", 0))

                if _price_changed(session, game.id, new_price, new_discount):
                    session.add(
                        PriceSnapshot(
                            game_id=game.id,
                            source_id=1,
                            platform="steam",
                            precio_actual=new_price,
                            precio_base=new_base,
                            descuento_porcentaje=new_discount,
                            moneda=pricing.get("currency", "USD"),
                        )
                    )
                    logger.info(f"Price updated for {name}: ${new_price} (-{new_discount}%)")
                else:
                    logger.debug(f"Price unchanged for {name}, skipping snapshot.")

            elif app_data.get("is_free"):
                if _price_changed(session, game.id, 0.0, 0.0):
                    session.add(
                        PriceSnapshot(
                            game_id=game.id,
                            source_id=1,
                            platform="steam",
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

        self._mark_checked(app_id)

    def _mark_checked(self, app_id: str):
        """Update DiscoveredAppId to mark this ID as processed and set last_check."""
        if not app_id:
            return
        db = SessionLocal()
        try:
            row = db.query(DiscoveredAppId).filter_by(app_id=app_id).first()
            if row:
                row.processed = True
                row.last_check = datetime.datetime.now(datetime.timezone.utc)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


async def main():
    collector = SteamCollector()
    logger.info("Starting batch data extraction...")
    for app_id in TARGET_APP_IDS:
        await asyncio.sleep(1.2)
        raw_data = await collector.fetch_app_data(app_id)
        collector.save_to_db(raw_data, app_id)


if __name__ == "__main__":
    asyncio.run(main())
