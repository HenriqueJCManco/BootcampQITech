import json
import re
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = PROJECT_ROOT / "src"
SCHEMA_FILE = PROJECT_ROOT / "database" / "database.sql"

if SOURCE_DIR.is_dir() and str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))


def seeded_engine_params() -> dict:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    match = re.search(r"INSERT INTO fraude\.engine_config.*?'(\{.*?\})'::jsonb", sql, re.DOTALL)
    return json.loads(match.group(1))


@pytest.fixture
def engine_config():
    from domain import EngineConfig

    return EngineConfig(version=1, params=seeded_engine_params())
