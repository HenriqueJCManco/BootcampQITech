import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.utils import DbUtils


SOURCE_DIR = Path(__file__).resolve().parents[3] / "src"
if SOURCE_DIR.is_dir() and str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))


@pytest.fixture(autouse=True)
def reset_database():
    DbUtils.rollback()


@pytest.fixture
def session():
    engine = create_engine(DbUtils.database_url())
    db_session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield db_session
    finally:
        db_session.close()
        engine.dispose()
