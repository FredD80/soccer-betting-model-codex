from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from api.config import settings

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(settings.database_url)
        _SessionLocal = sessionmaker(bind=_engine)
    return _SessionLocal


def get_session():
    session = _get_engine()()
    try:
        yield session
    finally:
        session.close()
