"""California ABC daily licensing reports, narrowed to the Trackstar service area.

ABC publishes three daily statewide reports as ordinary anonymous public pages:
new applications, issued licenses and status changes. The pages are WordPress forms
that post back with a per-page-load nonce, so the adapter loads the report page, reads
the nonce the page itself supplies, and posts it back the way a browser would. No
login, no CAPTCHA and no undocumented endpoint is involved.

The reports are statewide. Trackstar keeps only rows whose premises fall in ABC county
28 (Napa) or 48 (Solano), which is a structured column in the table rather than a guess
from the address text.

Nothing here decides that a business is opening. The adapter emits evidence with the
tenant name the state itself printed, and `business.py` decides what the evidence adds
up to. A row with no DBA carries no brand claim at all.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

REPORT_TYPES: dict[str, dict[str, str]] = {
    "new_applications": {"rpttype": "2", "path": "/licensing/licensing-reports/new-applications/"},
    "issued_licenses": {"rpttype": "1", "path": "/licensing/licensing-reports/issued-licenses/"},
    "status_changes": {"rpttype": "3", "path": "/licensing/licensing-reports/status-changes/"},
}

# ABC numbers counties alphabetically. These two are the whole Trackstar service area.
SERVICE_AREA_COUNTY_CODES: dict[str, str] = {"28": "Napa County", "48": "Solano County"}

# Columns every report shares. Their absence means the published report changed shape.
REQUIRED_COLUMNS = ("License Number", "Primary Owner and Premises Addr.", "City", "County")

_NONCE_FIELD = "abclqs_daily_report"
_ACTION = "abclqs_daily_report"
_DBA_PATTERN = re.compile(r"^DBA:\s*(?P<name>.+)$", re.IGNORECASE)


def _cell_lines(cell: Tag) -> list[str]:
    """Split a cell on its <br> breaks, which is how ABC separates name from address."""

    text = cell.get_text("\n", strip=True)
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def _column_key(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return key or "column"


def _parse_premises(cell: Tag) -> dict[str, Any]:
    """Split the premises cell into the trade name, the owner and the address lines.

    The first line is a DBA only when ABC labelled it one. Without that label the first
    line is the licence holder's own name, and treating it as a storefront brand would
    invent a business that nobody announced.
    """

    lines = _cell_lines(cell)
    if not lines:
        return {"owner_name": None, "dba_name": None, "premises_address_lines": []}

    dba_match = _DBA_PATTERN.match(lines[0])
    if dba_match:
        return {
            "dba_name": dba_match.group("name").strip() or None,
            "owner_name": lines[1] if len(lines) > 1 else None,
            "premises_address_lines": lines[2:],
        }
    return {
        "dba_name": None,
        "owner_name": lines[0],
        "premises_address_lines": lines[1:],
    }


def _parse_date(value: str) -> datetime | None:
    text = " ".join(str(value or "").split())
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class AbcCaAdapter(CollectorAdapter):
    """Daily California ABC licensing reports filtered to Napa and Solano premises."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.base_url = str(config.options.get("base_url") or config.base_url).rstrip("/")
        requested = config.options.get("report_types") or list(REPORT_TYPES)
        self.report_types = [str(item) for item in requested]
        for report_type in self.report_types:
            if report_type not in REPORT_TYPES:
                raise ValueError(f"Unsupported ABC report type: {report_type}")
        self.lookback_days = int(config.options.get("lookback_days", 7))
        self.county_codes = {
            str(code) for code in config.options.get("county_codes", SERVICE_AREA_COUNTY_CODES)
        }
        self.min_interval = float(config.options.get("min_request_interval_seconds", 1.0))
        self.timeout_seconds = float(config.options.get("timeout_seconds", 30))
        self._client = client
        self._last_request_at: float | None = None

    def _report_url(self, report_type: str) -> str:
        return f"{self.base_url}{REPORT_TYPES[report_type]['path']}"

    @property
    def _post_url(self) -> str:
        return f"{self.base_url}/wp-admin/admin-post.php"

    async def _pace(self) -> None:
        if self.min_interval <= 0 or self._last_request_at is None:
            return
        loop = asyncio.get_running_loop()
        delay = self.min_interval - (loop.time() - self._last_request_at)
        if delay > 0:
            await asyncio.sleep(delay)

    @asynccontextmanager
    async def _session(self):
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        ) as client:
            yield client

    @staticmethod
    def _assert_not_challenged(response: httpx.Response) -> None:
        """Stop at a bot challenge instead of trying to look like something else.

        ABC sits behind Cloudflare, which currently answers automated clients with an
        interactive challenge. That is an access control. Trackstar reports it and stops;
        it does not fingerprint-spoof, solve the challenge, or retry until it slips
        through. The source stays unpromoted until a legitimate stable contract exists.
        """

        if response.headers.get("cf-mitigated") == "challenge" or (
            response.status_code == 403 and "challenges.cloudflare.com" in response.text[:4000]
        ):
            raise SourceBlockedError(
                "California ABC answered with a Cloudflare bot challenge. The daily "
                "licensing reports are public, but they are not reachable by an "
                "automated client without defeating an access control."
            )

    async def _request(self, client: httpx.AsyncClient, method: str, url: str, **kwargs) -> str:
        await self._pace()
        try:
            response = await client.request(
                method, url, headers={"User-Agent": "NS-Trackstar/0.1"}, **kwargs
            )
            self._assert_not_challenged(response)
            response.raise_for_status()
            return response.text
        finally:
            self._last_request_at = asyncio.get_running_loop().time()

    @staticmethod
    def _nonce(html: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        field = soup.find("input", attrs={"name": _NONCE_FIELD})
        if not isinstance(field, Tag):
            return None
        value = field.get("value")
        return value if isinstance(value, str) and value else None

    async def _report_page(self, client: httpx.AsyncClient, report_type: str) -> str:
        return await self._request(client, "GET", self._report_url(report_type))

    async def _report_rows(
        self,
        client: httpx.AsyncClient,
        *,
        report_type: str,
        nonce: str,
        report_date: date,
    ) -> tuple[list[str], list[list[str]]]:
        path = REPORT_TYPES[report_type]["path"]
        html = await self._request(
            client,
            "POST",
            self._post_url,
            data={
                "action": _ACTION,
                "url": path,
                "rpttype": REPORT_TYPES[report_type]["rpttype"],
                _NONCE_FIELD: nonce,
                "_wp_http_referer": path,
                "abclqs-date": report_date.strftime("%m/%d/%Y"),
            },
        )
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="license_report")
        if not isinstance(table, Tag):
            return [], []

        rows = table.find_all("tr")
        if not rows:
            return [], []
        header = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
        data_rows = [row.find_all(["th", "td"]) for row in rows[1:]]
        return header, data_rows

    @staticmethod
    def _schema_fingerprint(headers: dict[str, list[str]]) -> str:
        encoded = "|".join(
            f"{report_type}:{','.join(columns)}" for report_type, columns in sorted(headers.items())
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def canary(self) -> bool:
        """The report form and its published column set must both still be there."""

        async with self._session() as client:
            for report_type in self.report_types:
                html = await self._report_page(client, report_type)
                if self._nonce(html) is None:
                    return False
                soup = BeautifulSoup(html, "html.parser")
                form = soup.find("form", id="daily-license-report-form")
                if not isinstance(form, Tag):
                    return False
                if form.find("input", attrs={"name": "rpttype"}) is None:
                    return False
        return True

    async def collect(self) -> CollectorResult:
        today = datetime.now(UTC).date()
        report_dates = [today - timedelta(days=offset) for offset in range(self.lookback_days)]

        records: list[NormalizedRecord] = []
        headers_seen: dict[str, list[str]] = {}
        statewide_rows = 0
        parsed_rows = 0

        async with self._session() as client:
            for report_type in self.report_types:
                page_html = await self._report_page(client, report_type)
                nonce = self._nonce(page_html)
                if nonce is None:
                    raise RuntimeError(
                        f"ABC report page no longer supplies a {_NONCE_FIELD} nonce"
                    )

                for report_date in report_dates:
                    header, rows = await self._report_rows(
                        client,
                        report_type=report_type,
                        nonce=nonce,
                        report_date=report_date,
                    )
                    if not header:
                        # ABC publishes nothing on weekends and holidays. That is a real
                        # answer about the day, not a broken request.
                        continue

                    headers_seen.setdefault(report_type, header)
                    missing = [column for column in REQUIRED_COLUMNS if column not in header]
                    if missing:
                        raise RuntimeError(
                            f"ABC {report_type} report columns changed; missing: {missing}"
                        )

                    index = {label: position for position, label in enumerate(header)}
                    county_at = index["County"]
                    licence_at = index["License Number"]
                    premises_at = index["Primary Owner and Premises Addr."]
                    statewide_rows += len(rows)

                    for cells in rows:
                        if len(cells) <= max(county_at, licence_at, premises_at):
                            continue
                        parsed_rows += 1
                        county_code = cells[county_at].get_text(" ", strip=True).strip()
                        if county_code not in self.county_codes:
                            continue

                        licence_number = cells[licence_at].get_text(" ", strip=True).strip()
                        if not licence_number:
                            continue

                        payload: dict[str, Any] = {
                            column: cells[position].get_text(" ", strip=True)
                            for column, position in index.items()
                            if position < len(cells)
                        }
                        normalized = {_column_key(key): value for key, value in payload.items()}
                        normalized.update(_parse_premises(cells[premises_at]))
                        normalized["report_type"] = report_type
                        normalized["report_date"] = report_date.isoformat()
                        normalized["county"] = SERVICE_AREA_COUNTY_CODES.get(
                            county_code, county_code
                        )
                        normalized["abc_county_code"] = county_code
                        normalized["license_number"] = licence_number
                        normalized["business_name"] = normalized.get("dba_name")

                        canonical_url = (
                            f"{self.base_url}/licensing/license-lookup/single-license/"
                            f"?RPTTYPE=12&LICENSE={licence_number}"
                        )
                        records.append(
                            NormalizedRecord(
                                source_key=self.config.key,
                                external_id=f"{report_type}:{report_date.isoformat()}"
                                f":{licence_number}:{normalized.get('type_dup', '')}".strip(":"),
                                canonical_url=canonical_url,
                                source_updated_at=datetime.combine(
                                    report_date, datetime.min.time(), tzinfo=UTC
                                ),
                                source_created_at=_parse_date(
                                    payload.get("Original Issue Date", "")
                                ),
                                raw_payload=payload,
                                normalized_payload=normalized,
                            )
                        )

        if statewide_rows == 0:
            # Every queried day empty statewide means the post-back stopped working, not
            # that California issued no licences all week.
            raise RuntimeError(
                "ABC daily reports returned no statewide rows across "
                f"{self.lookback_days} days; the report workflow is not returning data"
            )

        return CollectorResult(
            records=records,
            schema_fingerprint=self._schema_fingerprint(headers_seen),
            parser_yield=len(records) / parsed_rows if parsed_rows else 1.0,
            metadata={
                "statewide_rows_seen": statewide_rows,
                "service_area_rows": len(records),
                "report_types": sorted(headers_seen),
                "lookback_days": self.lookback_days,
            },
        )
