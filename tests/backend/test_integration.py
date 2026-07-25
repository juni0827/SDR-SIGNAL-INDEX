import os

import pytest
from signal_index.database import engine
from source_adapters.adapters import CSVAdapter
from sqlalchemy import text

pytestmark = pytest.mark.integration


def require_integration() -> None:
    if os.getenv("SIGNAL_INDEX_INTEGRATION") != "1":
        pytest.skip("set SIGNAL_INDEX_INTEGRATION=1 with Docker services running")


def test_database_migration_reachable() -> None:
    require_integration()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 1


def test_csv_import_contract() -> None:
    require_integration()
    adapter = CSVAdapter(b"frequency_hz,label\n4625000,Integration\n", "FREQUENCY")
    assert adapter.parse(adapter.payload)[0].data["label"] == "Integration"
