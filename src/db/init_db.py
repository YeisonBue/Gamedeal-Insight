from sqlalchemy import inspect, text

from src.db.database import engine, Base
from src.models.models import Game, PriceSnapshot, ReputationSnapshot


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
            if "steam_app_id" not in existing:
                conn.execute(text("ALTER TABLE games ADD COLUMN steam_app_id VARCHAR"))
                conn.commit()
            if "imagen_url" not in existing:
                conn.execute(text("ALTER TABLE games ADD COLUMN imagen_url VARCHAR"))
                conn.commit()


if __name__ == "__main__":
    init_db()
