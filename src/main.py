from contextlib import asynccontextmanager
from pathlib import Path
import threading

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

import src.scheduler as scheduler_module
from src.db.database import SessionLocal
from src.models.models import Game, PriceSnapshot, ReputationSnapshot

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


def money(value: float | None, currency: str | None) -> str:
    amount = float(value or 0)
    return f"{currency or 'USD'} {amount:,.2f}"


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
    }


def get_latest_price(db: Session, game_id: int):
    return (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.game_id == game_id)
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


def build_deal_item(game: Game, latest_price: PriceSnapshot | None, latest_rep: ReputationSnapshot | None):
    if not latest_price:
        return None

    return {
        "juego": game.nombre,
        "slug": game.slug,
        "desarrollador": game.desarrollador,
        "publisher": game.publisher,
        "genero": game.genero,
        "steam_app_id": game.steam_app_id,
        "imagen_url": game.imagen_url,
        "precio_original": money(latest_price.precio_base, latest_price.moneda),
        "precio_oferta": money(latest_price.precio_actual, latest_price.moneda),
        "precio_original_valor": round(float(latest_price.precio_base or 0), 2),
        "precio_oferta_valor": round(float(latest_price.precio_actual or 0), 2),
        "descuento": int(round(float(latest_price.descuento_porcentaje or 0))),
        "reputacion_score": round(float(latest_rep.score_promedio or 0), 1) if latest_rep else 0.0,
        "reputacion_reviews": int(latest_rep.cantidad_reseñas or 0) if latest_rep else 0,
    }


def build_deals_payload(db: Session) -> list[dict]:
    payload = []
    games = db.query(Game).order_by(Game.nombre.asc()).all()
    for game in games:
        latest_price = get_latest_price(db, game.id)
        latest_rep = get_latest_rep(db, game.id)
        item = build_deal_item(game, latest_price, latest_rep)
        if item:
            payload.append(item)

    return sorted(payload, key=lambda item: (item["descuento"], item["reputacion_score"]), reverse=True)


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


@app.get("/health")
def health_check():
    return {"status": "online", "service": "GameDeal Insight API", "version": "2.0.0"}


@app.get("/api/deals")
def get_market_deals(db: Session = Depends(get_db)):
    return build_deals_payload(db)


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    deals = build_deals_payload(db)
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
    }


@app.get("/api/games")
def get_all_games(db: Session = Depends(get_db)):
    games = db.query(Game).order_by(Game.nombre.asc()).all()
    payload = []
    for game in games:
        latest_price = get_latest_price(db, game.id)
        latest_rep = get_latest_rep(db, game.id)
        payload.append(
            {
                **serialize_game(game),
                "latest_price": {
                    "precio_actual": round(float(latest_price.precio_actual or 0), 2),
                    "precio_base": round(float(latest_price.precio_base or 0), 2),
                    "descuento_porcentaje": round(float(latest_price.descuento_porcentaje or 0), 2),
                    "moneda": latest_price.moneda,
                    "fecha_captura": latest_price.fecha_captura.isoformat() if latest_price and latest_price.fecha_captura else None,
                } if latest_price else None,
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
def get_game_detail(slug: str, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.slug == slug).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    latest_price = get_latest_price(db, game.id)
    latest_rep = get_latest_rep(db, game.id)
    history_rows = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.game_id == game.id)
        .order_by(PriceSnapshot.fecha_captura.desc())
        .limit(20)
        .all()
    )
    history_rows.reverse()

    return {
        "game": serialize_game(game),
        "latest_price": {
            "precio_actual": round(float(latest_price.precio_actual or 0), 2),
            "precio_base": round(float(latest_price.precio_base or 0), 2),
            "descuento_porcentaje": round(float(latest_price.descuento_porcentaje or 0), 2),
            "moneda": latest_price.moneda,
            "precio_actual_formateado": money(latest_price.precio_actual, latest_price.moneda),
            "precio_base_formateado": money(latest_price.precio_base, latest_price.moneda),
            "fecha_captura": latest_price.fecha_captura.isoformat() if latest_price and latest_price.fecha_captura else None,
        } if latest_price else None,
        "latest_rep": {
            "score_promedio": round(float(latest_rep.score_promedio or 0), 1),
            "cantidad_reseñas": int(latest_rep.cantidad_reseñas or 0),
            "score_tipo": latest_rep.score_tipo,
            "fecha_captura": latest_rep.fecha_captura.isoformat() if latest_rep and latest_rep.fecha_captura else None,
        } if latest_rep else None,
        "price_history": [
            {
                "fecha": row.fecha_captura.date().isoformat() if row.fecha_captura else None,
                "precio": round(float(row.precio_actual or 0), 2),
                "descuento": int(round(float(row.descuento_porcentaje or 0))),
            }
            for row in history_rows
        ],
    }


@app.get("/games")
def legacy_games(db: Session = Depends(get_db)):
    return get_all_games(db)


@app.get("/deals")
def legacy_deals(db: Session = Depends(get_db)):
    return get_market_deals(db)
