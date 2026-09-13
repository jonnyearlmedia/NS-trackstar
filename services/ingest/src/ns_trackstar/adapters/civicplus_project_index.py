"""CivicPlus project index pages.

Small cities on CivicPlus rarely run a permit portal. What they run instead is a
hand-maintained set of pages: an index such as "Active Projects" or "Approved
Projects", and under it one page per planning case carrying a labelled field block:

    <h2 class="subhead1">Project ID</h2><p>PL25-034</p>
    <h2 class="subhead1">Project Status</h2><p>Approved</p>
    <h2 class="subhead1">Location</h2><p>1933 Spring St.</p><p>St. Helena, CA 94574</p>

That block is the whole point. It is the city's own structured statement of what a
project is, where it is and how far along it is, which is exactly what a resident
asking "what is happening on my street" needs, and it is published as ordinary
anonymous HTML.

Two things this adapter deliberately does not do:

It does not guess which links are projects. A linked page counts as a project only
when its own field block carries the configured identity label, so a navigation
change adds nothing and a removed project disappears rather than turning into a
half-empty record.

It does not read coordinates out of the "See map" link some pages carry. Those are
Google Maps place links, and a viewport centre is not a project location. The
address is collected instead and geocoded downstream against the county's
authoritative address points, which is a provenance Trackstar can defend.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

# CivicPlus page URLs are "/<page id>/<slug>". The page id is the stable half: the
# slug is derived from the title and changes when a clerk retitles the page.
_PAGE_PATH = re.compile(r"^/(?P<page_id>\d+)(?:/(?P<slug>[^/?#]*))?/?$")

_BLANK_VALUES = frozenset({"", "n/a", "na", "none", "tbd", "-", "--"})

# A location block is written as free paragraphs, and the first one is often the
# business name ("Farmstead at Long Meadow Ranch") rather than the street address.
# Only a line that starts with a street number is treated as an address; when none
# does, the project has no address and says so, instead of handing the geocoder a
# building's trade name.
_STREET_LINE = re.compile(r"^\d+[A-Za-z]?\s+\S")
_CITY_STATE_ZIP = re.compile(r",\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?$")


def street_address(lines: list[str]) -> str | None:
    for line in lines:
        cleaned = _clean(line)
        if _CITY_STATE_ZIP.search(cleaned):
            continue
        if _STREET_LINE.match(cleaned):
            return cleaned
    return None


def _clean(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _field_label(value: str) -> str:
    """Return a stable snake_case key for a human field label."""

    slug = re.sub(r"[^a-z0-9]+", "_", _clean(value).casefold()).strip("_")
    return slug


def page_id_of(url: str) -> str | None:
    match = _PAGE_PATH.match(urlsplit(url).path)
    return match.group("page_id") if match else None


def parse_field_block(html: str) -> dict[str, list[str]]:
    """Return every labelled field on a CivicPlus content page.

    Labels are the `h2` headings inside an editor widget; a field's value is every
    paragraph that follows it until the next heading. Values are kept as a list
    because the city writes multi-line values (a street line and a city/ZIP line)
    as separate paragraphs, and joining them blindly would corrupt the address.
    """

    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, list[str]] = {}
    for view in soup.select("div.fr-view"):
        for heading in view.find_all(["h2", "h3"]):
            label = _field_label(heading.get_text(" ", strip=True))
            if not label:
                continue
            values: list[str] = []
            for sibling in heading.next_siblings:
                name = getattr(sibling, "name", None)
                if name in {"h2", "h3"}:
                    break
                if name is None:
                    continue
                text = _clean(sibling.get_text(" ", strip=True))
                if text and text.casefold() not in _BLANK_VALUES:
                    values.append(text)
            if values and label not in fields:
                fields[label] = values
    return fields


def _body_containers(soup: BeautifulSoup) -> list[Any]:
    """Return just the page's own body, not the site chrome.

    CivicPlus reuses `div.pageContent` for the global quick-links and footer blocks as
    well as for the page body, so selecting that class alone drags the whole site
    navigation into the crawl. The body is the `div.pageContent` that immediately
    follows the page headline, so anchor on the headline instead.
    """

    headline = soup.select_one("h1#versionHeadLine")
    if headline is not None:
        for sibling in headline.next_siblings:
            classes = getattr(sibling, "get", lambda *_: None)("class") or []
            if getattr(sibling, "name", None) == "div" and "pageContent" in classes:
                return [sibling]
    first = soup.select_one("div.pageContent")
    return [first] if first is not None else [soup]


def child_page_links(html: str, *, base_url: str) -> list[str]:
    """Return the CivicPlus page links inside the page's own content area.

    Navigation, breadcrumbs and the footer also link to `/<id>/<slug>` pages, so the
    search is scoped to the content container the page body lives in.
    """

    soup = BeautifulSoup(html, "html.parser")
    containers = _body_containers(soup)
    seen: dict[str, None] = {}
    for container in containers:
        for anchor in container.select("a[href]"):
            href = str(anchor.get("href") or "")
            if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absolute = urljoin(base_url, href)
            if urlsplit(absolute).netloc != urlsplit(base_url).netloc:
                continue
            if page_id_of(absolute) is None:
                continue
            seen.setdefault(absolute, None)
    return list(seen)


class CivicPlusProjectIndexAdapter(CollectorAdapter):
    """Collect a small city's planning-project pages from its CivicPlus indexes."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.site_url = str(config.options.get("site_url") or config.base_url).rstrip("/")
        indexes = config.options.get("indexes") or []
        if not indexes:
            raise ValueError("CivicPlus project index config needs at least one index page")
        self.indexes = [dict(entry) for entry in indexes]
        self.identity_label = _field_label(str(config.options.get("identity_label", "Project ID")))
        self.max_depth = int(config.options.get("max_depth", 1))
        self.max_pages = int(config.options.get("max_pages", 200))
        self.min_expected_projects = int(config.options.get("min_expected_projects", 1))
        self.timeout_seconds = float(config.options.get("timeout_seconds", 30))
        self.min_request_interval_seconds = float(
            config.options.get("min_request_interval_seconds", 0.5)
        )
        self._pages: dict[str, str] = {}

    async def _fetch(self, url: str) -> str:
        if url in self._pages:
            return self._pages[url]
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        )
        try:
            response = await client.get(url, headers={"User-Agent": "NS-Trackstar/0.1"})
            if response.status_code in {401, 403, 429}:
                raise SourceBlockedError(
                    "CivicPlus project index request is explicitly blocked: "
                    f"status={response.status_code} url={url}"
                )
            response.raise_for_status()
            self._pages[url] = response.text
            return response.text
        finally:
            if owns:
                await client.aclose()
        # unreachable

    async def _walk(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        """Return {page url: project fields} plus counters describing the crawl."""

        found: dict[str, dict[str, Any]] = {}
        visited: set[str] = set()
        index_pages = 0
        fetched = 0

        for entry in self.indexes:
            index_url = urljoin(f"{self.site_url}/", str(entry["url"]).lstrip("/"))
            queue: list[tuple[str, int]] = [(index_url, 0)]
            while queue:
                url, depth = queue.pop(0)
                if url in visited or fetched >= self.max_pages:
                    continue
                visited.add(url)
                html = await self._fetch(url)
                fetched += 1
                if self.min_request_interval_seconds:
                    await asyncio.sleep(self.min_request_interval_seconds)

                fields = parse_field_block(html)
                if self.identity_label in fields:
                    found[url] = {
                        "fields": fields,
                        "index_label": str(entry.get("label") or entry["url"]),
                        "lifecycle_stage": entry.get("lifecycle_stage"),
                        "html": html,
                    }
                    continue

                index_pages += 1
                if depth < self.max_depth:
                    for child in child_page_links(html, base_url=url):
                        if child not in visited:
                            queue.append((child, depth + 1))

        return found, {
            "index_pages_read": index_pages,
            "pages_fetched": fetched,
            "project_pages": len(found),
        }

    def _record(self, url: str, payload: dict[str, Any]) -> NormalizedRecord:
        fields: dict[str, list[str]] = payload["fields"]
        flat = {label: " ".join(values) for label, values in fields.items()}
        identity = flat[self.identity_label]
        page_id = page_id_of(url) or hashlib.sha256(url.encode()).hexdigest()[:12]

        location_lines = fields.get("location") or []
        normalized: dict[str, Any] = {
            "record_kind": "curated_project",
            "planning_case": identity,
            "page_id": page_id,
            "project_page": url,
            "index_label": payload["index_label"],
            "address": street_address(location_lines),
            "location_text": " ".join(location_lines) or None,
        }
        # The index a page sits under is weaker evidence than the page's own status
        # field, and the two disagree in practice: a pre-application listed under
        # "Approved Projects" still reports "Under Review" on its own page. So the
        # section is recorded as what it is, and the status dimension comes from the
        # city's own field rather than from where a clerk filed the link.
        if payload.get("lifecycle_stage"):
            normalized["index_lifecycle_hint"] = payload["lifecycle_stage"]
        for label, value in flat.items():
            normalized.setdefault(label, value)

        title = flat.get("page_title") or normalized.get("project_name")
        if not title:
            soup = BeautifulSoup(payload["html"], "html.parser")
            heading = soup.select_one("h1#versionHeadLine") or soup.find("h1")
            title = _clean(heading.get_text(" ", strip=True)) if heading else identity
        normalized["name"] = title

        return NormalizedRecord(
            source_key=self.config.key,
            # The page id is the city's own stable identifier for this project page.
            # The case number is carried as an assertion rather than used as identity,
            # because a city can publish two pages for one case (a pre-application and
            # the application itself) and collapsing them here would lose one.
            external_id=f"{page_id}",
            canonical_url=url,
            raw_payload={"fields": fields},
            normalized_payload=normalized,
        )

    async def canary(self) -> bool:
        """Every configured index must still resolve to identified project pages.

        An index that stops yielding projects is a broken parse or a moved page, not a
        city that stopped approving buildings, so it fails rather than passing quietly.
        """

        try:
            found, _ = await self._walk()
        except (httpx.HTTPError, SourceBlockedError):
            return False
        return len(found) >= self.min_expected_projects

    async def collect(self) -> CollectorResult:
        found, counters = await self._walk()
        records = [self._record(url, payload) for url, payload in sorted(found.items())]

        labels = sorted({label for payload in found.values() for label in payload["fields"]})
        fingerprint = hashlib.sha256("|".join(labels).encode()).hexdigest() if labels else None
        attempted = counters["project_pages"]
        return CollectorResult(
            records=records,
            schema_fingerprint=fingerprint,
            parser_yield=(len(records) / attempted) if attempted else 0.0,
            metadata={
                **counters,
                "indexes": [str(entry["url"]) for entry in self.indexes],
                "field_labels_seen": labels,
            },
        )
