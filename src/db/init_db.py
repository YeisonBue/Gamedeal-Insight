from src.db.database import engine, Base
from src.models.models import Game, PriceSnapshot, ReputationSnapshot

def init_db():
    """
    Initializes the database schema by creating all tables defined in the metadata.
    Ensures that the connection to PostgreSQL is established before execution.
    """
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Database initialization failed: {e}")
        raise

if __name__ == "__main__":
    init_db()