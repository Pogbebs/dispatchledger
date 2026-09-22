"""Database connection settings for DispatchLedger."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Reads DATABASE_URL from the environment if set; otherwise uses the local Docker database.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://dispatch:dispatch@localhost:5433/dispatchledger",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
