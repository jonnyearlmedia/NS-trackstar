"""PlanetBids vendor portals.

A PlanetBids agency publishes its bid opportunities through a single-page app on
`vendors.planetbids.com`. Every earlier attempt at this source probed that host for
an API and found the app's own index page at every path, and concluded the request
contract could not be read. The contract was readable the whole time, just not
there: the portal ships a runtime config file that names a different host entirely.

    GET https://vendors.planetbids.com/ember-runtime-config-<hash>.js
        -> window.__emberRuntimeConfig__.HOST_URL
        == https://api-external.prod.planetbids.com

So `vendors.planetbids.com` serves the application and `api-external.prod` serves
the data, and a path that does not exist on the app host falls through to the app's
index rather than answering 404. That is what "serves its own index page in place of
every asset" was actually describing.

Three things about the API are worth stating because none of them is guessable:

*   The list endpoint takes plain snake_case query parameters, not the JSON:API
    ``filter[...]`` form its response shape would suggest. ``cid`` is the agency.
*   Every request needs ``Referer: https://vendors.planetbids.com/``. Without it the
    API answers HTTP 400 with ``{"code": "DIRECT_ACCESS"}``. This is the portal's own
    same-origin expectation, and sending it is what a browser does for the portal's
    own fetches; nothing is being impersonated.
*   A bid's detail additionally needs a ``company-id`` header carrying the same
    agency id. Without it the detail answers 400 while the list answers fine, which
    is a good way to have a collector that half works.

Document links are recorded by name and not synthesised. The API returns a server
path and a stored filename, and stitching those into a URL would be inventing an
endpoint; the canonical link stays the agency's own bid page.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

_API_HOST = "https://api-external.prod.planetbids.com"
_PORTAL_ORIGIN = "https://vendors.planetbids.com"
_LIST_PATH = "/papi/bids"
_DETAIL_PATH = "/papi/bid-details"
_FILES_PATH = "/papi/bid-downloadable-files"
_AGENCY_PATH = "/papi/agencies"

# The fields the list endpoint must keep returning for this source to mean anything.
_REQUIRED_LIST_FIELDS = ("bidId", "title", "stageStr", "bidDueDate", "issueDate")

# Waits after an empty HTTP 202, which is how this API says "slow down".
_THROTTLE_BACKOFF_SECONDS = (2.0, 5.0, 10.0, 20.0)


def _moment(value: Any, *, timezone: ZoneInfo) -> datetime | None:
    """Read PlanetBids' ``YYYY-MM-DD HH:MM:SS.fff`` agency-local clock."""

    text = " ".join(str(value or "").split())
    if not text:
        return None
    for shape in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, shape)  # noqa: DTZ007 - agency-local
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone)
    return None


def _naics_codes(value: Any) -> list[str]:
    """Split the comma-joined NAICS string the API returns into its codes."""

    return [part.strip() for part in str(value or "").split(",") if part.strip()]


class PlanetBidsAdapter(CollectorAdapter):
    """Collect an agency's published bid opportunities from its PlanetBids portal."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self._last_request_at: float | None = None
        self._throttled = 0
        options = config.options
        self.agency_id = str(options.get("agency_id") or "").strip()
        if not self.agency_id.isdigit():
            raise ValueError("PlanetBids agency_id (the portal id) is required")
        self.api_host = str(options.get("api_host") or _API_HOST).rstrip("/")
        self.portal_origin = str(options.get("portal_origin") or _PORTAL_ORIGIN).rstrip("/")
        self.timezone = ZoneInfo(str(options.get("timezone", "America/Los_Angeles")))
        self.per_page = max(1, min(100, int(options.get("per_page", 30))))
        self.max_pages = max(1, int(options.get("max_pages", 20)))
        self.fetch_details = bool(options.get("fetch_details", True))
        self.fetch_documents = bool(options.get("fetch_documents", True))
        self.min_expected_bids = int(options.get("min_expected_bids", 1))
        # PlanetBids refuses a bare "NS-Trackstar/0.1", "NS-Trackstar-Bot/0.1" and
        # "curl/8.7.1" with HTTP 403, and accepts the conventional
        # "Mozilla/5.0 (compatible; <name>; +<url>)" shape. That is a crude prefix
        # filter rather than a bot challenge, and the string below is not a
        # disguise: it names NS-Trackstar and gives a contact URL, which is how
        # every well-behaved crawler has identified itself for thirty years. We do
        # not claim to be Chrome anywhere, and if this ever stops working the answer
        # is to record the source as blocked, not to start pretending.
        self.user_agent = str(
            options.get("user_agent")
            or "Mozilla/5.0 (compatible; NS-Trackstar/0.1; +https://github.com/jonnyearlmedia/NS-trackstar)"
        )
        self.min_interval = float(options.get("min_request_interval_seconds", 1.0))
        self.timeout_seconds = float(options.get("timeout_seconds", 45))
        host = urlparse(self.api_host).hostname
        if not host:
            raise ValueError("PlanetBids api_host must be an absolute https URL")
        self._allowed_host = host

    # ------------------------------------------------------------------ transport

    def _headers(self, *, with_company: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.api+json",
            "Referer": f"{self.portal_origin}/",
            "Origin": self.portal_origin,
            "User-Agent": self.user_agent,
            "timezone-name": str(self.timezone),
        }
        if with_company:
            headers["company-id"] = self.agency_id
        return headers

    async def _pace(self) -> None:
        if self.min_interval <= 0 or self._last_request_at is None:
            return
        delay = self.min_interval - (asyncio.get_running_loop().time() - self._last_request_at)
        if delay > 0:
            await asyncio.sleep(delay)

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        with_company: bool = False,
    ) -> dict[str, Any] | None:
        url = f"{self.api_host}{path}"
        if urlparse(url).hostname != self._allowed_host:
            raise RuntimeError("PlanetBids request attempted to leave the configured API host")

        # PlanetBids throttles by answering HTTP 202 with an empty body rather than
        # 429. It clears within a few seconds. Reading that as "this bid has no
        # documents" would quietly under-report attachments on exactly the bids the
        # collector asked about fastest, so it is waited out and retried, and a
        # throttle that never clears is raised rather than swallowed.
        for attempt in range(len(_THROTTLE_BACKOFF_SECONDS) + 1):
            await self._pace()
            try:
                response = await client.get(
                    url, params=params, headers=self._headers(with_company=with_company)
                )
            finally:
                self._last_request_at = asyncio.get_running_loop().time()
            if response.status_code == 202 and not response.content:
                if attempt >= len(_THROTTLE_BACKOFF_SECONDS):
                    raise RuntimeError(
                        "PlanetBids kept throttling this request with an empty HTTP 202 "
                        f"after {attempt} waits; the run is incomplete rather than empty"
                    )
                self._throttled += 1
                await asyncio.sleep(_THROTTLE_BACKOFF_SECONDS[attempt])
                continue
            break

        if response.status_code in {401, 403}:
            raise SourceBlockedError(
                f"PlanetBids API rejected anonymous access with HTTP {response.status_code}"
            )
        if response.status_code == 404:
            return None
        if response.status_code == 400:
            # The API states its own refusals. DIRECT_ACCESS means the same-origin
            # headers did not arrive, which is a broken collector rather than a
            # blocked source, so it must not be reported as an empty result.
            raise RuntimeError(f"PlanetBids refused the request: {_api_error(response.text)}")
        response.raise_for_status()
        try:
            return response.json()
        except json.JSONDecodeError:
            raise RuntimeError("PlanetBids returned a non-JSON body where JSON:API was expected")

    # ------------------------------------------------------------------ requests

    def _list_params(self, page: int) -> dict[str, Any]:
        """The portal's own query, reproduced exactly rather than trimmed.

        Every one of these is sent by the portal even when empty. Dropping the empty
        ones is the kind of tidy-up that works until the day the API starts requiring
        one, so they are kept as the app sends them.
        """

        return {
            "bid_type_id": 0,
            "cid": self.agency_id,
            "dept_id": 0,
            "due_date_from": "",
            "due_date_to": "",
            "keyword": "",
            "page": page,
            "per_page": self.per_page,
            "sort_by": "",
            "sort_order": -1,
            "stage_id": 0,
        }

    async def _bid_pages(self, client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        total_reported = 0
        page = 1
        while page <= self.max_pages:
            payload = await self._get(client, _LIST_PATH, params=self._list_params(page))
            if payload is None:
                break
            meta = payload.get("meta") or {}
            total_reported = int(meta.get("totalBids") or total_reported)
            batch = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
            if not batch:
                break
            rows.extend(batch)
            total_pages = int(meta.get("totalPages") or 0)
            if total_pages and page >= total_pages:
                break
            page += 1
        return rows, total_reported

    async def _detail(self, client: httpx.AsyncClient, bid_id: str) -> dict[str, Any]:
        payload = await self._get(
            client, f"{_DETAIL_PATH}/{bid_id}", with_company=True
        )
        data = (payload or {}).get("data") or {}
        attributes = data.get("attributes")
        return attributes if isinstance(attributes, dict) else {}

    async def _documents(self, client: httpx.AsyncClient, bid_id: str) -> list[dict[str, Any]]:
        payload = await self._get(client, _FILES_PATH, params={"bid_id": bid_id})
        documents = []
        for item in (payload or {}).get("data") or []:
            attributes = (item or {}).get("attributes") or {}
            if not attributes:
                continue
            documents.append(
                {
                    "title": attributes.get("fileTitle"),
                    "filename": attributes.get("filename"),
                    "file_size_bytes": attributes.get("fileSize"),
                    "uploaded_date": attributes.get("uploadedDate"),
                    "publicly_visible": attributes.get("publiclyVisible"),
                    "recalled": attributes.get("recalled"),
                }
            )
        return documents

    # ------------------------------------------------------------------ records

    def _bid_url(self, bid_id: str) -> str:
        return f"{self.portal_origin}/portal/{self.agency_id}/bo/bo-detail/{bid_id}"

    def _record(
        self,
        row: dict[str, Any],
        detail: dict[str, Any],
        documents: list[dict[str, Any]],
    ) -> NormalizedRecord | None:
        attributes = row.get("attributes") or {}
        bid_id = str(attributes.get("bidId") or row.get("id") or "").strip()
        title = " ".join(str(attributes.get("title") or detail.get("title") or "").split())
        if not bid_id or not title:
            return None

        issued = _moment(attributes.get("issueDate"), timezone=self.timezone)
        due = _moment(attributes.get("bidDueDate"), timezone=self.timezone)
        award_date = _moment(detail.get("awardDate"), timezone=self.timezone)

        normalized = {
            "record_kind": "procurement_solicitation",
            "bid_id": bid_id,
            "title": title,
            "invitation_number": attributes.get("invitationNum") or detail.get("invitationNum"),
            # stageStr is the agency's own word for where this bid is. It is kept as
            # written rather than folded into one inferred lifecycle state, because
            # "Bidding" and "Awarded" are decisions the agency published, not guesses.
            "stage": attributes.get("stageStr"),
            "stage_id": attributes.get("stageId"),
            "bid_type_id": attributes.get("bidTypeId") or detail.get("bidType"),
            "response_format": attributes.get("bidResponseFormatStr"),
            "by_invitation": attributes.get("byInvitation"),
            "issue_date": issued.isoformat() if issued else None,
            "due_date": due.isoformat() if due else None,
            "award_date": award_date.isoformat() if award_date else None,
            "naics_codes": _naics_codes(attributes.get("categoryIds")),
            "address": " ".join(
                part for part in (detail.get("address1"), detail.get("address2")) if part
            ).strip()
            or None,
            "city": detail.get("city") or None,
            "county": detail.get("legacyCounty") or None,
            "zip_code": detail.get("zipCode") or None,
            "scope": " ".join(str(detail.get("scope") or "").split()) or None,
            "estimated_value": detail.get("estimatedValue") or None,
            "licence_required": detail.get("licenseReq") or None,
            "contact_name": detail.get("contactNameAndPhone") or None,
            "contact_email": detail.get("contactEmail") or None,
            "pre_bid_meeting_date": detail.get("preBidMeetingDate") or None,
            "pre_bid_meeting_mandatory": bool(detail.get("preBidMtgMandatory") or 0) or None,
            "documents": documents or None,
            "document_count": len(documents) or None,
        }
        normalized = {k: v for k, v in normalized.items() if v not in (None, "", [], {})}

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=f"planetbids:{self.agency_id}:{bid_id}",
            canonical_url=self._bid_url(bid_id),
            source_created_at=issued,
            source_updated_at=None,
            raw_payload={"list_row": attributes, "detail": detail, "documents": documents},
            normalized_payload=normalized,
        )

    def _schema_fingerprint(self, rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        keys: set[str] = set()
        for row in rows:
            keys.update((row.get("attributes") or {}).keys())
        return hashlib.sha256(
            json.dumps(sorted(keys), separators=(",", ":")).encode()
        ).hexdigest()

    # ------------------------------------------------------------------ contract

    async def canary(self) -> bool:
        async with self._session() as client:
            agency = await self._get(client, f"{_AGENCY_PATH}/{self.agency_id}")
            attributes = ((agency or {}).get("data") or {}).get("attributes") or {}
            if not attributes.get("companyName"):
                return False
            # An agency that has switched the bid-opportunities module off is a real
            # answer about that agency, and it is not the same thing as a broken feed.
            if attributes.get("moduleBo") is False:
                raise SourceBlockedError(
                    f"{attributes.get('companyName')} has the PlanetBids bid-opportunity "
                    "module switched off, so it publishes no bids through this portal"
                )
            payload = await self._get(client, _LIST_PATH, params=self._list_params(1))
            rows = [item for item in ((payload or {}).get("data") or []) if isinstance(item, dict)]
            if len(rows) < self.min_expected_bids:
                return False
            first = rows[0].get("attributes") or {}
            return all(field in first for field in _REQUIRED_LIST_FIELDS)

    async def collect(self) -> CollectorResult:
        async with self._session() as client:
            rows, total_reported = await self._bid_pages(client)

            records: list[NormalizedRecord] = []
            skipped = 0
            for row in rows:
                bid_id = str((row.get("attributes") or {}).get("bidId") or "").strip()
                detail: dict[str, Any] = {}
                documents: list[dict[str, Any]] = []
                if bid_id and self.fetch_details:
                    detail = await self._detail(client, bid_id)
                if bid_id and self.fetch_documents:
                    documents = await self._documents(client, bid_id)
                record = self._record(row, detail, documents)
                if record is None:
                    skipped += 1
                    continue
                records.append(record)

        stages: dict[str, int] = {}
        for record in records:
            stage = str(record.normalized_payload.get("stage") or "unstated")
            stages[stage] = stages.get(stage, 0) + 1

        return CollectorResult(
            records=records,
            schema_fingerprint=self._schema_fingerprint(rows),
            parser_yield=len(records) / len(rows) if rows else 1.0,
            metadata={
                "agency_id": self.agency_id,
                "bids_listed": len(rows),
                # The agency's own count of what it published. A run that walks fewer
                # pages than exist should say so rather than quietly under-reporting.
                "bids_reported_by_agency": total_reported,
                "pages_capped": bool(total_reported and len(rows) < total_reported),
                "rows_skipped": skipped,
                "stages": stages,
                "throttled_waits": self._throttled,
                "detail_fetch": self.fetch_details,
                "document_fetch": self.fetch_documents,
            },
        )

    @asynccontextmanager
    async def _session(self):
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            yield client


def _api_error(body: str) -> str:
    """Repeat the API's own error back, so a failure says what the API said."""

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return " ".join(body.split())[:200] or "no message"
    errors = payload.get("errors") or []
    if errors and isinstance(errors[0], dict):
        first = errors[0]
        code = first.get("code")
        detail = first.get("detail") or ""
        return f"{detail} (code {code})" if code else str(detail)
    return " ".join(body.split())[:200] or "no message"
