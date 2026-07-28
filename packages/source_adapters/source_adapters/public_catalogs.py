"""Adapters for public receiver directories and number-station schedules.

They deliberately produce *catalogue records*, not audio captures.  A public
receiver's tuning page is not proof that its audio transport may be recorded;
the capture worker remains opt-in and uses a separately authorised URL.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from .adapters import RemoteAdapter
from .base import FetchResult, NormalizedRecord
from .http import PoliteFetcher

_FREQUENCY = re.compile(r"(?P<frequency>\d{3,5}(?:[.,]\d+)?)\s*(?:kHz|khz)", re.IGNORECASE)
_STATION = re.compile(r"\b(?P<station>[A-Z]{1,3}\s?-?\d{1,3}[A-Z]?)\b")
_UTC_TIME = re.compile(r"\b(?P<time>(?:[01]\d|2[0-3]):[0-5]\d)(?:\s*(?:UTC|Z))?\b", re.IGNORECASE)


def _absolute_http_url(raw_url: str, page_url: str) -> str | None:
    candidate = urljoin(page_url, raw_url.strip())
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate.rstrip("/ ")


def _mode_from_text(text: str) -> str | None:
    upper = text.upper()
    for mode in ("USB", "LSB", "AM", "CW", "FM"):
        if re.search(rf"\b{mode}\b", upper):
            return mode
    return None


class _DirectoryAdapter(RemoteAdapter):
    """Common normalizer for public receiver listings.

    Directory HTML varies substantially.  The parser scopes each outbound
    endpoint to its nearest card/list container and retains the listing URL in
    provenance metadata instead of inventing transmitter coordinates.
    """

    receiver_type = "OTHER"
    source_name = "receiver_directory"
    parser_version = "1.0.0"

    def __init__(
        self,
        url: str,
        allowed_hosts: set[str] | None = None,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        super().__init__(url, "RECEIVER", allowed_hosts, etag=etag, last_modified=last_modified)
        self.directory_url = url

    def _candidate_urls(self, soup: BeautifulSoup) -> Iterable[tuple[str, Tag]]:
        directory_host = (urlparse(self.directory_url).hostname or "").lower()
        for anchor in soup.select("a[href]"):
            candidate = _absolute_http_url(str(anchor.get("href", "")), self.directory_url)
            if candidate is None:
                continue
            host = (urlparse(candidate).hostname or "").lower()
            if host == directory_host:
                continue
            context = anchor.find_parent(["article", "li", "tr", "section", "div"]) or anchor
            yield candidate, context

    def _is_receiver_link(self, url: str, context: str) -> bool:
        return self.receiver_type.lower() in f"{url} {context}".lower()

    def parse(self, payload: bytes) -> list[NormalizedRecord]:
        soup = BeautifulSoup(payload, "html.parser")
        records: list[NormalizedRecord] = []
        seen: set[str] = set()
        for endpoint, context_node in self._candidate_urls(soup):
            context = context_node.get_text(" ", strip=True)
            if not self._is_receiver_link(endpoint, context):
                continue
            canonical = endpoint.rstrip("/")
            if canonical in seen:
                continue
            seen.add(canonical)
            title = context_node.find(["h1", "h2", "h3", "h4", "strong", "b"])
            name = title.get_text(" ", strip=True) if title else ""
            if not name:
                image = context_node.select_one("img[alt]")
                name = str(image.get("alt", "")).removesuffix(" avatar") if image else ""
            if not name:
                name = urlparse(endpoint).hostname or endpoint
            frequency_text = context.lower()
            min_hz = 0 if "0-30" in frequency_text or "0 – 30" in frequency_text else None
            max_hz = 30_000_000 if min_hz == 0 else None
            records.append(
                NormalizedRecord(
                    "RECEIVER",
                    {
                        "name": name[:200],
                        "receiver_type": self.receiver_type,
                        "base_url": endpoint,
                        "min_frequency_hz": min_hz,
                        "max_frequency_hz": max_hz,
                        "supported_modes": [],
                        "status": "UNKNOWN",
                        "tuning_url_template": self.tuning_template(endpoint),
                        "metadata": {
                            "directory_url": self.directory_url,
                            "directory_adapter": self.source_name,
                            "catalogue_only": True,
                        },
                    },
                    source_url=self.directory_url,
                    confidence=0.65,
                    raw={"endpoint": endpoint, "listing_text": context[:2_000]},
                )
            )
        return records

    def tuning_template(self, endpoint: str) -> str | None:
        """Return a safe browser tuning template only where the URL syntax is known."""
        return None


class KiwiSDRDirectoryAdapter(_DirectoryAdapter):
    """Parse KiwiSDR links from a public listing such as Receiverbook."""

    receiver_type = "KIWISDR"
    source_name = "kiwisdr_directory"
    parser_version = "1.0.0"

    def __init__(
        self,
        url: str,
        allowed_hosts: set[str] | None = None,
        *,
        max_pages: int = 1,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        super().__init__(url, allowed_hosts, etag=etag, last_modified=last_modified)
        if not 1 <= max_pages <= 64:
            raise ValueError("max_pages must be between 1 and 64")
        self.max_pages = max_pages

    @staticmethod
    def _page_url(url: str, page: int) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["page"] = str(page)
        return urlunparse(parsed._replace(query=urlencode(query)))

    async def fetch(self, cursor: str | None) -> FetchResult:
        """Fetch a bounded Receiverbook listing sequentially and politely.

        Conditional validators are intentionally used only for a one-page
        profile: aggregating page ETags would make a false 304 result possible.
        """
        if self.max_pages == 1:
            return await super().fetch(cursor)
        pages: list[bytes] = []
        for page in range(1, self.max_pages + 1):
            page_url = self._page_url(self.directory_url, page)
            result = await PoliteFetcher(
                page_url,
                allowed_hosts={urlparse(self.directory_url).hostname or ""},
            ).fetch(None)
            pages.append(result.payload)
        return FetchResult(
            payload=b"\n<!-- signal-index-page-break -->\n".join(pages),
            cursor=str(self.max_pages),
            source_url=self.directory_url,
            fetched_at=datetime.now(UTC),
        )

    def _is_receiver_link(self, url: str, context: str) -> bool:
        joined = f"{url} {context}".lower()
        return "kiwisdr" in joined or ":8073" in url

    def _candidate_urls(self, soup: BeautifulSoup) -> Iterable[tuple[str, Tag]]:
        """Receiverbook's receiver cards avoid its global navigation links."""
        directory_host = (urlparse(self.directory_url).hostname or "").lower()
        for card in soup.select("li.list-group-item"):
            context = card.get_text(" ", strip=True)
            for anchor in card.select("a[href]"):
                candidate = _absolute_http_url(str(anchor.get("href", "")), self.directory_url)
                if candidate is None:
                    continue
                host = (urlparse(candidate).hostname or "").lower()
                if host == directory_host or not self._is_receiver_link(candidate, context):
                    continue
                yield candidate, card

    def tuning_template(self, endpoint: str) -> str | None:
        separator = "&" if "?" in endpoint else "?"
        # KiwiSDR accepts a frequency/mode query on its browser UI.  This is a
        # navigation link, never a capture transport.
        return f"{endpoint}{separator}f={{frequency_khz}}{{mode}}"


class WebSDRDirectoryAdapter(_DirectoryAdapter):
    """Parse a permitted WebSDR directory JSON response into receivers.

    The official list carries an explicit no-automated-reuse notice. This
    adapter is available for a user who has permission, but is not a default
    unattended profile.
    """

    receiver_type = "WEBSDR"
    source_name = "websdr_directory"
    parser_version = "1.0.0"

    def _is_receiver_link(self, url: str, context: str) -> bool:
        return "websdr" in f"{url} {context}".lower()

    def tuning_template(self, endpoint: str) -> str | None:
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}tune={{frequency_khz}}{{mode}}"

    def parse(self, payload: bytes) -> list[NormalizedRecord]:
        text = payload.decode("utf-8", errors="replace")
        start = text.find("[")
        if start < 0:
            return super().parse(payload)
        try:
            decoded = json.loads(text[start:])
        except json.JSONDecodeError:
            return super().parse(payload)
        if not isinstance(decoded, list):
            raise ValueError("WebSDR directory response is not a list")
        records: list[NormalizedRecord] = []
        for row in decoded:
            if not isinstance(row, dict) or not isinstance(row.get("url"), str):
                continue
            endpoint = _absolute_http_url(row["url"], self.directory_url)
            if endpoint is None:
                continue
            bands_value = row.get("bands")
            bands: list[object] = bands_value if isinstance(bands_value, list) else []
            ranges = [band for band in bands if isinstance(band, dict)]
            lows = [float(band["l"]) for band in ranges if isinstance(band.get("l"), int | float)]
            highs = [float(band["h"]) for band in ranges if isinstance(band.get("h"), int | float)]
            records.append(
                NormalizedRecord(
                    "RECEIVER",
                    {
                        "name": str(row.get("desc") or urlparse(endpoint).hostname or endpoint)[:200],
                        "receiver_type": "WEBSDR",
                        "base_url": endpoint,
                        "latitude": row.get("lat") if isinstance(row.get("lat"), int | float) else None,
                        "longitude": row.get("lon") if isinstance(row.get("lon"), int | float) else None,
                        "grid_locator": str(row.get("qth")) if row.get("qth") else None,
                        "min_frequency_hz": round(min(lows) * 1_000_000) if lows else None,
                        "max_frequency_hz": round(max(highs) * 1_000_000) if highs else None,
                        "supported_modes": [],
                        "status": "UNKNOWN",
                        "tuning_url_template": self.tuning_template(endpoint),
                        "metadata": {
                            "directory_url": self.directory_url,
                            "directory_adapter": self.source_name,
                            "catalogue_only": True,
                            "directory_terms_approved": True,
                        },
                    },
                    source_url=self.directory_url,
                    confidence=0.7,
                    raw={"directory_record": row},
                )
            )
        if not records:
            raise ValueError("no receiver endpoints found in WebSDR directory response")
        return records


class PriyomScheduleAdapter(RemoteAdapter):
    """Normalize publicly listed number-station schedule rows into frequencies."""

    source_name = "priyom_schedule"
    parser_version = "1.0.0"

    def __init__(
        self,
        url: str,
        allowed_hosts: set[str] | None = None,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        super().__init__(url, "FREQUENCY", allowed_hosts, etag=etag, last_modified=last_modified)
        self.schedule_url = url

    async def fetch(self, cursor: str | None) -> FetchResult:
        """Request the documented public calendar's current 24-hour window."""
        now = datetime.now(UTC)
        window_start = now.replace(hour=0 if now.hour < 12 else 12, minute=0, second=0, microsecond=0)
        window_end = window_start + timedelta(days=1)
        parsed = urlparse(self.schedule_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update({"timeMin": window_start.isoformat().replace("+00:00", "Z"), "timeMax": window_end.isoformat().replace("+00:00", "Z")})
        endpoint = urlunparse(parsed._replace(query=urlencode(query)))
        result = await PoliteFetcher(
            endpoint,
            allowed_hosts={urlparse(self.schedule_url).hostname or ""},
        ).fetch(cursor)
        return FetchResult(
            payload=result.payload,
            cursor=window_start.isoformat(),
            source_url=self.schedule_url,
            fetched_at=result.fetched_at,
            etag=result.etag,
            last_modified=result.last_modified,
            not_modified=result.not_modified,
        )

    @staticmethod
    def _lines(soup: BeautifulSoup) -> Iterable[str]:
        for row in soup.select("tr"):
            line = row.get_text(" ", strip=True)
            if line:
                yield line
        # Some schedule views are cards rather than semantic tables.
        for node in soup.select("article, li, .schedule-item, .transmission"):
            line = node.get_text(" ", strip=True)
            if line:
                yield line

    def parse(self, payload: bytes) -> list[NormalizedRecord]:
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict) and isinstance(decoded.get("items"), list):
            return self._parse_calendar_items(decoded["items"])
        soup = BeautifulSoup(payload, "html.parser")
        records: list[NormalizedRecord] = []
        seen: set[tuple[str, int, str]] = set()
        for line in self._lines(soup):
            frequency = _FREQUENCY.search(line)
            if frequency is None:
                continue
            try:
                frequency_hz = round(float(frequency.group("frequency").replace(",", ".")) * 1_000)
            except ValueError:
                continue
            station_match = _STATION.search(line.upper())
            station = station_match.group("station").replace(" ", "").replace("-", "") if station_match else "Unknown number station"
            time_match = _UTC_TIME.search(line)
            time_utc = time_match.group("time") if time_match else "unscheduled"
            key = (station, frequency_hz, time_utc)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                NormalizedRecord(
                    "FREQUENCY",
                    {
                        "frequency_hz": frequency_hz,
                        "mode": _mode_from_text(line),
                        "label": f"{station} · {frequency_hz / 1_000:g} kHz",
                        "category": "NUMBERS",
                        "station_name": station,
                        "callsigns": [station] if station != "Unknown number station" else [],
                        "schedule": {"utc": time_utc, "source_line": line[:2_000]},
                        "confidence": 0.8,
                        "notes": "Public schedule listing; confirm activity with an observation.",
                    },
                    source_url=self.schedule_url,
                    observed_at=datetime.now(UTC),
                    confidence=0.8,
                    license_notes="Priyom schedule content: CC BY-NC-SA 4.0; preserve attribution.",
                    raw={"source_line": line[:4_000]},
                )
            )
        if not records:
            raise ValueError("no parseable frequency rows found in public schedule response")
        return records

    def _parse_calendar_items(self, items: list[object]) -> list[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        seen: set[tuple[str, int, str]] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or "")
            station_match = _STATION.search(summary.upper())
            station = station_match.group("station").replace(" ", "").replace("-", "") if station_match else "Unknown number station"
            start_value = item.get("start")
            start = start_value.get("dateTime") if isinstance(start_value, dict) else None
            observed_at = _calendar_datetime(start)
            frequencies = list(_FREQUENCY.finditer(summary))
            if not frequencies:
                continue
            mode = _mode_from_text(summary)
            for frequency in frequencies:
                try:
                    frequency_hz = round(float(frequency.group("frequency").replace(",", ".")) * 1_000)
                except ValueError:
                    continue
                key = (station, frequency_hz, str(start or "unscheduled"))
                if key in seen:
                    continue
                seen.add(key)
                records.append(
                    NormalizedRecord(
                        "FREQUENCY",
                        {
                            "frequency_hz": frequency_hz,
                            "mode": mode,
                            "label": f"{station} · {frequency_hz / 1_000:g} kHz",
                            "category": "NUMBERS",
                            "station_name": station,
                            "callsigns": [station] if station != "Unknown number station" else [],
                            "schedule": {"start_at_utc": start, "summary": summary},
                            "confidence": 0.85,
                            "notes": "Public schedule listing; confirm activity with an observation.",
                        },
                        source_url=self.schedule_url,
                        observed_at=observed_at,
                        confidence=0.85,
                        license_notes="Priyom schedule content: CC BY-NC-SA 4.0; preserve attribution.",
                        raw={"calendar_item": item},
                    )
                )
        if not records:
            raise ValueError("no parseable frequency entries found in public calendar response")
        return records


def _calendar_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
