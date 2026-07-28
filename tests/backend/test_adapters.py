import pytest
from signal_index.routes.catalog import PUBLIC_SOURCE_PROFILES, REMOTE_ADAPTER_TYPES
from source_adapters.adapters import CSVAdapter, JSONAdapter
from source_adapters.public_catalogs import (
    KiwiSDRDirectoryAdapter,
    PriyomScheduleAdapter,
    WebSDRDirectoryAdapter,
)


@pytest.fixture(autouse=True)
def bypass_network_resolution_for_parser_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parsing fixtures must not depend on the sandbox DNS resolver."""
    monkeypatch.setattr(
        "source_adapters.http.validate_external_url",
        lambda url, allowed_hosts=None: url,
    )


def test_csv_parser_and_deduplication() -> None:
    adapter = CSVAdapter(b"frequency_hz,label\n4625000,Demo\n", "FREQUENCY")
    records = adapter.parse(adapter.payload)
    assert records[0].data["frequency_hz"] == "4625000"
    assert adapter.deduplicate_key(records[0]) == adapter.deduplicate_key(records[0])


def test_json_parser_rejects_scalar() -> None:
    adapter = JSONAdapter(b"42", "EVENT")
    with pytest.raises(ValueError, match="object"):
        adapter.parse(adapter.payload)


def test_kiwisdr_directory_normalizes_a_catalogue_receiver() -> None:
    payload = b"""
    <li class="list-group-item"><h3>Bad Ragaz KiwiSDR</h3>
      <p>0-30 MHz KiwiSDR receiver</p>
      <a href=\"http://sdr-badragaz.proxy.kiwisdr.com:8073\">Open</a>
    </li>
    """
    adapter = KiwiSDRDirectoryAdapter(
        "https://www.receiverbook.de/?page=1&type=kiwisdr", {"www.receiverbook.de"}
    )
    records = adapter.parse(payload)
    assert len(records) == 1
    assert records[0].record_type == "RECEIVER"
    assert records[0].data["receiver_type"] == "KIWISDR"
    assert records[0].data["base_url"] == "http://sdr-badragaz.proxy.kiwisdr.com:8073"
    assert "{frequency_khz}" in str(records[0].data["tuning_url_template"])
    assert records[0].data["metadata"]["catalogue_only"] is True


def test_websdr_directory_normalizes_permitted_json_response() -> None:
    payload = b'''// permissioned fixture
    [{"url":"https://receiver.example/websdr", "desc":"University WebSDR", "qth":"JO32KF", "lat":52.2, "lon":6.8,
      "bands":[{"l":0,"h":29.1596}]}]
    '''
    adapter = WebSDRDirectoryAdapter(
        "https://directory.example/permissioned-websdr.json", {"directory.example"}
    )
    records = adapter.parse(payload)
    assert [record.data["base_url"] for record in records] == ["https://receiver.example/websdr"]
    assert records[0].data["min_frequency_hz"] == 0
    assert records[0].data["max_frequency_hz"] == 29_159_600
    assert "{frequency_khz}" in str(records[0].data["tuning_url_template"])


def test_priyom_schedule_normalizes_frequency_and_station() -> None:
    payload = b"""
    <table><tr><th>UTC</th><th>Station</th><th>Frequency</th></tr>
    <tr><td>10:00 UTC</td><td>F01</td><td>4625 kHz USB</td></tr></table>
    """
    adapter = PriyomScheduleAdapter("https://priyom.org/number-stations/station-schedule", {"priyom.org"})
    records = adapter.parse(payload)
    assert len(records) == 1
    assert records[0].data["frequency_hz"] == 4_625_000
    assert records[0].data["station_name"] == "F01"
    assert records[0].data["category"] == "NUMBERS"
    assert records[0].data["schedule"]["utc"] == "10:00"


def test_priyom_calendar_normalizes_each_public_frequency() -> None:
    payload = b'''{
      "items": [{
        "summary": "V13 15388kHz USB/AM [Target: East Asia]",
        "start": {"dateTime": "2026-07-28T00:00:00.000Z"}
      }]
    }'''
    adapter = PriyomScheduleAdapter("https://calendar2.priyom.org/events", {"calendar2.priyom.org"})
    records = adapter.parse(payload)
    assert records[0].data["frequency_hz"] == 15_388_000
    assert records[0].data["station_name"] == "V13"
    assert records[0].observed_at is not None


def test_maintained_catalogue_profiles_are_remote_and_rate_bounded() -> None:
    assert set(PUBLIC_SOURCE_PROFILES) == {
        "websdr-directory",
        "kiwisdr-receiverbook",
        "priyom-number-station-schedule",
    }
    for profile in PUBLIC_SOURCE_PROFILES.values():
        assert profile["adapter_type"] in REMOTE_ADAPTER_TYPES
        assert int(profile["config"]["interval_sec"]) >= 300
        assert profile["config"]["allowed_hosts"]
    assert PUBLIC_SOURCE_PROFILES["websdr-directory"]["config"]["requires_terms_approval"] is True
