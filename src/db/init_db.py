from sqlalchemy import inspect, text

from src.db.database import engine, Base
from src.models.models import (
    Game, PriceSnapshot, ReputationSnapshot,
    DiscoveredAppId, CurrencyRate,
)


def init_db():
    try:
        Base.metadata.create_all(bind=engine)
        _migrate_columns()
        print("Database schema ready.")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        raise


def _migrate_columns():
    inspector = inspect(engine)

    if inspector.has_table("games"):
        existing = [col["name"] for col in inspector.get_columns("games")]
        with engine.connect() as conn:
            for col, ddl in [
                ("steam_app_id", "ALTER TABLE games ADD COLUMN steam_app_id VARCHAR"),
                ("imagen_url", "ALTER TABLE games ADD COLUMN imagen_url VARCHAR"),
                ("descripcion", "ALTER TABLE games ADD COLUMN descripcion TEXT"),
                ("last_scraped_at", "ALTER TABLE games ADD COLUMN last_scraped_at TIMESTAMP"),
            ]:
                if col not in existing:
                    conn.execute(text(ddl))
            conn.commit()

    if inspector.has_table("price_snapshots"):
        existing = [col["name"] for col in inspector.get_columns("price_snapshots")]
        with engine.connect() as conn:
            if "platform" not in existing:
                conn.execute(text(
                    "ALTER TABLE price_snapshots ADD COLUMN platform VARCHAR NOT NULL DEFAULT 'steam'"
                ))
            conn.commit()


if __name__ == "__main__":
    init_db()
