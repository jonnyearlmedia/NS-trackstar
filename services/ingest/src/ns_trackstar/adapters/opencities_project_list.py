"""OpenCities project lists.

A Granicus OpenCities city publishes a project inventory as a list page whose
items are structured markup, not prose: `div.oc-quick-list` holds one
`div.list-item-container` per project, each carrying a title, a one-line summary
and a link to a detail page.

The detail page is where the value is. It carries labelled fields
(`ul.content-details-list` as label/value pairs), a written description, named
document panels ("PROJECT DOCUMENTS", "TRAFFIC DISRUPTIONS"), a street address,
and the city's own geocode of that address inside its map widget.

The geocode is taken, and that is a deliberate exception to Trackstar's usual
refusal to read coordinates out of a page. This is not a map link's viewport
centre; it is the agency's own published marker for its own project, carried in
the same markup that draws the map a resident sees on the city's website. It is
recorded as an address-level fix attributed to that page, so its provenance is
visible and can be argued with, rather than being laundered into the record.
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
from ns_trackstar.models import CollectorResult, LocationAccuracy, NormalizedRecord

_LATLONG = re.compile(
    r"^\s*(?P<lat>-?\d{1,3}(?:\.\d+)?)\s*,\s*(?P<lon>-?\d{1,3}(?:\.\d+)?)\s*$"
)


def _clean(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _field_key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _clean(label).casefold()).strip("_")


def parse_latlong(value: str) -> tuple[float, float] | None:
    """Return (lat, lon) for an OpenCities marker, or None when it is not usable.

    Anything outside real latitude/longitude range, and the 0,0 an unset marker
    produces, is rejected rather than placed in the Gulf of Guinea.
    """

    match = _LATLONG.match(str(value or ""))
    if not match:
        return None
    lat = float(match.group("lat"))
    lon = float(match.group("lon"))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0 and lon == 0:
        return None
    return lat, lon


def parse_list_page(html_text: str, *, base_url: str) -> list[dict[str, str]]:
    """Return one entry per project in the page's OpenCities list widget."""

    soup = BeautifulSoup(html_text, "html.parser")
    entries: dict[str, dict[str, str]] = {}
    for container in soup.select("div.oc-quick-list div.list-item-container"):
        anchor = container.select_one("a[href]")
        if anchor is None:
            continue
        url = urljoin(base_url, str(anchor.get("href") or ""))
        if urlsplit(url).netloc != urlsplit(base_url).netloc:
            continue
        title_tag = container.select_one(".list-item-title")
        title = _clean(title_tag.get_text(" ", strip=True)) if title_tag else ""
        paragraphs = [
            _clean(node.get_text(" ", strip=True))
            for node in anchor.select("p")
            if "oc-thumbnail-image" not in (node.get("class") or [])
        ]
        summary = next((text for text in paragraphs if text), "")
        if not title:
            continue
        entries.setdefault(url, {"url": url, "title": title, "summary": summary})
    return list(entries.values())


def parse_detail_page(html_text: str) -> dict[str, Any]:
    """Return the structured content of one OpenCities project page."""

    soup = BeautifulSoup(html_text, "html.parser")
    main = soup.select_one("div.content-main-container") or soup
    for node in main.select("script,style"):
        node.decompose()

    detail: dict[str, Any] = {}
    heading = main.select_one("h1.oc-page-title") or main.find("h1")
    if heading is not None:
        detail["title"] = _clean(heading.get_text(" ", strip=True))

    for item in main.select("ul.content-details-list li"):
        label = item.select_one(".field-label")
        value = item.select_one(".field-value")
        if label is None or value is None:
            continue
        key = _field_key(label.get_text(" ", strip=True))
        if key:
            detail[key] = _clean(value.get_text(" ", strip=True))

    panels: dict[str, str] = {}
    for panel in main.select("div.oc-wysiwyg-container-panel"):
        panel_heading = panel.find(["h2", "h3"])
        body = panel.select_one(".oc-wysiwyg-container-panel-content")
        if panel_heading is None or body is None:
            continue
        panels[_field_key(panel_heading.get_text(" ", strip=True))] = _clean(
            body.get_text(" ", strip=True)
        )
    if panels:
        detail["panels"] = panels

    marker = main.select_one("div.gmap-marker")
    if marker is not None:
        latlong = marker.select_one(".gmap-latlong")
        address = marker.select_one(".gmap-address")
        if latlong is not None:
            point = parse_latlong(latlong.get_text(" ", strip=True))
            if point is not None:
                detail["latitude"], detail["longitude"] = point
        if address is not None:
            detail["address"] = _clean(address.get_text(" ", strip=True)).replace(" ,", ",")

    # The page's own description is every paragraph above the named panels. The
    # summary the list page carries is one line; this is the real explanation, and
    # it is what a resident is actually asking for.
    body_paragraphs: list[str] = []
    for node in main.select("div.col-m-8 > p, div.col-m-8 p"):
        if node.find_parent("div", class_="oc-wysiwyg-container-panel"):
            continue
        if node.find_parent("div", class_="gmap-marker"):
            continue
        text = _clean(node.get_text(" ", strip=True))
        if text and text not in body_paragraphs:
            body_paragraphs.append(text)
    if body_paragraphs:
        detail["description"] = " ".join(body_paragraphs)

    return detail


class OpenCitiesProjectListAdapter(CollectorAdapter):
    """Collect a city's project inventory from its OpenCities list and detail pages."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.site_url = str(config.options.get("site_url") or config.base_url).rstrip("/")
        lists = config.options.get("lists") or []
        if not lists:
            raise ValueError("OpenCities project list config needs at least one list page")
        self.lists = [dict(entry) for entry in lists]
        self.fetch_details = bool(config.options.get("fetch_details", True))
        self.min_expected_projects = int(config.options.get("min_expected_projects", 1))
        self.max_projects = int(config.options.get("max_projects", 200))
        self.timeout_seconds = float(config.options.get("timeout_seconds", 45))
        self.min_request_interval_seconds = float(
            config.options.get("min_request_interval_seconds", 0.5)
        )

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str:
        response = await client.get(url, headers={"User-Agent": "NS-Trackstar/0.1"})
        if response.status_code in {401, 403, 429}:
            raise SourceBlockedError(
                "OpenCities project page request is explicitly blocked: "
                f"status={response.status_code} url={url}"
            )
        response.raise_for_status()
        return response.text

    async def _walk(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        )
        collected: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        details_fetched = 0
        try:
            for entry in self.lists:
                list_url = urljoin(f"{self.site_url}/", str(entry["url"]).lstrip("/"))
                items = parse_list_page(await self._fetch(client, list_url), base_url=list_url)
                counts[str(entry.get("label") or entry["url"])] = len(items)
                for item in items:
                    if len(collected) >= self.max_projects:
                        break
                    record: dict[str, Any] = {
                        **item,
                        "list_label": str(entry.get("label") or entry["url"]),
                        "lifecycle_stage": entry.get("lifecycle_stage"),
                        "detail": {},
                    }
                    if self.fetch_details:
                        if self.min_request_interval_seconds:
                            await asyncio.sleep(self.min_request_interval_seconds)
                        record["detail"] = parse_detail_page(
                            await self._fetch(client, item["url"])
                        )
                        details_fetched += 1
                    collected.append(record)
        finally:
            if owns:
                await client.aclose()
        return collected, {"projects_by_list": counts, "detail_pages_fetched": details_fetched}

    def _record(self, entry: dict[str, Any]) -> NormalizedRecord:
        detail: dict[str, Any] = entry["detail"]
        # The URL's last path segment is the city's own slug for the project and is
        # stable across edits to the title, so it is the identity rather than a hash
        # of the name.
        slug = urlsplit(entry["url"]).path.rstrip("/").rsplit("/", 1)[-1]
        identity = slug or hashlib.sha256(entry["url"].encode()).hexdigest()[:12]

        normalized: dict[str, Any] = {
            "record_kind": "curated_project",
            "name": detail.get("title") or entry["title"],
            "summary": entry.get("summary") or None,
            "description": detail.get("description") or entry.get("summary") or None,
            "address": detail.get("address"),
            "list_label": entry["list_label"],
            "project_page": entry["url"],
        }
        if entry.get("lifecycle_stage"):
            normalized["lifecycle_stage"] = entry["lifecycle_stage"]
        for key, value in detail.items():
            if key in {"panels", "latitude", "longitude", "title", "description", "address"}:
                continue
            normalized.setdefault(key, value)
        for key, value in (detail.get("panels") or {}).items():
            normalized.setdefault(key, value)

        geometry = None
        accuracy = None
        if detail.get("latitude") is not None and detail.get("longitude") is not None:
            geometry = {
                "type": "Point",
                "coordinates": [detail["longitude"], detail["latitude"]],
            }
            accuracy = LocationAccuracy.EXACT_ADDRESS

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=identity,
            canonical_url=entry["url"],
            raw_payload={"list_item": {k: v for k, v in entry.items() if k != "detail"},
                         "detail": detail},
            normalized_payload=normalized,
            geometry_geojson=geometry,
            geometry_source=entry["url"] if geometry else None,
            location_accuracy=accuracy,
        )

    async def canary(self) -> bool:
        """Every configured list page must still yield identified projects.

        A city does not stop building. An empty list is a moved page or a template
        change, so it fails rather than passing as a quiet zero-result run.
        """

        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        )
        try:
            total = 0
            for entry in self.lists:
                list_url = urljoin(f"{self.site_url}/", str(entry["url"]).lstrip("/"))
                total += len(parse_list_page(await self._fetch(client, list_url), base_url=list_url))
        except (httpx.HTTPError, SourceBlockedError):
            return False
        finally:
            if owns:
                await client.aclose()
        return total >= self.min_expected_projects

    async def collect(self) -> CollectorResult:
        collected, counts = await self._walk()
        records = [self._record(entry) for entry in collected]

        labels = sorted(
            {key for entry in collected for key in (entry["detail"] or {}) if key != "panels"}
        )
        fingerprint = hashlib.sha256("|".join(labels).encode()).hexdigest() if labels else None
        located = sum(1 for record in records if record.geometry_geojson is not None)
        return CollectorResult(
            records=records,
            schema_fingerprint=fingerprint,
            parser_yield=(len(records) / len(collected)) if collected else 0.0,
            metadata={
                **counts,
                "projects": len(records),
                "projects_with_published_coordinates": located,
                "detail_fields_seen": labels,
            },
        )
