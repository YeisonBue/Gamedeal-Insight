# GameDeal Insight — Copilot Instructions

## Running the project

**Docker (recommended):**
```bash
docker-compose up --build
```
App available at `http://localhost:8000/dashboard`.

**Local (without Docker):**
```powershell
# Requires a running PostgreSQL instance
.\venv\Scripts\uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

**Environment variable:** `DATABASE_URL` defaults to `postgresql://gamedeal:admin123@localhost/gamedealdb`.

## Verification commands

```powershell
# Check all files compile without errors
python -m compileall src scraping

# Run DB migration (safe to re-run; adds missing columns, never drops data)
python -m src.db.init_db

# Verify imports
python -c "from src.main import app; print('OK')"
```

There is no automated test suite. Validate by hitting these endpoints manually after startup:
- `GET /health`
- `GET /api/stats?currency=COP`
- `GET /api/deals?currency=EUR`
- `GET /api/game/{slug}/platform-prices?currency=COP`
- `GET /api/currency/rates`

## Architecture

FastAPI app (`src/main.py`) with a background scheduler thread (`src/scheduler.py`) launched at startup via FastAPI `lifespan`.

**Data flow:**
```
Startup:
  seed_static_app_ids()        → discovered_app_ids table (sync, ~122 IDs)
  job_currency_rates()         → currency_rates table
  job_steam_sync()             → games + price_snapshots + reputation_snapshots
  job_discover_app_ids()       → daemon thread, scrapes Steam Search HTML for new App IDs

Recurring:
  Steam sync     every 6h  — re-checks any app_id with last_check > 24h ago
  Platform sync  every 12h — CheapShark API for GOG, Epic, Humble, etc.
  Currency rates every 12h — open.er-api.com (fallback to hardcoded rates)
```

**Layer responsibilities:**
- `src/models/models.py` — SQLAlchemy ORM: `Game`, `PriceSnapshot`, `ReputationSnapshot`, `DiscoveredAppId`, `CurrencyRate`
- `src/db/database.py` — engine + `SessionLocal` + `Base`
- `src/db/init_db.py` — `create_all` + `_migrate_columns()` (ALTER TABLE for new columns)
- `src/collectors/steam_collector.py` — fetches Steam App Details API; delta logic avoids duplicate snapshots
- `src/collectors/platform_collector.py` — CheapShark API for multi-store prices
- `src/collectors/itad_collector.py` — **mock, not used in production**
- `src/services/currency_service.py` — converts USD amounts on-the-fly; caches rates in DB
- `src/scheduler.py` — orchestrates all background jobs with `schedule` library
- `src/static/` — plain HTML pages (dashboard, catalog, game detail); no framework, vanilla JS + Chart.js

## Key conventions

**All prices stored in USD; conversions are always on-the-fly.**  
`convert(amount_usd, target_currency)` from `currency_service` is the single conversion point. Never store converted values.

**Delta snapshots only.**  
`SteamCollector.save_to_db()` calls `_price_changed()` before inserting a `PriceSnapshot`. A new row is only created if price changed by >$0.01 or discount by >0.5 points. Same logic in `platform_collector`.

**`DiscoveredAppId` is the game catalog source.**  
The scheduler only syncs App IDs that are in this table. To add a game, insert its Steam App ID here (or add it to `TARGET_APP_IDS` in `steam_collector.py` for persistence across resets).

**DB migrations never destroy data.**  
`init_db._migrate_columns()` only adds columns with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Dropping or renaming columns must be done manually.

**`platform` column distinguishes price sources.**  
`PriceSnapshot.platform` defaults to `'steam'`. Multi-platform rows use store names from CheapShark (e.g., `"GOG"`, `"Epic Games"`, `"Humble Store"`).

**Currency selector persists in `localStorage`** under key `gamedeal_currency`. All three HTML pages read this key on load and pass `?currency=` to every API call.

**`get_db()` dependency pattern** for all FastAPI routes:
```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**External APIs used (no keys required):**
- Steam App Details: `https://store.steampowered.com/api/appdetails?appids=...`
- Steam Search HTML scraping (cookies: `birthtime=0`, `mature_content=1`)
- CheapShark: `https://www.cheapshark.com/api/1.0/`
- Exchange rates: `https://open.er-api.com/v6/latest/USD`
