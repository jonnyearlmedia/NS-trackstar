from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

_RECORD_KINDS = {"permit", "project"}


def _text(tag: Tag | None) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


def _attribute(tag: Tag, name: str) -> str:
    value = tag.get(name)
    return value if isinstance(value, str) else ""


def _find_control(soup: BeautifulSoup, suffix: str) -> Tag | None:
    needle = suffix.casefold()
    for tag in soup.find_all(["input", "select", "button"]):
        tag_id = _attribute(tag, "id").casefold()
        tag_name = _attribute(tag, "name").casefold()
        if tag_id.endswith(needle) or tag_name.endswith(needle):
            return tag
    return None


def _label(soup: BeautifulSoup, suffix: str) -> str:
    needle = suffix.casefold()
    for tag in soup.find_all(["span", "div", "td"]):
        tag_id = _attribute(tag, "id").casefold()
        if tag_id.endswith(needle):
            value = _text(tag)
            if value:
                return value
    return ""


def _site_address(soup: BeautifulSoup) -> str:
    for tag in soup.find_all("a"):
        if "hlsiteaddress" in _attribute(tag, "id").casefold():
            return _text(tag)
    return ""


def _apn(soup: BeautifulSoup) -> str:
    for tag in soup.find_all("a", href=True):
        href = _attribute(tag, "href").casefold()
        if "parcel.aspx?activityno=" in href:
            value = _text(tag)
            if value:
                return value
    return ""


def _contacts(soup: BeautifulSoup) -> list[dict[str, str]]:
    container: Tag | None = None
    for tag in soup.find_all(True):
        if "rgcontactinfo" in _attribute(tag, "id").casefold():
            container = tag
            break
    if container is None:
        return []

    contacts: list[dict[str, str]] = []
    for row in container.find_all("tr"):
        cells = [_text(cell) for cell in row.find_all("td")]
        if len(cells) < 2 or not cells[0] or not cells[1]:
            continue
        contact = {"role": cells[0], "name": cells[1]}
        for key, index in (
            ("phone", 2),
            ("email", 3),
            ("address", 4),
            ("city_state_zip", 5),
        ):
            if len(cells) > index and cells[index]:
                contact[key] = cells[index]
        contacts.append(contact)
    return contacts


def _linked_parents(soup: BeautifulSoup, current_number: str) -> list[str]:
    parents: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = _attribute(tag, "href")
        title = _attribute(tag, "title")
        if "permit.aspx?activityNo=" not in href or "parent" not in title.casefold():
            continue
        value = _text(tag)
        if value and value != current_number and value not in parents:
            parents.append(value)
    return parents


def _interesting_grids(soup: BeautifulSoup) -> dict[str, list[list[str]]]:
    keywords = ("inspection", "chron", "condition", "review")
    grids: dict[str, list[list[str]]] = {}
    for table in soup.find_all("table"):
        table_id = _attribute(table, "id")
        if not table_id or not any(word in table_id.casefold() for word in keywords):
            continue
        rows: list[list[str]] = []
        for row in table.find_all("tr"):
            cells = [_text(cell) for cell in row.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        if rows:
            grids[table_id] = rows
    return grids


def _parse_source_date(value: str, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    candidates = (
        "%m/%d/%Y",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%Y-%m-%d",
    )
    for format_string in candidates:
        try:
            return datetime.strptime(value.strip(), format_string).replace(tzinfo=timezone)
        except ValueError:
            continue
    return None


def _form_values(soup: BeautifulSoup) -> dict[str, str]:
    data: dict[str, str] = {}
    for field in soup.find_all("input"):
        name = _attribute(field, "name")
        if not name:
            continue
        field_type = _attribute(field, "type").casefold()
        if field_type in {"submit", "button", "image", "file"}:
            continue
        if field_type in {"checkbox", "radio"} and not field.has_attr("checked"):
            continue
        data[name] = _attribute(field, "value")

    for select in soup.find_all("select"):
        name = _attribute(select, "name")
        if not name:
            continue
        option = select.find("option", selected=True) or select.find("option")
        data[name] = _attribute(option, "value") if isinstance(option, Tag) else ""
    return data


def _option_value(
    select: Tag,
    *,
    requested_value: str | None,
    requested_label: str | None,
) -> str:
    options = [option for option in select.find_all("option") if isinstance(option, Tag)]
    if requested_value:
        for option in options:
            if _attribute(option, "value") == requested_value:
                return requested_value
        raise ValueError(f"eTRAKiT search option value not found: {requested_value}")

    if requested_label:
        requested = requested_label.casefold()
        for option in options:
            if requested in _text(option).casefold():
                return _attribute(option, "value")
        raise ValueError(f"eTRAKiT search option label not found: {requested_label}")

    selected = select.find("option", selected=True) or select.find("option")
    if isinstance(selected, Tag):
        return _attribute(selected, "value")
    raise ValueError("eTRAKiT select has no options")


def _activity_numbers(soup: BeautifulSoup, kind: str) -> list[str]:
    results: list[str] = []
    expected_path = f"{kind}.aspx"
    for link in soup.find_all("a", href=True):
        href = _attribute(link, "href")
        parsed = urlparse(href)
        if not parsed.path.casefold().endswith(expected_path.casefold()):
            continue
        query = parse_qs(parsed.query)
        values = query.get("activityNo") or query.get("activityno")
        if not values:
            continue
        number = values[0].strip()
        if number and number not in results:
            results.append(number)

    # Current eTRAKiT tenants render Telerik search results as plain table cells.
    # The record number is not a link, while a hidden RECORDID cell carries an
    # internal database key. Keep using the public activity number from the first
    # visible column so detail retrieval remains tenant-independent.
    for table in soup.find_all("table"):
        table_id = _attribute(table, "id").casefold()
        if "rgsearchrslts" not in table_id:
            continue
        for row in table.find_all("tr"):
            row_classes = {
                str(value).casefold() for value in (row.get("class") or [])
            }
            if not row_classes.intersection({"rgrow", "rgaltrow"}):
                continue
            cells = row.find_all("td", recursive=False)
            if not cells:
                cells = row.find_all("td")
            if not cells:
                continue
            number = _text(cells[0]).strip()
            if number and number not in results:
                results.append(number)
    return results


def _next_results_control(soup: BeautifulSoup) -> Tag | None:
    for tag in soup.find_all(["input", "button"]):
        descriptor = " ".join(
            [
                _attribute(tag, "id"),
                _attribute(tag, "name"),
                _attribute(tag, "value"),
                " ".join(str(value) for value in (tag.get("class") or [])),
                _text(tag),
            ]
        ).casefold()
        if not any(
            marker in descriptor
            for marker in ("more result", "moreresult", "btnpagenext", "nextpage")
        ):
            continue
        if tag.has_attr("disabled"):
            continue
        style = _attribute(tag, "style").replace(" ", "").casefold()
        if "display:none" in style:
            continue
        return tag
    return None


class ETrakitAdapter(CollectorAdapter):
    """Public eTRAKiT search/detail collector for permits and planning projects.

    The adapter discovers live ASP.NET control names from each tenant instead of assuming
    one city's generated control prefix. Source configs specify search intent, not HTML IDs.
    """

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.base_url = str(config.options.get("base_url") or config.base_url).rstrip("/")
        self.searches = list(config.options.get("searches") or [])
        self.explicit_records = list(config.options.get("explicit_records") or [])
        self.discovery_partitions = list(config.options.get("discovery_partitions") or [])
        self.max_candidates_per_run = int(config.options.get("max_candidates_per_run", 600))
        self.canary_kinds = list(config.options.get("canary_kinds") or ["permit", "project"])
        self.max_result_pages = int(config.options.get("max_result_pages", 10))
        self.min_interval = float(config.options.get("min_request_interval_seconds", 1.0))
        self.timezone = ZoneInfo(str(config.options.get("timezone", "America/Los_Angeles")))
        self._client = client
        self._last_request_at: float | None = None

        for kind in self.canary_kinds:
            self._validate_kind(str(kind))

    @staticmethod
    def _validate_kind(kind: str) -> None:
        if kind not in _RECORD_KINDS:
            raise ValueError(f"Unsupported eTRAKiT record kind: {kind}")

    def _search_url(self, kind: str) -> str:
        self._validate_kind(kind)
        return f"{self.base_url}/Search/{kind}.aspx"

    async def _pace(self) -> None:
        if self.min_interval <= 0 or self._last_request_at is None:
            return
        loop = asyncio.get_running_loop()
        delay = self.min_interval - (loop.time() - self._last_request_at)
        if delay > 0:
            await asyncio.sleep(delay)

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
    ) -> str:
        await self._pace()
        try:
            response = await client.request(
                method,
                url,
                data=data,
                headers={"User-Agent": "NS-Trackstar/0.1"},
            )
            response.raise_for_status()
            return response.text
        finally:
            self._last_request_at = asyncio.get_running_loop().time()

    @asynccontextmanager
    async def _session(self):
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            yield client

    @staticmethod
    def _assert_search_form(soup: BeautifulSoup) -> None:
        missing = [
            suffix
            for suffix in ("ddSearchBy", "ddSearchOper", "txtSearchString", "btnSearch")
            if _find_control(soup, suffix) is None
        ]
        if missing:
            raise RuntimeError(f"eTRAKiT public search schema changed; missing controls: {missing}")

    async def canary(self) -> bool:
        async with self._session() as client:
            for kind_value in self.canary_kinds:
                kind = str(kind_value)
                html = await self._request(client, "GET", self._search_url(kind))
                soup = BeautifulSoup(html, "html.parser")
                try:
                    self._assert_search_form(soup)
                except RuntimeError:
                    return False
        return True

    def _search_post_data(self, soup: BeautifulSoup, query: dict[str, Any]) -> dict[str, str]:
        self._assert_search_form(soup)
        search_by = _find_control(soup, "ddSearchBy")
        operator = _find_control(soup, "ddSearchOper")
        search_string = _find_control(soup, "txtSearchString")
        search_button = _find_control(soup, "btnSearch")
        assert search_by is not None and operator is not None
        assert search_string is not None and search_button is not None

        data = _form_values(soup)
        search_by_name = _attribute(search_by, "name")
        operator_name = _attribute(operator, "name")
        search_name = _attribute(search_string, "name")
        button_name = _attribute(search_button, "name")
        if not all((search_by_name, operator_name, search_name, button_name)):
            raise RuntimeError("eTRAKiT search controls are missing ASP.NET names")

        data["__EVENTTARGET"] = button_name
        data["__EVENTARGUMENT"] = ""
        data[search_by_name] = _option_value(
            search_by,
            requested_value=query.get("search_by_value"),
            requested_label=query.get("search_by_label"),
        )
        data[operator_name] = _option_value(
            operator,
            requested_value=query.get("operator_value"),
            requested_label=query.get("operator_label"),
        )
        data[search_name] = str(query["value"])
        data.pop(button_name, None)
        return data

    async def _search_ids(
        self,
        client: httpx.AsyncClient,
        query: dict[str, Any],
    ) -> list[tuple[str, str]]:
        kind = str(query["kind"])
        self._validate_kind(kind)
        search_url = self._search_url(kind)
        initial_html = await self._request(client, "GET", search_url)
        soup = BeautifulSoup(initial_html, "html.parser")
        post_data = self._search_post_data(soup, query)
        result_html = await self._request(client, "POST", search_url, data=post_data)

        records: list[tuple[str, str]] = []
        seen_pages: set[str] = set()
        max_pages = int(query.get("max_pages", self.max_result_pages))

        for _ in range(max_pages):
            page_hash = hashlib.sha256(result_html.encode()).hexdigest()
            if page_hash in seen_pages:
                break
            seen_pages.add(page_hash)
            result_soup = BeautifulSoup(result_html, "html.parser")
            for record_number in _activity_numbers(result_soup, kind):
                candidate = (kind, record_number)
                if candidate not in records:
                    records.append(candidate)

            next_control = _next_results_control(result_soup)
            if next_control is None:
                break
            target = _attribute(next_control, "name")
            if not target:
                break
            next_data = _form_values(result_soup)
            next_data["__EVENTTARGET"] = target
            next_data["__EVENTARGUMENT"] = ""
            next_data.pop(target, None)
            result_html = await self._request(client, "POST", search_url, data=next_data)

        return records

    def _detail_record(self, kind: str, number: str, html: str, url: str) -> NormalizedRecord | None:
        soup = BeautifulSoup(html, "html.parser")
        if kind == "permit":
            record_type = _label(soup, "lblPermitType")
            if not record_type:
                return None
            normalized: dict[str, Any] = {
                "record_kind": "permit",
                "record_number": number,
                "type": record_type,
                "subtype": _label(soup, "lblPermitSubtype"),
                "description": _label(soup, "lblPermitDesc"),
                "status": _label(soup, "lblPermitStatus"),
                "applied_date": _label(soup, "lblPermitAppliedDate"),
                "approved_date": _label(soup, "lblPermitApprovedDate"),
                "issued_date": _label(soup, "lblPermitIssuedDate"),
                "address": _site_address(soup),
                "apn": _apn(soup),
            }
            applied = _parse_source_date(str(normalized["applied_date"]), self.timezone)
        else:
            record_type = _label(soup, "lblProjectType")
            if not record_type:
                return None
            normalized = {
                "record_kind": "project",
                "record_number": number,
                "type": record_type,
                "name": _label(soup, "lblProjectName"),
                "description": _label(soup, "lblProjectDesc"),
                "status": _label(soup, "lblProjectStatus"),
                "applied_date": _label(soup, "lblProjectAppliedDate"),
                "approved_date": _label(soup, "lblProjectApprovedDate"),
                "planner": _label(soup, "lblProjectPlanner"),
                "address": _site_address(soup),
                "apn": _apn(soup),
            }
            applied = _parse_source_date(str(normalized["applied_date"]), self.timezone)

        normalized["site_city_state_zip"] = _label(soup, "lblSiteCityStateZip")
        normalized["lot_sqft"] = _label(soup, "lblSiteLotSqFt")
        normalized["property_type"] = _label(soup, "lblPropertyType")
        contacts = _contacts(soup)
        if contacts:
            normalized["contacts"] = contacts
        parents = _linked_parents(soup, number)
        if parents:
            normalized["linked_parent_records"] = parents
        grids = _interesting_grids(soup)
        if grids:
            normalized["detail_grids"] = grids

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=f"{kind}:{number}",
            canonical_url=url,
            source_created_at=applied,
            raw_payload={
                "record_kind": kind,
                "record_number": number,
                "html_sha256": hashlib.sha256(html.encode()).hexdigest(),
            },
            normalized_payload=normalized,
        )

    async def _fetch_record(
        self,
        client: httpx.AsyncClient,
        kind: str,
        number: str,
    ) -> NormalizedRecord | None:
        self._validate_kind(kind)
        url = f"{self._search_url(kind)}?activityNo={quote(number, safe='-_.')}"
        html = await self._request(client, "GET", url)
        return self._detail_record(kind, number, html, url)

    def _partition_queries(self, *, today: datetime | None = None) -> list[dict[str, Any]]:
        """Expand recurring discovery into bounded, dated prefix searches.

        eTRAKiT has no "what changed recently" endpoint, so discovery has to walk the
        record-number space. Walking it blindly would mean an unbounded crawl of a small
        city's server. Instead each partition is one record-number prefix for one year,
        with its own page cap, so a run is the same predictable size every time and the
        set moves forward on its own in January without anyone editing the config.
        """

        reference = today or datetime.now(self.timezone)
        queries: list[dict[str, Any]] = []
        for partition in self.discovery_partitions:
            kind = str(partition["kind"])
            self._validate_kind(kind)
            year_format = str(partition.get("year_format", "%y"))
            years_back = int(partition.get("years_back", 1))
            years = [reference.year - offset for offset in range(years_back + 1)]
            for prefix in partition.get("prefixes") or []:
                for year in years:
                    stamp = datetime(year, 1, 1, tzinfo=self.timezone).strftime(year_format)
                    queries.append(
                        {
                            "kind": kind,
                            "search_by_value": partition["search_by_value"],
                            "operator_value": "BEGINS WITH",
                            "value": f"{prefix}{stamp}",
                            "max_pages": int(partition.get("max_pages", 3)),
                        }
                    )
        return queries

    def _partition_plan(
        self, *, today: datetime | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """Order the partitions for this run and decide how much budget each one gets.

        Spending the budget first-come starves the partitions at the end of the list:
        with eleven partitions and a budget of 500, the first five consume it and the
        rest are never discovered on any run, because the query order is deterministic.
        So every partition gets an equal share of the budget, and the order rotates
        daily so the remainder does not always land on the same one.
        """

        queries = self._partition_queries(today=today)
        if not queries:
            return [], self.max_candidates_per_run

        reference = today or datetime.now(self.timezone)
        offset = reference.toordinal() % len(queries)
        rotated = queries[offset:] + queries[:offset]
        return rotated, max(1, self.max_candidates_per_run // len(queries))

    async def collect(self) -> CollectorResult:
        candidates: list[tuple[str, str]] = []
        for item in self.explicit_records:
            kind = str(item["kind"])
            number = str(item["id"])
            self._validate_kind(kind)
            candidate = (kind, number)
            if candidate not in candidates:
                candidates.append(candidate)

        partition_queries, partition_share = self._partition_plan()
        truncated = False

        async with self._session() as client:
            # Explicitly configured searches are deliberate and keep the whole budget.
            for query_value in self.searches:
                for candidate in await self._search_ids(client, dict(query_value)):
                    if candidate not in candidates:
                        candidates.append(candidate)
                if len(candidates) >= self.max_candidates_per_run:
                    truncated = True
                    break

            if not truncated:
                for query_value in partition_queries:
                    taken = 0
                    for candidate in await self._search_ids(client, dict(query_value)):
                        if candidate in candidates:
                            continue
                        candidates.append(candidate)
                        taken += 1
                        if taken >= partition_share:
                            break
                    if len(candidates) >= self.max_candidates_per_run:
                        truncated = True
                        break

            records: list[NormalizedRecord] = []
            missing = 0
            for kind, number in candidates[: self.max_candidates_per_run]:
                record = await self._fetch_record(client, kind, number)
                if record is None:
                    missing += 1
                    continue
                records.append(record)

        attempted = min(len(candidates), self.max_candidates_per_run)
        parser_yield = len(records) / attempted if attempted else 1.0
        return CollectorResult(
            records=records,
            parser_yield=parser_yield,
            metadata={
                "candidates": attempted,
                "records_missing": missing,
                "search_queries": len(self.searches),
                "discovery_partitions": len(partition_queries),
                "candidates_per_partition": partition_share,
                "explicit_records": len(self.explicit_records),
                "candidate_budget_reached": truncated,
            },
        )
