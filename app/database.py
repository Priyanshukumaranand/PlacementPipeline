from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/placements"
)

# Create engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set True for SQL debugging
    pool_pre_ping=True  # Verify connections before use
)

# Session factory for request-scoped sessions
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


def get_db():
    """
    FastAPI dependency to get a database session.
    
    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...
    
    Yields:
        Session: Database session that auto-closes after request
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
