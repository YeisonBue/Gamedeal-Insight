from contextlib import asynccontextmanager
from pathlib import Path
import threading

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

import src.scheduler as scheduler_module
from src.collectors.platform_collector import get_platform_prices_for_game
from src.db.database import SessionLocal
from src.models.models import Game, PriceSnapshot, ReputationSnapshot
from src.services.currency_service import (
    SUPPORTED_CURRENCIES,
    convert,
    get_rates,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=scheduler_module.run_scheduler, daemon=True)
    t.start()
    yield


app = FastAPI(title="GameDeal Insight API", version="2.0.0", lifespan=lifespan)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def read_static_file(filename: str) -> HTMLResponse:
    target = STATIC_DIR / filename
    if not target.exists():
        return HTMLResponse(content="Static page not found.", status_code=404)
    return HTMLResponse(target.read_text(encoding="utf-8"))


def _fmt_money(value: float | None, currency: str) -> str:
    amount = float(value or 0)
    if currency == "COP":
        return f"COP {amount:,.0f}"
    if currency in ("JPY", "CLP"):
        return f"{currency} {amount:,.0f}"
    return f"{currency} {amount:,.2f}"


def money(value: float | None, currency: str | None, target_currency: str = "USD") -> str:
    amount_usd = float(value or 0)
    converted = convert(amount_usd, target_currency)
    return _fmt_money(converted, target_currency.upper())


def serialize_game(game: Game) -> dict:
    return {
        "id": game.id,
        "nombre": game.nombre,
        "slug": game.slug,
        "genero": game.genero,
        "desarrollador": game.desarrollador,
        "publisher": game.publisher,
        "fecha_lanzamiento": game.fecha_lanzamiento.isoformat() if game.fecha_lanzamiento else None,
        "plataforma": game.plataforma,
        "steam_app_id": game.steam_app_id,
        "imagen_url": game.imagen_url,
        "descripcion": game.descripcion,
    }


def get_latest_price(db: Session, game_id: int, platform: str = "steam"):
    return (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.game_id == game_id, PriceSnapshot.platform == platform)
        .order_by(PriceSnapshot.fecha_captura.desc())
        .first()
    )


def get_latest_rep(db: Session, game_id: int):
    return (
        db.query(ReputationSnapshot)
        .filter(ReputationSnapshot.game_id == game_id)
        .order_by(ReputationSnapshot.fecha_captura.desc())
        .first()
    )


def build_deal_item(
    game: Game,
    latest_price: PriceSnapshot | None,
    latest_rep: ReputationSnapshot | None,
    currency: str = "USD",
):
    if not latest_price:
        return None

    base_usd = float(latest_price.precio_base or 0)
    actual_usd = float(latest_price.precio_actual or 0)

    return {
        "juego": game.nombre,
        "slug": game.slug,
        "desarrollador": game.desarrollador,
        "publisher": game.publisher,
        "genero": game.genero,
        "steam_app_id": game.steam_app_id,
        "imagen_url": game.imagen_url,
        "descripcion": game.descripcion,
        "precio_original": money(base_usd, "USD", currency),
        "precio_oferta": money(actual_usd, "USD", currency),
        "precio_original_valor": convert(base_usd, currency),
        "precio_oferta_valor": convert(actual_usd, currency),
        "moneda": currency.upper(),
        "descuento": int(round(float(latest_price.descuento_porcentaje or 0))),
        "reputacion_score": round(float(latest_rep.score_promedio or 0), 1) if latest_rep else 0.0,
        "reputacion_reviews": int(latest_rep.cantidad_reseñas or 0) if latest_rep else 0,
    }


def build_deals_payload(db: Session, currency: str = "USD") -> list[dict]:
    payload = []
    games = db.query(Game).order_by(Game.nombre.asc()).all()
    for game in games:
        latest_price = get_latest_price(db, game.id)
        latest_rep = get_latest_rep(db, game.id)
        item = build_deal_item(game, latest_price, latest_rep, currency)
        if item:
            payload.append(item)

    return sorted(payload, key=lambda item: (item["descuento"], item["reputacion_score"]), reverse=True)


# ──────────────────────────────────────────────────────────────
# Static pages
# ──────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def home_redirect():
    return RedirectResponse("/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    return read_static_file("dashboard.html")


@app.get("/catalog", response_class=HTMLResponse)
def serve_catalog():
    return read_static_file("catalog.html")


@app.get("/game/{slug}", response_class=HTMLResponse)
def serve_game_page(slug: str):
    return read_static_file("game.html")


# ──────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "online", "service": "GameDeal Insight API", "version": "2.0.0"}


# ──────────────────────────────────────────────────────────────
# Deals & games
# ──────────────────────────────────────────────────────────────

@app.get("/api/deals")
def get_market_deals(
    currency: str = Query(default="USD", description="Target currency code (USD, COP, EUR…)"),
    db: Session = Depends(get_db),
):
    return build_deals_payload(db, currency.upper())


@app.get("/api/stats")
def get_stats(
    currency: str = Query(default="USD"),
    db: Session = Depends(get_db),
):
    deals = build_deals_payload(db, currency.upper())
    total_games = db.query(Game).count()
    on_sale = [deal for deal in deals if deal["descuento"] > 0]
    best_discount = max(on_sale, key=lambda deal: deal["descuento"], default=None)
    rated_games = [deal for deal in deals if deal["reputacion_reviews"] > 0]
    avg_reputation = round(
        sum(deal["reputacion_score"] for deal in rated_games) / len(rated_games), 1
    ) if rated_games else 0.0

    return {
        "total_games": total_games,
        "games_on_sale": len(on_sale),
        "best_discount": best_discount,
        "avg_reputation": avg_reputation,
        "currency": currency.upper(),
    }


@app.get("/api/games")
def get_all_games(
    currency: str = Query(default="USD"),
    db: Session = Depends(get_db),
):
    games = db.query(Game).order_by(Game.nombre.asc()).all()
    payload = []
    for game in games:
        latest_price = get_latest_price(db, game.id)
        latest_rep = get_latest_rep(db, game.id)

        price_data = None
        if latest_price:
            price_usd = float(latest_price.precio_actual or 0)
            base_usd = float(latest_price.precio_base or 0)
            price_data = {
                "precio_actual": convert(price_usd, currency),
                "precio_base": convert(base_usd, currency),
                "descuento_porcentaje": round(float(latest_price.descuento_porcentaje or 0), 2),
                "moneda": currency.upper(),
                "fecha_captura": latest_price.fecha_captura.isoformat() if latest_price.fecha_captura else None,
            }

        payload.append(
            {
                **serialize_game(game),
                "latest_price": price_data,
                "latest_rep": {
                    "score_promedio": round(float(latest_rep.score_promedio or 0), 1),
                    "cantidad_reseñas": int(latest_rep.cantidad_reseñas or 0),
                    "score_tipo": latest_rep.score_tipo,
                    "fecha_captura": latest_rep.fecha_captura.isoformat() if latest_rep and latest_rep.fecha_captura else None,
                } if latest_rep else None,
            }
        )
    return payload


@app.get("/api/game/{slug}/data")
def get_game_detail(
    slug: str,
    currency: str = Query(default="USD"),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(Game.slug == slug).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    latest_price = get_latest_price(db, game.id)
    latest_rep = get_latest_rep(db, game.id)
    history_rows = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.game_id == game.id, PriceSnapshot.platform == "steam")
        .order_by(PriceSnapshot.fecha_captura.desc())
        .limit(20)
        .all()
    )
    history_rows.reverse()

    cur = currency.upper()
    price_payload = None
    if latest_price:
        price_usd = float(latest_price.precio_actual or 0)
        base_usd = float(latest_price.precio_base or 0)
        price_payload = {
            "precio_actual": convert(price_usd, cur),
            "precio_base": convert(base_usd, cur),
            "descuento_porcentaje": round(float(latest_price.descuento_porcentaje or 0), 2),
            "moneda": cur,
            "precio_actual_formateado": _fmt_money(convert(price_usd, cur), cur),
            "precio_base_formateado": _fmt_money(convert(base_usd, cur), cur),
            "fecha_captura": latest_price.fecha_captura.isoformat() if latest_price.fecha_captura else None,
        }

    return {
        "game": serialize_game(game),
        "latest_price": price_payload,
        "latest_rep": {
            "score_promedio": round(float(latest_rep.score_promedio or 0), 1),
            "cantidad_reseñas": int(latest_rep.cantidad_reseñas or 0),
            "score_tipo": latest_rep.score_tipo,
            "fecha_captura": latest_rep.fecha_captura.isoformat() if latest_rep and latest_rep.fecha_captura else None,
        } if latest_rep else None,
        "price_history": [
            {
                "fecha": row.fecha_captura.date().isoformat() if row.fecha_captura else None,
                "precio": convert(float(row.precio_actual or 0), cur),
                "descuento": int(round(float(row.descuento_porcentaje or 0))),
                "moneda": cur,
            }
            for row in history_rows
        ],
    }


# ──────────────────────────────────────────────────────────────
# Multi-platform price comparison
# ──────────────────────────────────────────────────────────────

@app.get("/api/game/{slug}/platform-prices")
def get_platform_prices(
    slug: str,
    currency: str = Query(default="USD"),
    db: Session = Depends(get_db),
):
    """Return the latest price per platform (Steam, GOG, Epic, Humble…) for a game."""
    game = db.query(Game).filter(Game.slug == slug).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    cur = currency.upper()
    raw = get_platform_prices_for_game(game.id)

    result = []
    for entry in raw:
        price_usd = entry["price"]
        base_usd = entry["base_price"]
        result.append({
            "platform": entry["platform"],
            "price": convert(price_usd, cur),
            "base_price": convert(base_usd, cur),
            "discount": entry["discount"],
            "currency": cur,
            "price_formatted": _fmt_money(convert(price_usd, cur), cur),
            "captured_at": entry["captured_at"],
        })

    return {
        "game": game.nombre,
        "slug": slug,
        "currency": cur,
        "platforms": result,
    }


# ──────────────────────────────────────────────────────────────
# Currency
# ──────────────────────────────────────────────────────────────

@app.get("/api/currency/rates")
def get_currency_rates():
    """Return all available exchange rates relative to USD."""
    rates = get_rates()
    return {
        "base": "USD",
        "rates": rates,
        "supported": {
            code: {"name": name, "rate": rates.get(code, 1.0)}
            for code, name in SUPPORTED_CURRENCIES.items()
        },
    }


@app.get("/api/currency/convert")
def convert_currency(
    amount: float = Query(..., description="Amount in USD"),
    to: str = Query(..., description="Target currency code"),
):
    """Convert a USD amount to the target currency."""
    cur = to.upper()
    if cur not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {cur}")
    converted = convert(amount, cur)
    return {
        "original": amount,
        "from": "USD",
        "to": cur,
        "converted": converted,
        "formatted": _fmt_money(converted, cur),
    }


# ──────────────────────────────────────────────────────────────
# Legacy routes
# ──────────────────────────────────────────────────────────────

@app.get("/games")
def legacy_games(db: Session = Depends(get_db)):
    return get_all_games(db=db)


@app.get("/deals")
def legacy_deals(db: Session = Depends(get_db)):
    return get_market_deals(db=db)
