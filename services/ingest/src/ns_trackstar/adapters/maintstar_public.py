"""MaintStar Land Management public permit search.

MaintStar hosts each agency's permit portal as a tenant on a shared host
(``h8.maintstar.co/<Tenant>/``) with the single-page portal shell served from
``/<tenant>/portal/``. The important property of this host for NS Trackstar is
that it is a completely separate machine from the agency's own website: City of
Rio Vista's site answers HTTP 403 from Cloudflare to every client we have, and
this host answers anonymously with no cookie, token, login or captcha on any
call. That is why Rio Vista can be covered at all.

Two endpoints carry the whole contract:

    GET /<Tenant>/mvc/Public/Configuration/portal
        -> the portal's own settings, including
           ``{"search": {"disableAnonymousSearch": false}}``
    GET /<Tenant>/api/Public/Record/Search?query=<str>&skip=<n>&take=<n>
        -> {"data": [...], "total": -1, "showMoreMode": true|false}

Four things about that search endpoint are worth stating plainly, because each
one is a way to build a collector that looks like it works and does not:

*   **There is no listing.** The endpoint only answers a substring match against
    the record number. There is no "give me everything" query, so *which*
    substrings get walked is a curation decision, and curation decisions belong
    in config rather than in code. ``queries`` is that decision: year prefixes
    (``26-``, ``25-``) reach all of a year's numbering, type prefixes (``PS``,
    ``CS``) reach a family. Queries overlap heavily on purpose — overlap is
    cheap and a gap is invisible — so rows are deduplicated by record number and
    every query reports how many rows it returned and how many of those were new.
    A config that quietly stops covering a record type shows up as a query whose
    row count collapsed, which is the only way anyone will ever notice.

*   **``total`` is always -1.** It is not a count and it is not a hint; it is a
    literal that never changes. Treating it as a total is how a run ends after
    one page. The only honest end-of-results signal is a page shorter than the
    page size, so that is the stopping rule, bounded by a configured per-query
    page cap. ``showMoreMode`` agrees with the short page in practice and is
    recorded, but it is not trusted as the sole stop. Hitting the cap is
    reported per query and in ``page_cap_hit`` so a capped run can never be
    mistaken for a complete one.

*   **``description`` is the literal string ``"(Confidential)"`` for anonymous
    callers.** Every row, without exception. It is a withholding notice, not a
    description, and writing it into a description field would fill the database
    with a thousand projects all described as "(Confidential)". It is recorded as
    absent, with ``description_withheld`` saying why the field is empty.

*   **``lat``/``lng`` are present on some rows and null on most.** They are the
    agency's own coordinates for the address, so they are used as source-provided
    geometry, and anything unusable — missing, unparseable, out of range, or the
    0,0 an unset coordinate produces — leaves the record unlocated rather than
    putting a Rio Vista permit in the Gulf of Guinea.

Record numbers are the agency's identifiers (``PS+26-0469``, ``CS26-0056``,
``26-1834``) and ``msType``/``status`` are the agency's own words for what a
record is and where it stands ("SolarApp+", "Issued and Paid", "Open"). None of
them is folded into an inferred lifecycle state here.

No deep link is synthesised. The portal is a hash-routed single-page app whose
record route is not readable from the endpoints this adapter uses, and guessing
one would produce a URL that cannot be verified and may not resolve. The
canonical link stays the portal's own search page, and the row's ``msValue`` and
numeric id are preserved so a real deep link can be added later without a
re-collection.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, LocationAccuracy, NormalizedRecord

_HOST = "https://h8.maintstar.co"
_CONFIG_PATH = "/{tenant}/mvc/Public/Configuration/portal"
_SEARCH_PATH = "/{tenant}/api/Public/Record/Search"
_PORTAL_PATH = "/{tenant}/portal/"

# The fields a search row must keep carrying for this source to mean anything.
_REQUIRED_ROW_FIELDS = ("number", "msType", "status", "createdDate")

# What the portal returns in place of a description for an anonymous caller.
_WITHHELD_DESCRIPTION = "(confidential)"


def _contract_broken(message: str) -> RuntimeError:
    """Shape a contract break as an error.

    The source answered; it just did not answer with the contract this adapter
    was written against. That is a broken collector to fix, not a blocked source
    and not an empty result, so it is raised rather than swallowed.
    """

    return RuntimeError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _moment(value: Any) -> datetime | None:
    """Read MaintStar's ``2026-09-11T11:59:11Z`` UTC stamps."""

    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_point(lat: Any, lng: Any) -> tuple[float, float] | None:
    """Return (lat, lng) when the row carries a usable coordinate, else None.

    Most rows carry nulls. Anything outside real latitude/longitude range, and
    the 0,0 an unset coordinate produces, is rejected rather than placed in the
    Gulf of Guinea.
    """

    if lat is None or lng is None:
        return None
    try:
        latitude = float(lat)
        longitude = float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    if latitude == 0 and longitude == 0:
        return None
    return latitude, longitude


class MaintStarPublicAdapter(CollectorAdapter):
    """Collect an agency's public permit records from its MaintStar portal."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self._last_request_at: float | None = None
        options = config.options

        self.tenant = _clean(options.get("tenant")).strip("/")
        if not self.tenant:
            raise ValueError("MaintStar tenant (the portal path segment) is required")
        self.host = str(options.get("host") or _HOST).rstrip("/")
        host = urlparse(self.host).hostname
        if not host:
            raise ValueError("MaintStar host must be an absolute https URL")
        self._allowed_host = host

        # Discovery is by substring match, so the walked queries are a coverage
        # decision that has to be visible and arguable. See the module docstring.
        self.queries = [_clean(q) for q in (options.get("queries") or []) if _clean(q)]
        if not self.queries:
            raise ValueError(
                "MaintStar discovery is substring-only; at least one search query is required"
            )

        self.take = max(1, min(300, int(options.get("take", 300))))
        self.max_pages_per_query = max(1, int(options.get("max_pages_per_query", 20)))
        self.min_expected_records = int(options.get("min_expected_records", 1))
        self.user_agent = str(
            options.get("user_agent")
            or "Mozilla/5.0 (compatible; NS-Trackstar/0.1; +https://github.com/jonnyearlmedia/NS-trackstar)"
        )
        self.min_interval = float(options.get("min_request_interval_seconds", 0.5))
        self.timeout_seconds = float(options.get("timeout_seconds", 45))

    # ------------------------------------------------------------------ transport

    @property
    def portal_url(self) -> str:
        return f"{self.host}{_PORTAL_PATH.format(tenant=self.tenant.lower())}"

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "User-Agent": self.user_agent}

    async def _pace(self) -> None:
        if self.min_interval <= 0 or self._last_request_at is None:
            return
        delay = self.min_interval - (asyncio.get_running_loop().time() - self._last_request_at)
        if delay > 0:
            await asyncio.sleep(delay)

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.host}{path}"
        if urlparse(url).hostname != self._allowed_host:
            raise RuntimeError("MaintStar request attempted to leave the configured host")

        await self._pace()
        try:
            response = await client.get(url, params=params, headers=self._headers())
        finally:
            self._last_request_at = asyncio.get_running_loop().time()

        if response.status_code in {401, 403}:
            # This host answers anonymously today. If it stops, that is a real
            # change in what the city publishes, not a transient failure to retry.
            raise SourceBlockedError(
                f"MaintStar rejected anonymous access with HTTP {response.status_code}; "
                f"{self.tenant} may have closed its public portal"
            )
        if response.status_code == 429:
            raise RuntimeError("MaintStar rate-limited the collector; the run is incomplete")
        response.raise_for_status()
        try:
            return response.json()
        except json.JSONDecodeError:
            raise RuntimeError(
                "MaintStar returned a non-JSON body where the portal API returns JSON"
            ) from None

    # ------------------------------------------------------------------ requests

    async def _portal_config(self, client: httpx.AsyncClient) -> dict[str, Any]:
        """Read the portal's settings and refuse to search if it says not to.

        The portal publishes whether anonymous search is switched on. Reading it
        first means a city that turns public search off gets recorded as blocked
        on one cheap request, instead of being hammered with page after page of
        empty or rejected searches.
        """

        payload = await self._get_json(client, _CONFIG_PATH.format(tenant=self.tenant))
        if not isinstance(payload, dict):
            raise _contract_broken("MaintStar portal configuration was not a JSON object")
        if payload.get("portalDisabled"):
            raise SourceBlockedError(f"MaintStar portal for {self.tenant} is switched off")
        search = payload.get("search")
        if not isinstance(search, dict) or "disableAnonymousSearch" not in search:
            raise RuntimeError(
                "MaintStar portal configuration no longer states "
                "search.disableAnonymousSearch; the contract has changed"
            )
        if bool(search["disableAnonymousSearch"]):
            raise SourceBlockedError(
                f"{self.tenant} has switched anonymous search off in its MaintStar portal, "
                "so it publishes no records to anonymous callers"
            )
        return payload

    async def _walk(
        self, client: httpx.AsyncClient, query: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Page one query until a short page, or until the configured cap."""

        rows: list[dict[str, Any]] = []
        pages = 0
        capped = False
        show_more = None
        while True:
            if pages >= self.max_pages_per_query:
                capped = True
                break
            payload = await self._get_json(
                client,
                _SEARCH_PATH.format(tenant=self.tenant),
                params={"query": query, "skip": len(rows), "take": self.take},
            )
            if not isinstance(payload, dict):
                raise _contract_broken(
                    "MaintStar search returned a body that was not a JSON object"
                )
            batch = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
            show_more = payload.get("showMoreMode")
            pages += 1
            rows.extend(batch)
            # "total" is -1 on every response and says nothing. A page shorter
            # than the page size is the only honest end-of-results signal.
            if len(batch) < self.take:
                break
        return rows, {
            "query": query,
            "pages": pages,
            "rows_returned": len(rows),
            "page_cap_hit": capped,
            "show_more_mode": show_more,
        }

    # ------------------------------------------------------------------ records

    def _record(self, row: dict[str, Any]) -> NormalizedRecord | None:
        number = _clean(row.get("number") or row.get("projectNumber"))
        if not number:
            return None
        record_id = _clean(row.get("id"))
        created = _moment(row.get("createdDate"))
        dated = _moment(row.get("dateVal"))

        description = _clean(row.get("description"))
        withheld = description.casefold() == _WITHHELD_DESCRIPTION

        normalized: dict[str, Any] = {
            "record_kind": "permit",
            "record_number": number,
            # msType and status are the agency's own words for what this record
            # is and where it stands. They are kept as written.
            "source_record_type": _clean(row.get("msType") or row.get("type")) or None,
            "source_status": _clean(row.get("status")) or None,
            "source_type_id": row.get("typeId"),
            "project_type": _clean(row.get("projectType")) or None,
            "address": _clean(row.get("address")) or None,
            "address_id": row.get("addressId"),
            "ms_value": _clean(row.get("msValue")) or None,
            "project_ms_value": _clean(row.get("projectMsValue")) or None,
            "project_number": _clean(row.get("projectNumber")) or None,
            "created_date": created.isoformat() if created else None,
            # The portal labels its one date field rather than naming it:
            # "Issued on", "Applied on". The label is kept with the value.
            "source_date": dated.isoformat() if dated else None,
            "source_date_label": _clean(row.get("datePrefix")) or None,
            # The portal returns "(Confidential)" in place of every description
            # for anonymous callers. That is a notice, not a description.
            "description_withheld": True if withheld else None,
            "description": None if withheld else (description or None),
        }
        normalized = {k: v for k, v in normalized.items() if v not in (None, "", [], {})}

        point = parse_point(row.get("lat"), row.get("lng"))
        geometry = {"type": "Point", "coordinates": [point[1], point[0]]} if point else None

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=f"maintstar:{self.tenant.casefold()}:{record_id or number}",
            canonical_url=self.portal_url,
            source_created_at=created,
            source_updated_at=None,
            raw_payload={"search_row": row},
            normalized_payload=normalized,
            geometry_geojson=geometry,
            geometry_source=f"{self.host}{_SEARCH_PATH.format(tenant=self.tenant)}"
            if geometry
            else None,
            location_accuracy=LocationAccuracy.EXACT_SOURCE_GEOMETRY if geometry else None,
        )

    def _schema_fingerprint(self, rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        keys: set[str] = set()
        for row in rows:
            keys.update(row.keys())
        return hashlib.sha256(
            json.dumps(sorted(keys), separators=(",", ":")).encode()
        ).hexdigest()

    # ------------------------------------------------------------------ contract

    async def canary(self) -> bool:
        """Assert the payload shape and the anonymous-search flag, not HTTP 200.

        This host answers 200 with an HTML shell for paths that do not exist, so
        a status code proves nothing at all here. The canary reads the portal's
        own anonymous-search flag (which raises SourceBlockedError when the city
        turns search off) and then checks that one real search still returns rows
        carrying the fields this adapter depends on.
        """

        async with self._session() as client:
            await self._portal_config(client)
            payload = await self._get_json(
                client,
                _SEARCH_PATH.format(tenant=self.tenant),
                params={"query": self.queries[0], "skip": 0, "take": min(self.take, 25)},
            )
            if not isinstance(payload, dict) or "data" not in payload:
                return False
            rows = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
            if len(rows) < self.min_expected_records:
                return False
            first = rows[0]
            return all(field in first for field in _REQUIRED_ROW_FIELDS)

    async def collect(self) -> CollectorResult:
        async with self._session() as client:
            portal_config = await self._portal_config(client)

            deduped: dict[str, dict[str, Any]] = {}
            query_reports: list[dict[str, Any]] = []
            duplicate_rows = 0
            for query in self.queries:
                rows, report = await self._walk(client, query)
                new = 0
                for row in rows:
                    key = _clean(row.get("number") or row.get("projectNumber")).casefold()
                    if not key:
                        # Numberless rows cannot be deduplicated against anything;
                        # they are kept under their own key so the parse failure
                        # below is counted rather than silently collapsed.
                        deduped[f"__unnumbered__{len(deduped)}"] = row
                        new += 1
                        continue
                    if key in deduped:
                        duplicate_rows += 1
                        continue
                    deduped[key] = row
                    new += 1
                report["records_new"] = new
                query_reports.append(report)

        rows_in_scope = list(deduped.values())
        records: list[NormalizedRecord] = []
        unparsed = 0
        for row in rows_in_scope:
            record = self._record(row)
            if record is None:
                unparsed += 1
                continue
            records.append(record)

        located = sum(1 for record in records if record.geometry_geojson is not None)
        coordinates_offered = sum(
            1 for row in rows_in_scope if row.get("lat") is not None and row.get("lng") is not None
        )
        coordinates_rejected = sum(
            1
            for row in rows_in_scope
            if row.get("lat") is not None
            and row.get("lng") is not None
            and parse_point(row.get("lat"), row.get("lng")) is None
        )
        types: dict[str, int] = {}
        statuses: dict[str, int] = {}
        for record in records:
            kind = str(record.normalized_payload.get("source_record_type") or "unstated")
            types[kind] = types.get(kind, 0) + 1
            status = str(record.normalized_payload.get("source_status") or "unstated")
            statuses[status] = statuses.get(status, 0) + 1

        return CollectorResult(
            records=records,
            schema_fingerprint=self._schema_fingerprint(rows_in_scope),
            # Parse success, not filter rate: the denominator is the rows this
            # adapter actually tried to turn into records, after duplicates from
            # deliberately overlapping queries are removed. A healthy run is 1.0.
            parser_yield=len(records) / len(rows_in_scope) if rows_in_scope else 1.0,
            metadata={
                "tenant": self.tenant,
                "portal_url": self.portal_url,
                "agency": portal_config.get("agency"),
                "anonymous_search_enabled": True,
                # Which substrings were walked, and what each one returned. A
                # query whose row count collapses is a coverage hole.
                "queries_walked": query_reports,
                "page_cap_hit": any(report["page_cap_hit"] for report in query_reports),
                "capped_queries": [
                    report["query"] for report in query_reports if report["page_cap_hit"]
                ],
                "max_pages_per_query": self.max_pages_per_query,
                "take": self.take,
                "rows_in_scope": len(rows_in_scope),
                "rows_unparsed": unparsed,
                "duplicate_rows_across_queries": duplicate_rows,
                "records_with_coordinates": located,
                "coordinates_offered": coordinates_offered,
                "coordinates_rejected": coordinates_rejected,
                "descriptions_withheld": sum(
                    1
                    for record in records
                    if record.normalized_payload.get("description_withheld")
                ),
                "record_types": types,
                "statuses": statuses,
            },
        )

    @asynccontextmanager
    async def _session(self):
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            yield client
