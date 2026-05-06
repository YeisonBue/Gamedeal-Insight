from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from src.db.database import SessionLocal
from src.models.models import Game, PriceSnapshot, ReputationSnapshot

app = FastAPI(
    title="GameDeal Insight API",
    version="1.0.0"
)

# Dependency to manage database session lifecycle
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health")
def health_check():
    """Service status endpoint."""
    return {"status": "online", "service": "GameDeal Insight API"}

@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the frontend application layer."""
    try:
        with open("src/static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(content="Dashboard source not found.", status_code=404)

@app.get("/games")
def get_all_games(db: Session = Depends(get_db)):
    """Retrieves all registered game metadata."""
    return db.query(Game).all()

@app.get("/deals")
def get_market_deals(db: Session = Depends(get_db)):
    """
    Analytics Engine: Aggregates the most recent price snapshots 
    and sentiment metrics for all indexed titles.
    """
    games = db.query(Game).all()
    payload = []
    
    for game in games:
        # Fetch latest temporal snapshots
        latest_price = db.query(PriceSnapshot)\
            .filter(PriceSnapshot.game_id == game.id)\
            .order_by(PriceSnapshot.fecha_captura.desc())\
            .first()
            
        latest_rep = db.query(ReputationSnapshot)\
            .filter(ReputationSnapshot.game_id == game.id)\
            .order_by(ReputationSnapshot.fecha_captura.desc())\
            .first()
        
        if latest_price:
            payload.append({
                "juego": game.nombre,
                "desarrollador": game.desarrollador,
                "precio_original": f"{latest_price.moneda} {latest_price.precio_base}",
                "precio_oferta": f"{latest_price.moneda} {latest_price.precio_actual}",
                "descuento": latest_price.descuento_porcentaje,
                "reputacion_score": round(latest_rep.score_promedio, 1) if latest_rep else 0,
                "reputacion_reviews": latest_rep.cantidad_reseñas if latest_rep else 0
            })
            
    return payload