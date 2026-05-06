import logging
from src.db.database import SessionLocal
from src.models.models import PriceSnapshot

# Configure basic logging for traceability
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def remove_test_data():
    """
    Removes temporary mock data from the snapshots table to ensure
    database integrity before production analysis.
    """
    session = SessionLocal()
    try:
        # Target specific test entry by price point
        target_record = session.query(PriceSnapshot).filter(
            PriceSnapshot.precio_actual == 29.99
        ).first()

        if target_record:
            session.delete(target_record)
            session.commit()
            logger.info("Cleanup successful: Test record removed.")
        else:
            logger.info("No matching test records found.")

    except Exception as e:
        session.rollback()
        logger.error(f"Database error during cleanup: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    remove_test_data()