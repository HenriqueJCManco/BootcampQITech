import pytest

from tests.utils import DbUtils


@pytest.fixture(autouse=True)
def reset_database():
    DbUtils.rollback()
