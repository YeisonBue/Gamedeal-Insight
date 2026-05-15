import datetime
from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from src.db.database import Base


class Game(Base):
    """Core entity for game metadata."""

    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
    slug = Column(String, unique=True, index=True)
    genero = Column(String)
    desarrollador = Column(String)
    publisher = Column(String)
    fecha_lanzamiento = Column(DateTime)
    plataforma = Column(String)
    steam_app_id = Column(String, nullable=True)
    imagen_url = Column(String, nullable=True)
    descripcion = Column(String, nullable=True)
    last_scraped_at = Column(DateTime, nullable=True)


class PriceSnapshot(Base):
    """Temporal tracking of pricing data per game and source."""

    __tablename__ = "price_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"))
    source_id = Column(Integer)
    platform = Column(String, default="steam", nullable=False)
    precio_actual = Column(Float)
    precio_base = Column(Float)
    descuento_porcentaje = Column(Float)
    moneda = Column(String)
    fecha_captura = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


class ReputationSnapshot(Base):
    """Temporal tracking of user reviews and scores per game."""

    __tablename__ = "reputation_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"))
    source_id = Column(Integer)
    score_promedio = Column(Float)
    cantidad_reseñas = Column(Integer)
    score_tipo = Column(String)
    fecha_captura = Column(DateTime(timezone=True), server_default=func.now())


class DiscoveredAppId(Base):
    """Tracks Steam App IDs discovered via scraping for background processing."""

    __tablename__ = "discovered_app_ids"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String, unique=True, index=True, nullable=False)
    discovered_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    processed = Column(Boolean, default=False)
    last_check = Column(DateTime, nullable=True)


class CurrencyRate(Base):
    """Cached exchange rates relative to USD."""

    __tablename__ = "currency_rates"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, index=True, nullable=False)
    rate_from_usd = Column(Float, nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
