import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Database connection string sourced from environment variables for Docker compatibility
# Default fallback to localhost for local development environments
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://gamedeal:admin123@localhost/gamedealdb"
)

# Initialize SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Session factory for database transactions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for declarative models
Base = declarative_base()