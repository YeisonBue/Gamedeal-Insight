"""
src/services/currency_service.py
─────────────────────────────────
Fetches and caches exchange rates from the free open.er-api.com endpoint.
Rates are stored in the DB and refreshed every 12 hours by the scheduler.
"""

import datetime
import logging

import httpx

from src.db.database import SessionLocal
from src.models.models import CurrencyRate

logger = logging.getLogger(__name__)

EXCHANGE_API_URL = "https://open.er-api.com/v6/latest/USD"

SUPPORTED_CURRENCIES = {
    "USD": "US Dollar",
    "COP": "Colombian Peso",
    "EUR": "Euro",
    "BRL": "Brazilian Real",
    "MXN": "Mexican Peso",
    "GBP": "British Pound",
    "ARS": "Argentine Peso",
    "CLP": "Chilean Peso",
    "PEN": "Peruvian Sol",
    "CAD": "Canadian Dollar",
    "JPY": "Japanese Yen",
    "AUD": "Australian Dollar",
}

# Fallback rates if the API is unreachable
_FALLBACK_RATES: dict[str, float] = {
    "USD": 1.0,
    "COP": 4100.0,
    "EUR": 0.92,
    "BRL": 5.0,
    "MXN": 17.0,
    "GBP": 0.79,
    "ARS": 900.0,
    "CLP": 920.0,
    "PEN": 3.75,
    "CAD": 1.37,
    "JPY": 155.0,
    "AUD": 1.53,
}


def fetch_and_store_rates() -> bool:
    """Fetch fresh exchange rates and persist them to the database."""
    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(EXCHANGE_API_URL)
            res.raise_for_status()
            data = res.json()

        if data.get("result") != "success":
            logger.warning("Exchange rate API returned non-success result.")
            return False

        api_rates: dict = data.get("rates", {})
        now = datetime.datetime.now(datetime.timezone.utc)

        db = SessionLocal()
        try:
            for code in SUPPORTED_CURRENCIES:
                rate = api_rates.get(code)
                if rate is None:
                    continue
                existing = db.query(CurrencyRate).filter_by(code=code).first()
                if existing:
                    existing.rate_from_usd = rate
                    existing.updated_at = now
                else:
                    db.add(CurrencyRate(code=code, rate_from_usd=rate, updated_at=now))
            db.commit()
            logger.info(f"Currency rates refreshed for {len(SUPPORTED_CURRENCIES)} currencies.")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to store currency rates: {e}")
            return False
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Failed to fetch currency rates from API: {e}")
        _seed_fallback_rates()
        return False


def _seed_fallback_rates():
    """Persist hardcoded fallback rates when API is unreachable."""
    db = SessionLocal()
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        for code, rate in _FALLBACK_RATES.items():
            if not db.query(CurrencyRate).filter_by(code=code).first():
                db.add(CurrencyRate(code=code, rate_from_usd=rate, updated_at=now))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def get_rates() -> dict[str, float]:
    """Return current rates from DB, seeding fallbacks if table is empty."""
    db = SessionLocal()
    try:
        rows = db.query(CurrencyRate).all()
        if not rows:
            _seed_fallback_rates()
            rows = db.query(CurrencyRate).all()
        return {r.code: r.rate_from_usd for r in rows}
    finally:
        db.close()


def convert(amount_usd: float, to_currency: str) -> float:
    """Convert a USD amount to the target currency."""
    code = to_currency.upper()
    if code == "USD":
        return round(amount_usd, 2)
    rates = get_rates()
    rate = rates.get(code, 1.0)
    return round(amount_usd * rate, 2)


def rates_are_stale(max_age_hours: int = 12) -> bool:
    """Return True if rates haven't been updated within the given window."""
    db = SessionLocal()
    try:
        row = db.query(CurrencyRate).order_by(CurrencyRate.updated_at.desc()).first()
        if not row:
            return True
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=max_age_hours)
        updated = row.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=datetime.timezone.utc)
        return updated < cutoff
    finally:
        db.close()
