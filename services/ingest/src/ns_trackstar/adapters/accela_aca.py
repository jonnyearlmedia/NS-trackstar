from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
RETRY_DELAYS_SECONDS = (2.0, 10.0, 30.0)


def _attribute(tag: Tag | None, name: str) -> str:
    if tag is None:
        return ""
    value = tag.get(name)
    return value if isinstance(value, str) else ""


def _text(tag: Tag | None) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


def _find_control(soup: BeautifulSoup, suffix: str) -> Tag | None:
    needle = suffix.casefold()
    for tag in soup.find_all(["input", "select", "button", "a"]):
        tag_id = _attribute(tag, "id").casefold()
        tag_name = _attribute(tag, "name").casefold()
        if tag_id.endswith(needle) or tag_name.endswith(needle):
            return tag
    return None


def _form_values(soup: BeautifulSoup) -> dict[str, str]:
    form = soup.find("form", id="aspnetForm") or soup.find("form")
    if not isinstance(form, Tag):
        raise RuntimeError("Accela ACA response is missing its ASP.NET form")

    data: dict[str, str] = {}
    for field in form.find_all("input"):
        name = _attribute(field, "name")
        if not name or field.has_attr("disabled"):
            continue
        field_type = _attribute(field, "type").casefold()
        if field_type in {"button", "submit", "image", "file"}:
            continue
        if field_type in {"checkbox", "radio"} and not field.has_attr("checked"):
            continue
        data[name] = _attribute(field, "value")

    for select in form.find_all("select"):
        name = _attribute(select, "name")
        if not name or select.has_attr("disabled"):
            continue
        option = select.find("option", selected=True) or select.find("option")
        data[name] = _attribute(option, "value") if isinstance(option, Tag) else ""

    for textarea in form.find_all("textarea"):
        name = _attribute(textarea, "name")
        if name and not textarea.has_attr("disabled"):
            data[name] = textarea.get_text()

    return data


def _postback(tag: Tag | None) -> tuple[str, str] | None:
    if tag is None:
        return None
    href = _attribute(tag, "href")
    if href:
        match = re.search(
            r"__doPostBack\(['\"]([^'\"]+)['\"],['\"]([^'\"]*)['\"]\)",
            href,
        )
        if match:
            return match.group(1), match.group(2)
    name = _attribute(tag, "name")
    return (name, "") if name else None


def _set_control_value(
    data: dict[str, str],
    soup: BeautifulSoup,
    suffix: str,
    value: str,
) -> bool:
    control = _find_control(soup, suffix)
    name = _attribute(control, "name")
    if not name:
        return False
    data[name] = value
    return True


def _result_table(soup: BeautifulSoup) -> Tag | None:
    candidates: list[Tag] = []
    for table in soup.find_all("table"):
        table_id = _attribute(table, "id").casefold()
        if "permitlist" in table_id:
            candidates.append(table)
    for table in candidates:
        headers = {_text(cell).casefold() for cell in table.find_all("th")}
        if "record number" in headers:
            return table
    return candidates[0] if candidates else None


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _cap_id_parts(url: str) -> tuple[str, str, str] | None:
    query = parse_qs(urlparse(url).query)
    parts = tuple((query.get(name) or [""])[0] for name in ("capID1", "capID2", "capID3"))
    return parts if all(parts) else None


def _parse_result_rows(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    table = _result_table(soup)
    if table is None:
        return []

    rows = table.find_all("tr")
    header_index: int | None = None
    headers: list[str] = []
    for index, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        labels = [_text(cell) for cell in cells]
        if any(label.casefold() == "record number" for label in labels):
            header_index = index
            headers = [_normalize_header(label) or f"column_{position}" for position, label in enumerate(labels)]
            break
    if header_index is None:
        return []

    records: list[dict[str, Any]] = []
    for row in rows[header_index + 1 :]:
        cells = row.find_all("td")
        if not cells or len(cells) != len(headers):
            continue
        detail_link = row.find("a", href=lambda value: isinstance(value, str) and "CapDetail.aspx" in value)
        if not isinstance(detail_link, Tag):
            continue
        values = [_text(cell) for cell in cells]
        record = dict(zip(headers, values))
        canonical_url = urljoin(base_url, _attribute(detail_link, "href"))
        record["_canonical_url"] = canonical_url
        cap_parts = _cap_id_parts(canonical_url)
        if cap_parts:
            record["_cap_id_parts"] = list(cap_parts)
        records.append(record)
    return records


def _next_page_postback(soup: BeautifulSoup) -> tuple[str, str] | None:
    for link in soup.find_all("a", href=True):
        label = _text(link).casefold()
        if not label.startswith("next"):
            continue
        postback = _postback(link)
        if postback and "permitlist" in postback[0].casefold():
            return postback
    return None


def _detail_value(soup: BeautifulSoup, suffix: str) -> str:
    needle = suffix.casefold()
    for tag in soup.find_all(True):
        if _attribute(tag, "id").casefold().endswith(needle):
            return _text(tag)
    return ""


def _parse_detail(soup: BeautifulSoup) -> dict[str, str]:
    detail = {
        "record_number": _detail_value(soup, "lblPermitNumber"),
        "record_type": _detail_value(soup, "lblPermitType"),
        "status": _detail_value(soup, "lblRecordStatus"),
        "expiration_date": _detail_value(soup, "lblExpirtionDate"),
        "work_location": _detail_value(soup, "tbl_worklocation"),
        "licensed_professionals": _detail_value(soup, "tbl_licensedps"),
    }

    plain_text = soup.get_text(" ", strip=True)
    parcel_match = re.search(r"Parcel Number:\s*([A-Za-z0-9.-]+)", plain_text, re.IGNORECASE)
    if parcel_match:
        detail["parcel_number"] = parcel_match.group(1)

    for heading in soup.find_all(["h1", "h2", "h3", "span", "div"]):
        heading_id = _attribute(heading, "id").casefold()
        if "label_project" not in heading_id:
            continue
        table = heading.find_next("table")
        if isinstance(table, Tag):
            detail["project_description"] = _text(table)
            break

    return {key: value for key, value in detail.items() if value}


def _schema_fingerprint(records: list[dict[str, Any]]) -> str | None:
    if not records:
        return None
    keys = sorted({key for record in records[:25] for key in record if not key.startswith("_")})
    return hashlib.sha256(json.dumps(keys, separators=(",", ":")).encode()).hexdigest()


def _parse_date(value: Any, timezone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for format_string in ("%m/%d/%Y", "%m/%d/%Y %I:%M %p", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, format_string).replace(tzinfo=timezone)
        except ValueError:
            continue
    return None


class AccelaAcaAdapter(CollectorAdapter):
    """Collect anonymous Accela Citizen Access records through its public WebForms UI."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.base_url = str(config.options.get("base_url") or config.base_url).rstrip("/")
        self.modules = [str(value) for value in config.options.get("modules", []) if str(value)]
        if not self.modules:
            raise ValueError("Accela ACA requires at least one configured module")
        self.lookback_days = max(int(config.options.get("lookback_days", 14)), 0)
        self.lookahead_days = max(int(config.options.get("lookahead_days", 0)), 0)
        self.max_pages = max(int(config.options.get("max_pages", 25)), 1)
        self.fetch_details = bool(config.options.get("fetch_details", True))
        self.min_interval = float(config.options.get("min_request_interval_seconds", 1.0))
        self.timezone = ZoneInfo(str(config.options.get("timezone", "America/Los_Angeles")))
        self.canary_records = {
            str(key): str(value)
            for key, value in dict(config.options.get("canary_records") or {}).items()
            if str(key) and str(value)
        }
        self._client = client
        self._last_request_at: float | None = None
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Accela ACA base_url must be HTTPS")
        self._allowed_host = parsed.hostname

    def _search_url(self, module: str) -> str:
        return f"{self.base_url}/Cap/CapHome.aspx?module={module}"

    async def _pace(self) -> None:
        if self.min_interval <= 0 or self._last_request_at is None:
            return
        delay = self.min_interval - (asyncio.get_running_loop().time() - self._last_request_at)
        if delay > 0:
            await asyncio.sleep(delay)

    @asynccontextmanager
    async def _session(self):
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(
            timeout=45,
            follow_redirects=True,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "NS-Trackstar/0.1",
            },
        ) as client:
            yield client

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
    ) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != self._allowed_host:
            raise RuntimeError("Accela ACA request attempted to leave the configured public host")
        await self._pace()
        try:
            for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
                try:
                    response = await client.request(method, url, data=data)
                except httpx.RequestError as exc:
                    if attempt >= len(RETRY_DELAYS_SECONDS):
                        raise RuntimeError(
                            f"Accela ACA request failed: {type(exc).__name__}"
                        ) from None
                    await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt] + random.random())
                    continue

                if response.status_code in {401, 403}:
                    raise SourceBlockedError(
                        f"Accela ACA public portal rejected access with HTTP {response.status_code}"
                    )
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt >= len(RETRY_DELAYS_SECONDS):
                        raise RuntimeError(
                            f"Accela ACA public portal failed with HTTP {response.status_code}"
                        )
                    await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt] + random.random())
                    continue
                response.raise_for_status()
                final_url = urlparse(str(response.url))
                if final_url.hostname != self._allowed_host:
                    raise RuntimeError("Accela ACA redirected outside the configured public host")
                return response.text
        finally:
            self._last_request_at = asyncio.get_running_loop().time()

        raise RuntimeError("Accela ACA request exhausted retries")

    @staticmethod
    def _assert_search_contract(soup: BeautifulSoup) -> None:
        data = _form_values(soup)
        if "__VIEWSTATE" not in data or "ACA_CS_FIELD" not in data:
            raise RuntimeError("Accela ACA search form is missing view-state/CSRF controls")
        missing = [
            suffix
            for suffix in ("txtGSStartDate", "txtGSEndDate", "btnNewSearch")
            if _find_control(soup, suffix) is None
        ]
        if missing:
            raise RuntimeError(f"Accela ACA search schema changed; missing controls: {missing}")

    def _search_post_data(
        self,
        soup: BeautifulSoup,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        record_number: str | None = None,
    ) -> dict[str, str]:
        self._assert_search_contract(soup)
        data = _form_values(soup)
        search_button = _find_control(soup, "btnNewSearch")
        postback = _postback(search_button)
        if postback is None:
            raise RuntimeError("Accela ACA search button has no usable postback target")
        data["__EVENTTARGET"], data["__EVENTARGUMENT"] = postback

        search_type = _find_control(soup, "ddlSearchType")
        search_type_name = _attribute(search_type, "name")
        if search_type_name:
            data[search_type_name] = "General Search"

        if start_date is not None and not _set_control_value(
            data, soup, "txtGSStartDate", start_date
        ):
            raise RuntimeError("Accela ACA start-date control disappeared")
        if end_date is not None and not _set_control_value(data, soup, "txtGSEndDate", end_date):
            raise RuntimeError("Accela ACA end-date control disappeared")
        if record_number is not None:
            record_suffixes = ("txtGSPermitNumber", "txtGSRecordNumber", "txtGSNumber")
            if not any(
                _set_control_value(data, soup, suffix, record_number)
                for suffix in record_suffixes
            ):
                raise RuntimeError("Accela ACA record-number control was not found")
        return data

    async def _search(
        self,
        client: httpx.AsyncClient,
        module: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        record_number: str | None = None,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        search_url = self._search_url(module)
        initial_html = await self._request(client, "GET", search_url)
        initial_soup = BeautifulSoup(initial_html, "html.parser")
        post_data = self._search_post_data(
            initial_soup,
            start_date=start_date,
            end_date=end_date,
            record_number=record_number,
        )
        result_html = await self._request(client, "POST", search_url, data=post_data)

        records: list[dict[str, Any]] = []
        seen_pages: set[str] = set()
        page_limit = max_pages or self.max_pages
        for _ in range(page_limit):
            page_hash = hashlib.sha256(result_html.encode()).hexdigest()
            if page_hash in seen_pages:
                break
            seen_pages.add(page_hash)
            soup = BeautifulSoup(result_html, "html.parser")
            for record in _parse_result_rows(soup, self.base_url):
                if record not in records:
                    records.append(record)

            next_postback = _next_page_postback(soup)
            if next_postback is None:
                break
            next_data = _form_values(soup)
            next_data["__EVENTTARGET"], next_data["__EVENTARGUMENT"] = next_postback
            result_html = await self._request(client, "POST", search_url, data=next_data)
        return records

    async def _detail(
        self,
        client: httpx.AsyncClient,
        canonical_url: str,
    ) -> dict[str, str]:
        html = await self._request(client, "GET", canonical_url)
        return _parse_detail(BeautifulSoup(html, "html.parser"))

    def _record(
        self,
        *,
        module: str,
        row: dict[str, Any],
        detail: dict[str, str],
    ) -> NormalizedRecord | None:
        record_number = str(
            detail.get("record_number") or row.get("record_number") or ""
        ).strip()
        if not record_number:
            return None
        canonical_url = str(row.get("_canonical_url") or self._search_url(module))
        submitted = (
            row.get("date")
            or row.get("date_submitted")
            or row.get("file_date")
            or row.get("application_date")
        )
        normalized = {
            "record_kind": "accela_record",
            "module": module,
            "record_number": record_number,
            "record_type": detail.get("record_type") or row.get("record_type"),
            "project_name": row.get("project_name"),
            "description": row.get("description") or detail.get("project_description"),
            "address": row.get("address") or detail.get("work_location"),
            "status": detail.get("status") or row.get("status"),
            "date_submitted": submitted,
            "expiration_date": detail.get("expiration_date"),
            "parcel_number": detail.get("parcel_number"),
            "licensed_professionals": detail.get("licensed_professionals"),
            "cap_id_parts": row.get("_cap_id_parts"),
        }
        normalized = {key: value for key, value in normalized.items() if value not in (None, "", [])}
        raw_row = {key: value for key, value in row.items() if not key.startswith("_")}
        return NormalizedRecord(
            source_key=self.config.key,
            external_id=f"{module}:{record_number}",
            canonical_url=canonical_url,
            source_created_at=_parse_date(submitted, self.timezone),
            raw_payload={"module": module, "search_row": raw_row, "detail": detail},
            normalized_payload=normalized,
        )

    async def canary(self) -> bool:
        async with self._session() as client:
            for module in self.modules:
                html = await self._request(client, "GET", self._search_url(module))
                soup = BeautifulSoup(html, "html.parser")
                try:
                    self._assert_search_contract(soup)
                except RuntimeError:
                    return False

                known_record = self.canary_records.get(module)
                if known_record:
                    rows = await self._search(
                        client,
                        module,
                        record_number=known_record,
                        max_pages=2,
                    )
                    if not any(
                        str(row.get("record_number") or "").strip() == known_record
                        for row in rows
                    ):
                        return False
        return True

    async def collect(self) -> CollectorResult:
        today = datetime.now(self.timezone).date()
        start_date = (today - timedelta(days=self.lookback_days)).strftime("%m/%d/%Y")
        end_date = (today + timedelta(days=self.lookahead_days)).strftime("%m/%d/%Y")
        records: list[NormalizedRecord] = []
        raw_rows: list[dict[str, Any]] = []
        skipped = 0
        module_counts: dict[str, int] = {}

        async with self._session() as client:
            for module in self.modules:
                rows = await self._search(
                    client,
                    module,
                    start_date=start_date,
                    end_date=end_date,
                )
                module_counts[module] = len(rows)
                raw_rows.extend(rows)
                for row in rows:
                    canonical_url = str(row.get("_canonical_url") or "")
                    detail: dict[str, str] = {}
                    if self.fetch_details and canonical_url:
                        detail = await self._detail(client, canonical_url)
                    record = self._record(module=module, row=row, detail=detail)
                    if record is None:
                        skipped += 1
                        continue
                    records.append(record)

        attempted = len(raw_rows)
        return CollectorResult(
            records=records,
            schema_fingerprint=_schema_fingerprint(raw_rows),
            parser_yield=len(records) / attempted if attempted else 1.0,
            metadata={
                "window_start": start_date,
                "window_end": end_date,
                "modules": module_counts,
                "rows_seen": attempted,
                "rows_skipped": skipped,
                "detail_fetch": self.fetch_details,
            },
        )
