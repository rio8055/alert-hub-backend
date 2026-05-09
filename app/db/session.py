from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=2,
    max_overflow=2,
    pool_timeout=30,
    connect_args={"connect_timeout": 15},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
