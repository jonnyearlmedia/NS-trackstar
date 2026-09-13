"""Tyler EnerGov "Civic Access" self-service search.

Civic Access is the public front counter for a Tyler EnerGov installation: one
Angular app per tenant, on `<tenant>-energovweb.tylerhost.net/apps/selfservice`,
listing that jurisdiction's permits, plan applications, code cases, inspections,
business licences and capital projects. Two calls drive the whole search:

    GET  <base>/api/energov/search/criteria   -> the request template
    POST <base>/api/energov/search/search     -> the results

The template that comes back from `criteria` is the request body for `search`,
which is why it is fetched rather than hand-written: it carries a criteria block
per module and Tyler adds fields to those blocks between releases.

Four headers decide whether this source exists at all:

    tenantId: 1
    tenantName: <tenant>
    Tyler-TenantUrl: <tenant>
    Tyler-Tenant-Culture: en-US

Without all four the endpoint answers HTTP 500 with
`{"Message":"An error has occurred."}` for every payload, including a payload
copied verbatim out of the browser. That failure is indistinguishable from a
retired route, and reading it as one is how a live source gets written off. It is
surfaced here by name so the next person sees the cause and not the symptom.

Two more refusals matter, because neither of them looks like a refusal:

*   `SearchModule` scoped to a single module (2, 3, 5, ...) answers HTTP 500.
    Module scoping is done with `FilterModule` instead: 2 permits, 3 plans,
    4 inspections, 5 code cases, 8 licences, 11 projects, and 1 for everything.
    `FilterModule` is a real server-side filter, so a run that wants permits
    fetches permits rather than fetching ninety thousand rows and throwing most
    of them away.
*   A `SortBy` the module does not index answers **HTTP 200** with
    `{"Result": null, "Success": false}`. An adapter that reads `Result` with a
    default of `{}` records that as "this jurisdiction has no code cases". It is
    raised here instead. Each module therefore names its own sort field:
    permits and plans sort on `ApplyDate`, code cases on `OpenedDate`,
    inspections on `RequestDate`, projects on `StartDate`, and licences have no
    date sort at all.

The date criteria inside the template (`PermitCriteria.ApplyDateFrom` and its
siblings) are accepted and ignored by this endpoint — the totals and the rows
come back unchanged. They belong to the per-module search endpoints, which are
the ones that answer 500 here. So the recency window is applied after the fetch,
against results already sorted newest-first, and the walk stops as soon as a
whole page falls outside it. `Keyword` is honoured server-side, for the record.

Finally, the search index refuses an offset beyond 10,000 rows: page 100 at
`PageSize` 100 answers in full and page 101 answers with an empty list rather
than an error. A module with more matches than that cannot be read exhaustively
through this endpoint, and a run that hits the ceiling says so in its metadata
rather than presenting a truncated walk as the whole agency.

`CaseStatus`, `CaseType` and `CaseWorkclass` are the agency's own vocabulary —
"Submitted - Online", "Fire Sprinkler System Permit", "Living Accommodations" —
and are stored as written rather than folded into an inferred lifecycle state.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

_CRITERIA_PATH = "/api/energov/search/criteria"
_SEARCH_PATH = "/api/energov/search/search"

# The search index will not serve an offset past this many rows.
_DEEP_PAGE_CEILING = 10_000

# Fields every result row must keep carrying for this source to mean anything.
_REQUIRED_RESULT_FIELDS = ("CaseId", "CaseNumber", "CaseType", "CaseStatus", "ModuleName")

# The agency's own census, reported alongside what the run actually kept.
_FOUND_KEYS = (
    "PermitsFound",
    "PlansFound",
    "InspectionsFound",
    "CodeCasesFound",
    "RequestsFound",
    "BusinessLicensesFound",
    "ProfessionalLicensesFound",
    "LicensesFound",
    "ProjectsFound",
    "OperationalPermitsFound",
    "TotalFound",
)


@dataclass(frozen=True, slots=True)
class _Module:
    """One Civic Access module: how to ask for it and how to date what comes back.

    ``sort_by`` is the field the search index will order this module on, and
    ``recency_field`` is the field the returned rows actually carry. They are not
    always the same word: code cases sort on ``OpenedDate`` and then report that
    same moment in ``ApplyDate``, leaving ``OpenedDate`` null on every row.
    """

    name: str
    filter_module: int
    module_name: int
    record_kind: str
    route: str
    sort_by: str | None
    recency_field: str | None


_MODULES: dict[str, _Module] = {
    "permit": _Module("permit", 2, 2, "permit", "permit", "ApplyDate", "ApplyDate"),
    "plan": _Module("plan", 3, 3, "plan_application", "plan", "ApplyDate", "ApplyDate"),
    "inspection": _Module(
        "inspection", 4, 4, "inspection", "inspectionDetail/inspection", "RequestDate", None
    ),
    "code_case": _Module("code_case", 5, 5, "code_case", "code", "OpenedDate", "ApplyDate"),
    # Licences are the one module with no date sort the index will accept, so a
    # licence run cannot be bounded by recency and says so rather than pretending.
    "license": _Module("license", 8, 8, "business_license", "businessLicense", None, None),
    "project": _Module("project", 11, 11, "project", "project", "StartDate", "StartDate"),
}

# FilterModule 1 is "everything", and it is the only way to read the agency's own
# count of each module in one call.
_CENSUS = _Module("all", 1, 0, "", "", None, None)

# Permits, plans, code cases and projects are the record types that describe
# something being built, proposed or enforced against. Inspections and business
# licences are real records and are collectable by naming them in config, but an
# agency publishes tens of thousands of each and they are not projects.
_DEFAULT_RECORD_TYPES = ("permit", "plan", "code_case", "project")


def _moment(value: Any, *, timezone: ZoneInfo) -> datetime | None:
    """Read EnerGov's unzoned ``YYYY-MM-DDTHH:MM:SS[.fff]`` agency-local clock."""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed


def _clean(value: Any) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


class EnerGovCivicAccessAdapter(CollectorAdapter):
    """Collect a jurisdiction's public Civic Access records for the configured modules."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self._last_request_at: float | None = None

        options = config.options
        self.base_url = str(options.get("base_url") or config.base_url or "").rstrip("/")
        host = urlparse(self.base_url).hostname
        if not host or not self.base_url.startswith("https://"):
            raise ValueError("EnerGov base_url must be an absolute https self-service URL")
        self._allowed_host = host

        self.tenant_name = str(options.get("tenant_name") or "").strip()
        if not self.tenant_name:
            raise ValueError("EnerGov tenant_name is required; it is sent as three headers")
        self.tenant_id = str(options.get("tenant_id") or "1").strip()
        self.culture = str(options.get("tenant_culture") or "en-US").strip()

        # Which record types this run collects is a curation decision, so it lives
        # in config where it can be read and argued with rather than in the code.
        requested = [
            str(name).strip().casefold()
            for name in (options.get("record_types") or _DEFAULT_RECORD_TYPES)
            if str(name).strip()
        ]
        unknown = [name for name in requested if name not in _MODULES]
        if unknown:
            raise ValueError(
                "EnerGov record_types names no such Civic Access module: "
                f"{', '.join(sorted(unknown))}; known: {', '.join(sorted(_MODULES))}"
            )
        if not requested:
            raise ValueError("EnerGov record_types must name at least one module")
        self.record_types = tuple(dict.fromkeys(requested))
        self.modules = tuple(_MODULES[name] for name in self.record_types)

        self.page_size = max(1, min(100, int(options.get("page_size", 100))))
        self.max_pages_per_module = max(1, int(options.get("max_pages_per_module", 40)))
        self.max_pages_per_run = max(1, int(options.get("max_pages_per_run", 160)))
        recency_days = options.get("recency_days", 365)
        self.recency_days = int(recency_days) if recency_days is not None else None
        if self.recency_days is not None and self.recency_days <= 0:
            self.recency_days = None
        self.keyword = str(options.get("keyword") or "")

        self.timezone = ZoneInfo(str(options.get("timezone", "America/Los_Angeles")))
        self.min_expected_results = int(options.get("min_expected_results", 1))
        self.min_interval = float(options.get("min_request_interval_seconds", 0.5))
        self.timeout_seconds = float(options.get("timeout_seconds", 60))
        self.user_agent = str(
            options.get("user_agent")
            or "Mozilla/5.0 (compatible; NS-Trackstar/0.1; "
            "+https://github.com/jonnyearlmedia/NS-trackstar)"
        )

    # ------------------------------------------------------------------ transport

    def _headers(self) -> dict[str, str]:
        """The four tenant headers, without which every payload answers HTTP 500."""

        return {
            "Accept": "application/json",
            "Content-Type": "application/json;charset=utf-8",
            "User-Agent": self.user_agent,
            "tenantId": self.tenant_id,
            "tenantName": self.tenant_name,
            "Tyler-TenantUrl": self.tenant_name,
            "Tyler-Tenant-Culture": self.culture,
        }

    async def _pace(self) -> None:
        if self.min_interval <= 0 or self._last_request_at is None:
            return
        delay = self.min_interval - (asyncio.get_running_loop().time() - self._last_request_at)
        if delay > 0:
            await asyncio.sleep(delay)

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if urlparse(url).hostname != self._allowed_host:
            raise RuntimeError("EnerGov request attempted to leave the configured tenant host")

        await self._pace()
        try:
            response = await client.request(
                method, url, json=json_body, headers=self._headers(), timeout=self.timeout_seconds
            )
        finally:
            self._last_request_at = asyncio.get_running_loop().time()

        if response.status_code in {401, 403}:
            raise SourceBlockedError(
                f"Civic Access for {self.tenant_name} rejected anonymous access with "
                f"HTTP {response.status_code}"
            )
        if response.status_code >= 500:
            raise RuntimeError(
                f"Civic Access answered HTTP {response.status_code} for {path}: "
                f"{_message(response.text)}. This endpoint answers 500 for every payload when "
                "the tenantId / tenantName / Tyler-TenantUrl / Tyler-Tenant-Culture headers are "
                "missing or name the wrong tenant, and for a SearchModule scoped to one module; "
                "it is not evidence that the route is gone."
            )
        response.raise_for_status()
        try:
            envelope = response.json()
        except json.JSONDecodeError:
            envelope = None
        if type(envelope) is not dict:
            raise RuntimeError(
                f"Civic Access returned a {type(envelope).__name__} body for {path} where its "
                "JSON envelope was expected"
            )
        return envelope

    def _result(self, envelope: dict[str, Any], *, what: str) -> dict[str, Any]:
        """Unwrap the envelope, refusing to read a stated failure as an empty answer.

        A rejected request comes back as HTTP 200 with ``Result: null`` and
        ``Success: false``. Defaulting that to ``{}`` turns a broken query into a
        jurisdiction that publishes nothing, which is the failure this source is
        most likely to produce and the least likely to be noticed.
        """

        result = envelope.get("Result")
        if type(result) is not dict or envelope.get("Success") is False:
            raise RuntimeError(
                f"Civic Access refused {what}: "
                f"{_clean(envelope.get('ErrorMessage')) or 'no message'}. A SortBy the module "
                "does not index is refused this way, with HTTP 200 and a null Result."
            )
        return result

    # ------------------------------------------------------------------ requests

    async def _template(self, client: httpx.AsyncClient) -> dict[str, Any]:
        """Fetch the search template, which is the search request body."""

        envelope = await self._request(client, "GET", _CRITERIA_PATH)
        return self._result(envelope, what="the search criteria template")

    def _body(self, template: dict[str, Any], module: _Module, page: int) -> dict[str, Any]:
        body = json.loads(json.dumps(template))
        body.update(
            {
                "Keyword": self.keyword,
                "ExactMatch": False,
                # SearchModule stays 1. Scoped to a module it answers HTTP 500;
                # FilterModule is what actually narrows the search server-side.
                "SearchModule": 1,
                "FilterModule": module.filter_module,
                "PageNumber": page,
                "PageSize": self.page_size,
                "SortBy": module.sort_by or "relevance",
                # Newest first where the module has a date to sort on, so a
                # recency-bounded walk can stop instead of reading the archive.
                "SortAscending": module.sort_by is None,
            }
        )
        return body

    async def _search(
        self, client: httpx.AsyncClient, template: dict[str, Any], module: _Module, page: int
    ) -> dict[str, Any]:
        envelope = await self._request(
            client, "POST", _SEARCH_PATH, json_body=self._body(template, module, page)
        )
        return self._result(envelope, what=f"the {module.name} search (page {page})")

    # ------------------------------------------------------------------ records

    def _canonical_url(self, module: _Module, case_id: str) -> str:
        return f"{self.base_url}/#/{module.route}/{case_id}"

    def _record(self, module: _Module, row: dict[str, Any]) -> NormalizedRecord | None:
        case_id = str(row.get("CaseId") or "").strip()
        case_number = _clean(row.get("CaseNumber"))
        if not case_id or not case_number:
            return None

        address = row.get("Address") if isinstance(row.get("Address"), dict) else {}
        applied = _moment(row.get("ApplyDate"), timezone=self.timezone)
        issued = _moment(row.get("IssueDate"), timezone=self.timezone)

        normalized = {
            "record_kind": module.record_kind,
            "module": module.name,
            "record_number": case_number,
            # Tyler and the agency's own vocabulary, stored as written. "Void",
            # "Submitted - Online" and "Complaint Received" are statuses the
            # agency published, not lifecycle states to be guessed at.
            "case_type": _clean(row.get("CaseType")),
            "case_workclass": _clean(row.get("CaseWorkclass")),
            "case_status": _clean(row.get("CaseStatus")),
            "project_name": _clean(row.get("ProjectName")),
            "description": _clean(row.get("Description")),
            "apply_date": applied.isoformat() if applied else None,
            "issue_date": issued.isoformat() if issued else None,
            "expire_date": _iso(row.get("ExpireDate"), self.timezone),
            "complete_date": _iso(row.get("CompleteDate"), self.timezone),
            "final_date": _iso(row.get("FinalDate"), self.timezone),
            "request_date": _iso(row.get("RequestDate"), self.timezone),
            "schedule_date": _iso(row.get("ScheduleDate"), self.timezone),
            "start_date": _iso(row.get("StartDate"), self.timezone),
            "expected_end_date": _iso(row.get("ExpectedEndDate"), self.timezone),
            "address": _clean(address.get("FullAddress")) or _clean(row.get("AddressDisplay")),
            "address_line_1": _clean(address.get("AddressLine1")),
            "unit_or_suite": _clean(address.get("UnitOrSuite")),
            "city": _clean(address.get("City")),
            "state": _clean(address.get("StateName")),
            "postal_code": _clean(address.get("PostalCode")),
            "parcel_number": _clean(row.get("MainParcel")),
            "company_name": _clean(row.get("CompanyName")),
            "business_type": _clean(row.get("BusinessTypeName")),
            "license_year": row.get("LicenseYear"),
        }
        normalized = {k: v for k, v in normalized.items() if v not in (None, "", [], {})}

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=f"energov:{self.tenant_name}:{module.name}:{case_id}",
            canonical_url=self._canonical_url(module, case_id),
            source_created_at=applied or issued,
            source_updated_at=None,
            raw_payload={"tenant": self.tenant_name, "module": module.name, "result": row},
            normalized_payload=normalized,
        )

    def _schema_fingerprint(self, rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        keys: set[str] = set()
        for row in rows:
            keys.update(row.keys())
            address = row.get("Address")
            if isinstance(address, dict):
                keys.update(f"Address.{key}" for key in address)
        return hashlib.sha256(
            json.dumps(sorted(keys), separators=(",", ":")).encode()
        ).hexdigest()

    # ------------------------------------------------------------------ contract

    async def canary(self) -> bool:
        """Prove the source answers with the shape expected, not merely with a 200.

        A missing tenant header answers HTTP 500 and a refused sort answers HTTP
        200 with a null body, so a canary that checked status codes would pass on
        a source that returns nothing and fail on one that works. This asserts on
        the payload: the template carries its per-module criteria blocks, and the
        search returns entity rows carrying the fields the normalizer reads.
        """

        async with self._session() as client:
            template = await self._template(client)
            for block in ("PermitCriteria", "PlanCriteria", "CodeCaseCriteria"):
                if not isinstance(template.get(block), dict):
                    return False
            if "SearchModule" not in template or "FilterModule" not in template:
                return False

            module = self.modules[0]
            result = await self._search(client, template, module, 1)
            if not any(key in result for key in _FOUND_KEYS):
                return False
            rows = [row for row in (result.get("EntityResults") or []) if isinstance(row, dict)]
            if len(rows) < self.min_expected_results:
                return False
            first = rows[0]
            if not all(field in first for field in _REQUIRED_RESULT_FIELDS):
                return False
            # FilterModule is a server-side filter; if it ever stops filtering,
            # every downstream count in this adapter is wrong.
            return all(row.get("ModuleName") == module.module_name for row in rows)

    async def collect(self) -> CollectorResult:
        cutoff = (
            datetime.now(UTC) - timedelta(days=self.recency_days)
            if self.recency_days is not None
            else None
        )

        records: list[NormalizedRecord] = []
        sampled: list[dict[str, Any]] = []
        per_module: dict[str, dict[str, Any]] = {}
        agency_census: dict[str, Any] = {}
        in_scope = 0
        unparsed = 0
        pages_walked = 0

        async with self._session() as client:
            template = await self._template(client)

            # One unscoped call for the agency's own census of everything it
            # publishes, so the run can report what exists next to what it kept.
            # It has to be unscoped: under a FilterModule the other modules'
            # counts all come back zero rather than absent.
            census = await self._search(client, template, _CENSUS, 1)
            agency_census = {key: census[key] for key in _FOUND_KEYS if key in census}

            for module in self.modules:
                stats = {
                    "reported_by_agency": None,
                    "rows_fetched": 0,
                    "rows_kept": 0,
                    "rows_outside_window": 0,
                    "rows_wrong_module": 0,
                    "rows_undated": 0,
                    "rows_unparsed": 0,
                    "pages_walked": 0,
                    "pages_capped": False,
                    "deep_paging_ceiling_reached": False,
                    "stopped_at_recency_window": False,
                    "recency_window_applied": bool(cutoff and module.recency_field),
                    "sort_by": module.sort_by or "relevance",
                }
                per_module[module.name] = stats

                page = 1
                while True:
                    if stats["pages_walked"] >= self.max_pages_per_module:
                        stats["pages_capped"] = True
                        break
                    if pages_walked >= self.max_pages_per_run:
                        stats["pages_capped"] = True
                        break
                    if (page - 1) * self.page_size >= _DEEP_PAGE_CEILING:
                        # The index serves no offset past 10,000 rows and says so
                        # with an empty list rather than an error, so the ceiling
                        # is named here instead of being read as the end of data.
                        stats["deep_paging_ceiling_reached"] = True
                        break

                    result = await self._search(client, template, module, page)
                    if stats["reported_by_agency"] is None:
                        stats["reported_by_agency"] = result.get("TotalFound")
                    rows = [
                        row for row in (result.get("EntityResults") or []) if isinstance(row, dict)
                    ]
                    stats["pages_walked"] += 1
                    pages_walked += 1
                    if not rows:
                        break
                    stats["rows_fetched"] += len(rows)
                    if len(sampled) < 50:
                        sampled.extend(rows[: 50 - len(sampled)])

                    page_had_in_window = False
                    page_had_dated = False
                    for row in rows:
                        if row.get("ModuleName") != module.module_name:
                            # FilterModule asked for one module; anything else is
                            # a filter that stopped filtering, not a record to keep.
                            stats["rows_wrong_module"] += 1
                            continue
                        if cutoff and module.recency_field:
                            moment = _moment(
                                row.get(module.recency_field), timezone=self.timezone
                            )
                            if moment is None:
                                # An undated record cannot be judged against a
                                # window, and dropping it would silently hollow
                                # out the modules that date the fewest rows.
                                stats["rows_undated"] += 1
                                page_had_in_window = True
                            elif moment < cutoff:
                                stats["rows_outside_window"] += 1
                                page_had_dated = True
                                continue
                            else:
                                page_had_in_window = True
                                page_had_dated = True

                        # In scope. From here on, anything that fails is a parse
                        # failure, and that is what parser_yield measures.
                        in_scope += 1
                        record = self._record(module, row)
                        if record is None:
                            unparsed += 1
                            stats["rows_unparsed"] += 1
                            continue
                        stats["rows_kept"] += 1
                        records.append(record)

                    if cutoff and module.recency_field and page_had_dated and not page_had_in_window:
                        # Newest first, and this whole page is older than the
                        # window, so every page after it is older still.
                        stats["stopped_at_recency_window"] = True
                        break
                    if len(rows) < self.page_size:
                        break
                    page += 1

        statuses: dict[str, int] = {}
        case_types: dict[str, int] = {}
        for record in records:
            status = str(record.normalized_payload.get("case_status") or "unstated")
            statuses[status] = statuses.get(status, 0) + 1
            case_type = str(record.normalized_payload.get("case_type") or "unstated")
            case_types[case_type] = case_types.get(case_type, 0) + 1

        incomplete = sorted(
            name
            for name, stats in per_module.items()
            if stats["pages_capped"]
            or stats["deep_paging_ceiling_reached"]
            or (
                stats["reported_by_agency"]
                and stats["rows_fetched"] < stats["reported_by_agency"]
                and not stats["stopped_at_recency_window"]
            )
        )

        return CollectorResult(
            records=records,
            schema_fingerprint=self._schema_fingerprint(sampled),
            # Parse success, not filter rate: the denominator is the rows that
            # were in scope for this run, not everything the agency published or
            # everything the pager happened to touch. A healthy run reads 1.0
            # however narrow the configured record types are.
            parser_yield=(in_scope - unparsed) / in_scope if in_scope else 1.0,
            metadata={
                "tenant_name": self.tenant_name,
                "record_types": list(self.record_types),
                # What the agency says it publishes, across every module,
                # including the ones this run deliberately does not collect.
                "agency_reports": agency_census,
                "records_kept": len(records),
                "rows_in_scope": in_scope,
                "rows_unparsed": unparsed,
                "pages_walked": pages_walked,
                "page_size": self.page_size,
                "recency_days": self.recency_days,
                "recency_cutoff": cutoff.isoformat() if cutoff else None,
                "keyword": self.keyword or None,
                "modules": per_module,
                # A run that walked fewer pages than the agency has rows must
                # say so rather than presenting a partial read as the whole file.
                "modules_incompletely_walked": incomplete,
                "window_walked_to_completion": not incomplete,
                "case_statuses": statuses,
                "case_types": case_types,
            },
        )

    @asynccontextmanager
    async def _session(self):
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            yield client


def _iso(value: Any, timezone: ZoneInfo) -> str | None:
    moment = _moment(value, timezone=timezone)
    return moment.isoformat() if moment else None


def _message(body: str) -> str:
    """Repeat Civic Access's own error back, so a failure says what it said."""

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return " ".join(body.split())[:200] or "no message"
    if isinstance(payload, dict):
        for key in ("Message", "ErrorMessage", "message"):
            text = _clean(payload.get(key))
            if text:
                return text
    return " ".join(body.split())[:200] or "no message"
