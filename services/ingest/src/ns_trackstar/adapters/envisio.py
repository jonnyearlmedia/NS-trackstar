"""Envisio public performance dashboards.

An agency that runs its strategic or capital plan in Envisio publishes it at
``performance.envisio.com`` as a single-page app. There is no HTML to scrape: the
served document is a loading spinner, and every project, budget figure and phase
label arrives afterwards over the wire. The city's own page only embeds it, e.g.

    https://www.cityofsthelena.gov/490/CIP-Interactive-Dashboard
        -> https://performance.envisio.com/dashboard-brandoff/cityofsthelena4607

Three facts make this source readable, and all three are read out of the vendor's
own files rather than guessed:

*   The served document ends with the app's runtime config, in plain sight:

        <script>window.token="",window.corporationId="",
        window.serverUri="https://envisio-pdv2-s-production.herokuapp.com/graphql",...

    So the dashboard host serves the app and a Heroku host serves the data. That
    config is three kilobytes, so this adapter re-reads it on every run and follows
    it; the constant below is only the fallback for when the read fails. A
    ``serverUri`` pointing at a host outside ``allowed_endpoint_hosts`` is ignored
    rather than followed, because a page that has been tampered with must not be
    able to redirect the collector.

*   The query lives in the app's JS bundle (``/static/js/main.<hash>.js``), written
    out in full. It is reproduced verbatim in ``_PUBLISH_DATA_QUERY`` below:

        query publishData($subDomain: String, $pageId: String) {
          publishData(subDomain: $subDomain, pageId: $pageId)
        }

    ``publishData`` returns a JSON scalar, not a typed graph, so there are no field
    names to invent: one POST returns the entire published dashboard. ``pageId`` is
    optional and narrows nothing worth having, so it is left unset.

*   The route that gives a project its own address is in the same bundle:
    ``/dashboard-brandoff/:subdomain/:pageId?``. That, not a fabricated deep link,
    is what a record's ``canonical_url`` is built from.

The payload is ``{"pages": {...}, "generalSettings": {...}}``. ``pages`` is keyed by
plan-node id and mixes three different things: one ``home`` page, the plan's
categories (``Strategy-<id>``), the projects (``Activity-<id>``), and — the trap —
performance measures, which are keyed with a compound id like
``Activity-272997-Activity-272997-Outcome-41738`` and carry no project fields at
all. Only keys matching ``Activity-<digits>`` exactly are projects. St. Helena's
dashboard returns 87 pages for 80 projects, so a parser yield divided by everything
fetched would read 0.92 on a run where every single project parsed perfectly. The
yield below divides by the pages that are actually in scope, and a healthy run
reads 1.0.

The project's own fields are not separate keys. The agency authors them as a
labelled block inside the page's ``description`` HTML:

    <p>Project Name:<strong> W-101 Tank 2 Rehabilitation</strong></p>
    <p>Description: <p>Rehabilitate Tank 2 at Lower Reservoir...</p></p>
    <p>Budget: $1,045,809.00</p><p>Expenditure: $100,184.00</p>
    <p>Project Phase: Early Design</p>

That layout is the agency's authoring convention rather than Envisio's schema, so
the labels are configurable, and a page that stops carrying them is reported as a
parse failure instead of being emitted as a nameless record. "Project Phase" and
the parent category are the city's own words — "Early Design", "Close Out",
"Wastewater" — and are stored exactly as written rather than folded into an
inferred lifecycle state.

One more thing worth stating because it is silent: an unknown ``subDomain`` does
not error. It answers HTTP 200 with ``{"data":{"publishData":{}}}``. A collector
that trusted the status code would report a healthy run with zero projects, which
is why ``canary()`` asserts on the shape of the payload and not on the response.
"""

from __future__ import annotations

import hashlib
import html as html_module
import json
import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

_DASHBOARD_ORIGIN = "https://performance.envisio.com"
_DASHBOARD_PATH = "/dashboard-brandoff"
# Fallback only. The live value is read from the dashboard document's own
# window.serverUri on every run; see the module docstring.
_GRAPHQL_ENDPOINT = "https://envisio-pdv2-s-production.herokuapp.com/graphql"
_ALLOWED_ENDPOINT_HOSTS = ("envisio-pdv2-s-production.herokuapp.com",)

# Copied verbatim out of the app's own JS bundle. Not reconstructed.
_PUBLISH_DATA_QUERY = (
    "query publishData($subDomain: String, $pageId: String) {\n"
    "    publishData(subDomain: $subDomain, pageId: $pageId)\n"
    "  }\n"
)

_SERVER_URI = re.compile(r"""window\.serverUri\s*=\s*["']([^"']+)["']""")

# A project page's key is "Activity-<digits>" exactly. A measure's key carries the
# activity id twice and an outcome id, and matching it loosely is how a dashboard of
# 80 projects turns into 81 records with one of them empty.
_PROJECT_KEY = re.compile(r"Activity-\d+")

# "W-101 Tank 2 Rehabilitation" -> ("W-101", "Tank 2 Rehabilitation").
_PROJECT_NUMBER = re.compile(r"^([A-Z]{1,4}\d*-[0-9]+[A-Za-z]?)\s+(.+)$")

_MONEY = re.compile(r"^\$?\s*(-?[\d,]+(?:\.\d+)?)$")

_BLOCK_MARKERS = ("cf-mitigated", "captcha", "cf_chl", "attention required")

# The labels St. Helena writes into each project's description, mapped to the field
# each one becomes. Overridable in config; a tenant that authors differently needs
# its own mapping rather than a looser regex here.
_DEFAULT_LABELS: dict[str, str] = {
    "Project Name": "project_name",
    "Description": "description",
    "Budget": "budget",
    "Expenditure": "expenditure",
    "Project Phase": "project_phase",
}


def _text(fragment: str) -> str:
    """Flatten a small HTML fragment to the words a reader would see."""

    plain = re.sub(r"<\s*br\s*/?\s*>", " ", fragment or "")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = html_module.unescape(plain).replace("\xa0", " ")
    return " ".join(plain.split())


def _money(value: str) -> float | None:
    """Read "$1,045,809.00" as a number, and an empty cell as nothing said."""

    match = _MONEY.match((value or "").strip())
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _day(value: Any) -> date | None:
    """Read Envisio's "Jun 30, 2024" display dates."""

    text = " ".join(str(value or "").split())
    if not text:
        return None
    for shape in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, shape).date()  # noqa: DTZ007 - plain date
        except ValueError:
            continue
    return None


class EnvisioAdapter(CollectorAdapter):
    """Collect an agency's published plan from its Envisio performance dashboard."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        options = config.options
        self.sub_domain = str(options.get("sub_domain") or "").strip()
        if not self.sub_domain:
            raise ValueError("Envisio sub_domain (the dashboard path segment) is required")
        self.dashboard_origin = str(
            options.get("dashboard_origin") or _DASHBOARD_ORIGIN
        ).rstrip("/")
        self.dashboard_path = "/" + str(
            options.get("dashboard_path") or _DASHBOARD_PATH
        ).strip("/")
        self.graphql_endpoint = str(options.get("graphql_endpoint") or _GRAPHQL_ENDPOINT)
        self.discover_endpoint = bool(options.get("discover_endpoint", True))
        self.allowed_endpoint_hosts = {
            str(host).strip().lower()
            for host in (options.get("allowed_endpoint_hosts") or _ALLOWED_ENDPOINT_HOSTS)
            if str(host).strip()
        }
        labels = options.get("description_labels") or _DEFAULT_LABELS
        self.description_labels = {str(k): str(v) for k, v in dict(labels).items()}
        self.required_labels = {
            str(label)
            for label in (options.get("required_labels") or self.description_labels.keys())
        }
        self.min_expected_projects = int(options.get("min_expected_projects", 1))
        self.user_agent = str(
            options.get("user_agent")
            or "Mozilla/5.0 (compatible; NS-Trackstar/0.1; "
            "+https://github.com/jonnyearlmedia/NS-trackstar)"
        )
        self.timeout_seconds = float(options.get("timeout_seconds", 45))
        self._label_pattern = re.compile(
            r"(" + "|".join(re.escape(label) for label in self.description_labels) + r")\s*:",
            re.IGNORECASE,
        )
        self._endpoint_used = self.graphql_endpoint
        self._endpoint_discovered = False

    # ------------------------------------------------------------------ transport

    @property
    def dashboard_url(self) -> str:
        return f"{self.dashboard_origin}{self.dashboard_path}/{self.sub_domain}"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": self.dashboard_origin,
            "Referer": f"{self.dashboard_url}",
            "User-Agent": self.user_agent,
        }

    @staticmethod
    def _guard_block(response: httpx.Response, what: str) -> None:
        """Stop at a bot challenge rather than trying to get around one."""

        if response.status_code not in {401, 403, 429, 503}:
            return
        fingerprint = " ".join(
            [response.headers.get("cf-mitigated", ""), response.text[:2000]]
        ).lower()
        if any(marker in fingerprint for marker in _BLOCK_MARKERS):
            raise SourceBlockedError(
                f"Envisio {what} answered HTTP {response.status_code} behind a bot challenge; "
                "this source is blocked rather than empty"
            )
        raise SourceBlockedError(
            f"Envisio {what} refused anonymous access with HTTP {response.status_code}"
        )

    async def _resolve_endpoint(self, client: httpx.AsyncClient) -> str:
        """Follow the dashboard's own window.serverUri, within the allowed hosts."""

        if not self.discover_endpoint:
            return self.graphql_endpoint
        try:
            response = await client.get(
                self.dashboard_url, headers={"User-Agent": self.user_agent}
            )
        except httpx.HTTPError:
            return self.graphql_endpoint
        self._guard_block(response, "dashboard page")
        if response.status_code != 200:
            return self.graphql_endpoint
        match = _SERVER_URI.search(response.text)
        if not match:
            return self.graphql_endpoint
        candidate = match.group(1).strip()
        parsed = urlparse(candidate)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in (
            self.allowed_endpoint_hosts
        ):
            # The page named a host we were not told to trust. Keep the configured
            # endpoint and say so, rather than following it.
            return self.graphql_endpoint
        self._endpoint_discovered = candidate != self.graphql_endpoint
        return candidate

    async def _publish_data(self, client: httpx.AsyncClient) -> dict[str, Any]:
        endpoint = await self._resolve_endpoint(client)
        self._endpoint_used = endpoint
        response = await client.post(
            endpoint,
            headers=self._headers(),
            content=json.dumps(
                {
                    "operationName": "publishData",
                    "variables": {"subDomain": self.sub_domain},
                    "query": _PUBLISH_DATA_QUERY,
                }
            ),
        )
        self._guard_block(response, "GraphQL endpoint")
        response.raise_for_status()
        try:
            body = response.json()
        except json.JSONDecodeError:
            raise RuntimeError(
                "Envisio returned a non-JSON body where a GraphQL response was expected"
            ) from None
        errors = body.get("errors")
        if errors:
            raise RuntimeError(f"Envisio refused the query: {_graphql_error(errors)}")
        published = (body.get("data") or {}).get("publishData")
        return published if isinstance(published, dict) else {}

    # ------------------------------------------------------------------ parsing

    def _project_pages(self, pages: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """The rows actually in scope: project pages, not categories or measures."""

        return {
            key: value
            for key, value in pages.items()
            if isinstance(value, dict) and _PROJECT_KEY.fullmatch(key)
        }

    def _labelled_fields(self, description: str) -> dict[str, str]:
        """Slice the agency's labelled description block into its fields.

        First occurrence of each label wins, and each field runs to the next label,
        so a label word appearing inside prose cannot re-open a field.
        """

        hits = [
            (match.group(1), match.start(), match.end())
            for match in self._label_pattern.finditer(description or "")
        ]
        fields: dict[str, str] = {}
        for index, (label, _start, end) in enumerate(hits):
            following = hits[index + 1][1] if index + 1 < len(hits) else len(description)
            canonical = next(
                (
                    known
                    for known in self.description_labels
                    if known.casefold() == label.casefold()
                ),
                label,
            )
            if canonical in fields:
                continue
            fields[canonical] = _text(description[end:following])
        return fields

    def _record(
        self,
        key: str,
        page: dict[str, Any],
        parent: dict[str, Any] | None,
    ) -> NormalizedRecord | None:
        fields = self._labelled_fields(str(page.get("description") or ""))
        if not self.required_labels.issubset(fields.keys()):
            return None
        # Labels become the field names config asked for, so a tenant that calls its
        # fields something else is not silently relabelled to St. Helena's words.
        values = {
            self.description_labels.get(label, label): text for label, text in fields.items()
        }

        name = (values.get("project_name") or _text(str(page.get("title") or ""))).strip()
        if not name:
            return None

        number_match = _PROJECT_NUMBER.match(name)
        start = _day(page.get("startDate"))
        end = _day(page.get("endDate"))
        latest_update = _text(str(page.get("latestUpdate") or ""))

        normalized: dict[str, Any] = {
            "record_kind": "capital_improvement_project",
            "plan_node_id": key,
            "name": name,
            "project_number": number_match.group(1) if number_match else None,
            "outline_number": page.get("numberWithLabel") or None,
            "description": values.get("description") or None,
            # The city's own labels. "Early Design" and "Wastewater" are published
            # decisions, not lifecycle states to be inferred.
            "project_phase": values.get("project_phase") or None,
            "category": _text(str((parent or {}).get("title") or "")) or None,
            "category_plan_node_id": page.get("parentPlanNodeId") or None,
            "budget_amount": _money(values.get("budget", "")),
            "budget_text": values.get("budget") or None,
            "expenditure_amount": _money(values.get("expenditure", "")),
            "expenditure_text": values.get("expenditure") or None,
            "start_date": start.isoformat() if start else None,
            "end_date": end.isoformat() if end else None,
            "latest_update": latest_update or None,
            "tags": [tag for tag in (page.get("tags") or []) if tag] or None,
        }
        # Any label this tenant carries beyond the ones normalized above is kept
        # under the name config gave it rather than dropped.
        for field, text in values.items():
            if field not in normalized:
                normalized[field] = text or None
        normalized = {k: v for k, v in normalized.items() if v not in (None, "", [], {})}

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=f"envisio:{self.sub_domain}:{key}",
            canonical_url=f"{self.dashboard_url}/{key}",
            # Envisio publishes no per-project created or updated timestamp; leaving
            # these empty is honest, and the project's own dates are normalized above.
            source_created_at=None,
            source_updated_at=None,
            raw_payload={"page": page, "parent": parent or {}},
            normalized_payload=normalized,
        )

    def _schema_fingerprint(self, projects: dict[str, dict[str, Any]]) -> str | None:
        if not projects:
            return None
        keys: set[str] = set()
        for page in projects.values():
            keys.update(page.keys())
        shape = {
            "page_fields": sorted(keys),
            "description_labels": sorted(self.description_labels),
        }
        return hashlib.sha256(
            json.dumps(shape, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()

    # ------------------------------------------------------------------ contract

    async def canary(self) -> bool:
        async with self._session() as client:
            published = await self._publish_data(client)
        pages = published.get("pages")
        if not isinstance(pages, dict) or not pages:
            # An unknown subdomain answers HTTP 200 with an empty object. That is a
            # broken source, not a quiet day.
            return False
        projects = self._project_pages(pages)
        if len(projects) < self.min_expected_projects:
            return False
        first = next(iter(projects.values()))
        fields = self._labelled_fields(str(first.get("description") or ""))
        return self.required_labels.issubset(fields.keys())

    async def collect(self) -> CollectorResult:
        async with self._session() as client:
            published = await self._publish_data(client)

        pages = published.get("pages")
        pages = pages if isinstance(pages, dict) else {}
        settings = published.get("generalSettings")
        settings = settings if isinstance(settings, dict) else {}
        projects = self._project_pages(pages)

        records: list[NormalizedRecord] = []
        unparsed: list[str] = []
        for key, page in projects.items():
            parent = pages.get(str(page.get("parentPlanNodeId") or ""))
            record = self._record(key, page, parent if isinstance(parent, dict) else None)
            if record is None:
                unparsed.append(key)
                continue
            records.append(record)

        phases: dict[str, int] = {}
        categories: dict[str, int] = {}
        for record in records:
            payload = record.normalized_payload
            phase = str(payload.get("project_phase") or "unstated")
            phases[phase] = phases.get(phase, 0) + 1
            category = str(payload.get("category") or "uncategorised")
            categories[category] = categories.get(category, 0) + 1

        return CollectorResult(
            records=records,
            schema_fingerprint=self._schema_fingerprint(projects),
            # Divided by the project pages, not by every page in the payload. The
            # dashboard also returns the home page, the categories and the
            # performance measures, and dividing by those would report a parse
            # failure on a run where every project parsed.
            parser_yield=len(records) / len(projects) if projects else 1.0,
            metadata={
                "sub_domain": self.sub_domain,
                "organisation": settings.get("name"),
                "plan_name": settings.get("planName"),
                "graphql_endpoint": self._endpoint_used,
                "graphql_endpoint_discovered": self._endpoint_discovered,
                "pages_returned": len(pages),
                "project_pages": len(projects),
                # The agency's own status tally across its activities. A count that
                # disagrees with the number of project pages means the payload and
                # the dashboard's own header are telling different stories.
                "projects_counted_by_agency": _agency_activity_count(settings),
                "rows_unparsed": len(unparsed),
                "unparsed_plan_node_ids": unparsed[:10] or None,
                "projects_missing_expenditure": sum(
                    1 for r in records if "expenditure_amount" not in r.normalized_payload
                ),
                "projects_missing_budget": sum(
                    1 for r in records if "budget_amount" not in r.normalized_payload
                ),
                "projects_without_latest_update": sum(
                    1 for r in records if "latest_update" not in r.normalized_payload
                ),
                "phases": phases,
                "categories": categories,
            },
        )

    @asynccontextmanager
    async def _session(self):
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        ) as client:
            yield client


def _agency_activity_count(settings: dict[str, Any]) -> int | None:
    """Sum the dashboard header's own status counts, which total its activities."""

    fields = (
        "onTrackCount",
        "upcomingCount",
        "completedCount",
        "someDisruptionCount",
        "majorDisruptionCount",
        "discontinuedCount",
        "statusPendingCount",
    )
    present = [settings.get(field) for field in fields if isinstance(settings.get(field), int)]
    return sum(present) if present else None


def _graphql_error(errors: Any) -> str:
    """Repeat GraphQL's own message back, so a failure says what the server said."""

    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return " ".join(str(errors[0].get("message") or "").split())[:200] or "no message"
    return " ".join(str(errors).split())[:200] or "no message"
