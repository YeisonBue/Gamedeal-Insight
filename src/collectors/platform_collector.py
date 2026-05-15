"""
src/collectors/platform_collector.py
──────────────────────────────────────
Fetches game prices from multiple stores using the free CheapShark API.
https://apidocs.cheapshark.com/

Strategy: bulk pagination — fetches deals in pages, matches to our DB by steamAppID.
This uses ~25 requests total instead of one per game, staying within rate limits.
No API key required.
"""

import logging
import time

import httpx

from src.db.database import SessionLocal
from src.models.models import Game, PriceSnapshot

logger = logging.getLogger(__name__)

CHEAPSHARK_BASE = "https://www.cheapshark.com/api/1.0"

# CheapShark store IDs → display names
STORE_MAP: dict[str, str] = {
    "1":  "Steam",
    "7":  "GOG",
    "11": "Humble Store",
    "3":  "Green Man Gaming",
    "13": "Fanatical",
    "25": "Epic Games",
    "2":  "GamersGate",
    "23": "GameBillet",
    "31": "IndieGala",
}

_HEADERS = {
    "User-Agent": "GameDeal-Insight/1.0 (price-comparison-tool; open-source project)",
    "Accept": "application/json",
}


def _get_with_retry(
    client: httpx.Client, url: str, params: dict, max_retries: int = 4
) -> httpx.Response:
    """GET with exponential backoff on 429 / 5xx."""
    for attempt in range(max_retries):
        res = client.get(url, params=params, timeout=20)
        if res.status_code == 429:
            wait = 30 * (attempt + 1)
            logger.warning(
                f"CheapShark rate-limited — waiting {wait}s "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)
            continue
        res.raise_for_status()
        return res
    # All retries exhausted — raise so callers can detect and back off
    res.raise_for_status()
    return res


# ──────────────────────────────────────────────────────────────
# Bulk fetch (primary strategy)
# ──────────────────────────────────────────────────────────────

def fetch_all_deals_bulk(max_pages: int = 30) -> dict[str, dict[str, dict]]:
    """
    Paginate through CheapShark /deals and build an index:
      { steam_app_id: { store_name: {price, base_price, discount} } }

    Uses ~30 requests for ~1 800 deals — far cheaper than per-game lookups.
    Runs multiple sort passes to maximise coverage.
    """
    index: dict[str, dict[str, dict]] = {}  # app_id -> store_name -> best deal

    sort_passes = [
        {"sortBy": "DealRating", "desc": 1},
        {"sortBy": "Savings",    "desc": 1},
        {"sortBy": "Price",      "desc": 0},
    ]

    with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        for sort_params in sort_passes:
            for page in range(max_pages):
                try:
                    res = _get_with_retry(
                        client,
                        f"{CHEAPSHARK_BASE}/deals",
                        {"pageSize": 60, "pageNumber": page, **sort_params},
                    )
                    deals = res.json()
                except Exception as e:
                    logger.warning(f"Bulk page {page} ({sort_params['sortBy']}): {e}")
                    break

                if not isinstance(deals, list) or not deals:
                    break

                for deal in deals:
                    app_id = str(deal.get("steamAppID") or "").strip()
                    if not app_id:
                        continue
                    store_id = str(deal.get("storeID", ""))
                    store_name = STORE_MAP.get(store_id, f"Store {store_id}")
                    try:
                        sale = round(float(deal.get("salePrice", 0)), 2)
                        normal = round(float(deal.get("normalPrice", sale)), 2)
                        savings = round(float(deal.get("savings", 0)), 1)
                        discount = savings if savings else round(
                            (1 - sale / normal) * 100 if normal > 0 else 0, 1
                        )
                    except (ValueError, TypeError):
                        continue

                    by_store = index.setdefault(app_id, {})
                    existing = by_store.get(store_name)
                    # Keep the cheapest price seen per store
                    if existing is None or sale < existing["price"]:
                        by_store[store_name] = {
                            "price": sale,
                            "base_price": normal,
                            "discount": discount,
                        }

                logger.info(
                    f"Bulk [{sort_params['sortBy']}] page {page + 1}: "
                    f"{len(index)} unique games indexed"
                )
                time.sleep(3)  # respectful delay: ~20 req/min

            logger.info(f"Pass '{sort_params['sortBy']}' done — {len(index)} games indexed")
            time.sleep(5)

    return index


def bulk_store_platform_prices(index: dict[str, dict[str, dict]]) -> int:
    """
    Match the bulk deal index to our DB games and persist changed snapshots.
    Returns the number of snapshots written.
    """
    db = SessionLocal()
    stored = 0
    try:
        games = db.query(Game).filter(Game.steam_app_id.isnot(None)).all()
        for game in games:
            app_deals = index.get(str(game.steam_app_id), {})
            for store_name, deal in app_deals.items():
                if _price_changed(db, game.id, store_name, deal["price"], deal["discount"]):
                    db.add(
                        PriceSnapshot(
                            game_id=game.id,
                            source_id=2,
                            platform=store_name,
                            precio_actual=deal["price"],
                            precio_base=deal["base_price"],
                            descuento_porcentaje=deal["discount"],
                            moneda="USD",
                        )
                    )
                    stored += 1
        db.commit()
        logger.info(f"Bulk platform sync: {stored} new snapshots for {len(games)} games")
    except Exception as e:
        db.rollback()
        logger.error(f"Bulk store error: {e}")
    finally:
        db.close()
    return stored


# ──────────────────────────────────────────────────────────────
# Single-game fetch (used by API endpoint for on-demand lookup)
# ──────────────────────────────────────────────────────────────

def fetch_platform_prices(game_name: str, steam_app_id: str = "") -> list[dict]:
    """
    Return a list of current prices across stores for one game (on-demand).
    Uses /deals?steamAppID= for direct lookup when possible.
    Prices in USD.
    """
    results: list[dict] = []

    with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        if not steam_app_id:
            return results
        try:
            res = _get_with_retry(
                client,
                f"{CHEAPSHARK_BASE}/deals",
                {"steamAppID": steam_app_id, "pageSize": 60},
            )
            deals = res.json()
            if not isinstance(deals, list):
                return results
        except Exception as e:
            logger.warning(f"On-demand fetch error [{game_name}]: {e}")
            return results

        seen: set[str] = set()
        for deal in deals:
            store_id = str(deal.get("storeID", ""))
            if store_id in seen:
                continue
            seen.add(store_id)
            store_name = STORE_MAP.get(store_id, f"Store {store_id}")
            try:
                sale = round(float(deal.get("salePrice", 0)), 2)
                normal = round(float(deal.get("normalPrice", sale)), 2)
                savings = round(float(deal.get("savings", 0)), 1)
                discount = savings or round(
                    (1 - sale / normal) * 100 if normal > 0 else 0, 1
                )
                results.append({
                    "platform": store_name,
                    "store_id": store_id,
                    "price": sale,
                    "base_price": normal,
                    "discount": discount,
                })
            except (ValueError, ZeroDivisionError):
                continue

    return sorted(results, key=lambda x: x["price"])


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _price_changed(db, game_id: int, platform: str, new_price: float, new_discount: float) -> bool:
    """Return True only when the price or discount actually changed."""
    last = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.game_id == game_id, PriceSnapshot.platform == platform)
        .order_by(PriceSnapshot.fecha_captura.desc())
        .first()
    )
    if not last:
        return True
    price_changed = abs((last.precio_actual or 0) - new_price) > 0.01
    discount_changed = abs((last.descuento_porcentaje or 0) - new_discount) > 0.5
    return price_changed or discount_changed


def collect_and_store_platform_prices(game_id: int, game_name: str, steam_app_id: str = ""):
    """Single-game collect + store (kept for scheduler compatibility)."""
    prices = fetch_platform_prices(game_name, steam_app_id)
    if not prices:
        return

    db = SessionLocal()
    try:
        for entry in prices:
            platform = entry["platform"]
            if _price_changed(db, game_id, platform, entry["price"], entry["discount"]):
                db.add(
                    PriceSnapshot(
                        game_id=game_id,
                        source_id=2,
                        platform=platform,
                        precio_actual=entry["price"],
                        precio_base=entry["base_price"],
                        descuento_porcentaje=entry["discount"],
                        moneda="USD",
                    )
                )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Platform price save error [{game_name}]: {e}")
    finally:
        db.close()


def get_platform_prices_for_game(game_id: int) -> list[dict]:
    """
    Return the latest price snapshot per platform for a game (from DB).
    Used by the API to build the comparison table without hitting CheapShark.
    """
    from sqlalchemy import func

    db = SessionLocal()
    try:
        subq = (
            db.query(
                PriceSnapshot.platform,
                func.max(PriceSnapshot.fecha_captura).label("latest"),
            )
            .filter(PriceSnapshot.game_id == game_id)
            .group_by(PriceSnapshot.platform)
            .subquery()
        )

        rows = (
            db.query(PriceSnapshot)
            .join(
                subq,
                (PriceSnapshot.platform == subq.c.platform)
                & (PriceSnapshot.fecha_captura == subq.c.latest),
            )
            .filter(PriceSnapshot.game_id == game_id)
            .all()
        )

        return [
            {
                "platform": r.platform,
                "price": round(float(r.precio_actual or 0), 2),
                "base_price": round(float(r.precio_base or 0), 2),
                "discount": round(float(r.descuento_porcentaje or 0), 1),
                "currency": r.moneda or "USD",
                "captured_at": r.fecha_captura.isoformat() if r.fecha_captura else None,
            }
            for r in sorted(rows, key=lambda x: (x.precio_actual or 9999))
        ]
    finally:
        db.close()

