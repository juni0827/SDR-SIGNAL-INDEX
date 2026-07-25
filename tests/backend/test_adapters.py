import pytest
from source_adapters.adapters import CSVAdapter, JSONAdapter


def test_csv_parser_and_deduplication() -> None:
    adapter = CSVAdapter(b"frequency_hz,label\n4625000,Demo\n", "FREQUENCY")
    records = adapter.parse(adapter.payload)
    assert records[0].data["frequency_hz"] == "4625000"
    assert adapter.deduplicate_key(records[0]) == adapter.deduplicate_key(records[0])


def test_json_parser_rejects_scalar() -> None:
    adapter = JSONAdapter(b"42", "EVENT")
    with pytest.raises(ValueError, match="object"):
        adapter.parse(adapter.payload)
