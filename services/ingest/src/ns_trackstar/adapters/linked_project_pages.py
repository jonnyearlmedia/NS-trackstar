"""Project inventories published as an index of links to per-project pages.

Plenty of cities run no project database. They run a page that lists projects
under headings a resident understands -- "Active Projects", "Upcoming Projects",
"Completed Projects" -- where each entry links to a page of prose written by the
engineer running the job. That prose is the best answer this product has to "what
is happening on my street and why", so it is collected rather than reduced to a
title.

Two things this adapter is careful about.

The heading a project sits under is read from document order, not from the DOM
nesting. Content editors routinely leave the next group's heading inside the last
item of the previous group, so a nesting-based reading silently files the whole
list under one stage.

The heading is a hint, never the project's status. A city that lists a job under
"Active" and writes "construction complete" in its own scope note is telling you
two different things, and the page's own words win. The group is recorded as what
it is: the section the city filed the link under.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

_HEADINGS = ("h1", "h2", "h3", "h4")


def _clean(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _section_key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _clean(label).casefold()).strip("_")


def parse_index(
    html_text: str,
    *,
    base_url: str,
    content_selector: str,
    item_selector: str,
    heading_tags: tuple[str, ...] = _HEADINGS,
    same_host_only: bool = True,
) -> list[dict[str, str]]:
    """Return each linked project with the section heading it appears under.

    Traversal is in document order precisely because the markup nesting lies: the
    heading that introduces a group is often authored inside the body of the last
    item of the group before it.
    """

    soup = BeautifulSoup(html_text, "html.parser")
    root = soup.select_one(content_selector) or soup
    for node in root.select("script,style,nav,header,footer"):
        node.decompose()

    wanted = set(root.select(item_selector))
    entries: dict[str, dict[str, str]] = {}
    group = ""
    for node in root.find_all(tuple(heading_tags) + ("a",)):
        if node.name in heading_tags:
            # A heading that wraps a project link is that project's title, not the
            # name of a group. Reading it as a group files every project under the
            # previous project's name.
            if any(anchor in wanted for anchor in node.find_all("a")):
                continue
            label = _clean(node.get_text(" ", strip=True))
            if label:
                group = label
            continue
        if node not in wanted:
            continue
        href = str(node.get("href") or "")
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href)
        if same_host_only and urlsplit(url).netloc != urlsplit(base_url).netloc:
            continue
        title = _clean(node.get_text(" ", strip=True))
        if not title:
            continue
        entries.setdefault(url, {"url": url, "title": title, "group": group})
    return list(entries.values())


def parse_detail(
    html_text: str,
    *,
    content_selector: str,
    section_tags: tuple[str, ...] = ("h2", "h3", "h4"),
) -> dict[str, Any]:
    """Return a project page's title and its labelled sections.

    Sections are found by walking the page's text in document order and asking, of
    every piece of it, whether it sits inside a heading element. That is deliberately
    tag-agnostic: plenty of city pages mark "Scope" and "Funding Source" with a bold
    run inside a paragraph rather than a real heading, and a parser that only knows
    `h2` reads those pages as one undifferentiated block of prose.
    """

    soup = BeautifulSoup(html_text, "html.parser")
    root = soup.select_one(content_selector) or soup
    for node in root.select("script,style,nav,header,footer"):
        node.decompose()

    detail: dict[str, Any] = {}
    heading = root.find("h1")
    if heading is not None:
        detail["title"] = _clean(heading.get_text(" ", strip=True))
        heading.decompose()

    sections: dict[str, str] = {}
    label_parts: list[str] = []
    body_parts: list[str] = []
    current: str | None = None

    def flush() -> None:
        if current and body_parts:
            text = " ".join(body_parts).strip()
            if text:
                sections.setdefault(current, text)

    for string in root.find_all(string=True):
        text = _clean(str(string))
        if not text:
            continue
        if string.find_parent(list(section_tags)) is not None:
            if body_parts or current is None:
                flush()
                body_parts = []
                label_parts = []
            label_parts.append(text)
            current = _section_key(" ".join(label_parts))
            continue
        body_parts.append(text)
    flush()

    if sections:
        detail["sections"] = sections
        detail["description"] = next(iter(sections.values()))
        return detail

    body = [_clean(node.get_text(" ", strip=True)) for node in root.find_all(["p", "li"])]
    joined = " ".join(part for part in body if part)
    if joined:
        detail["description"] = joined
    return detail


class LinkedProjectPagesAdapter(CollectorAdapter):
    """Collect a city's project inventory from one index page and its project pages."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.index_url = str(config.options.get("index_url") or config.base_url)
        self.content_selector = str(config.options.get("content_selector", "body"))
        self.detail_content_selector = str(
            config.options.get("detail_content_selector", self.content_selector)
        )
        self.item_selector = str(config.options.get("item_selector", "a"))
        # Engineers label the same thing differently from page to page: "Construction
        # Cost" on one, "Cost" on the next. The synonyms live in config, where they can
        # be read and argued with, and the page's own label is always kept alongside.
        self.section_aliases = {
            str(canonical): [str(name) for name in names]
            for canonical, names in (config.options.get("section_aliases") or {}).items()
        }
        self.section_tags = tuple(
            str(tag) for tag in (config.options.get("detail_section_tags") or ["h2", "h3", "h4"])
        )
        # A city that writes its group labels as bold runs rather than headings is
        # still grouping its projects, so which tags count as a heading is config.
        self.heading_tags = tuple(
            str(tag) for tag in (config.options.get("index_heading_tags") or list(_HEADINGS))
        )
        # Off-site links are dropped by default, because most of them are navigation.
        # A city that points one of its own project entries at a state programme page
        # is different, and that list is worth keeping whole.
        self.same_host_only = bool(config.options.get("same_host_only", True))
        self.id_query_param = config.options.get("id_query_param")
        self.group_stages = {
            str(key).casefold(): str(value)
            for key, value in (config.options.get("group_stages") or {}).items()
        }
        self.fetch_details = bool(config.options.get("fetch_details", True))
        self.max_projects = int(config.options.get("max_projects", 100))
        self.min_expected_projects = int(config.options.get("min_expected_projects", 1))
        self.timeout_seconds = float(config.options.get("timeout_seconds", 45))
        self.min_request_interval_seconds = float(
            config.options.get("min_request_interval_seconds", 0.5)
        )

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str:
        response = await client.get(url, headers={"User-Agent": "NS-Trackstar/0.1"})
        if response.status_code in {401, 403, 429}:
            raise SourceBlockedError(
                "Project page request is explicitly blocked: "
                f"status={response.status_code} url={url}"
            )
        response.raise_for_status()
        return response.text

    def _identity(self, url: str) -> str:
        if self.id_query_param:
            values = parse_qs(urlsplit(url).query).get(str(self.id_query_param)) or []
            if values:
                return str(values[0])
        path = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        if path and path.casefold() not in {"index.asp", "index.html", "default.aspx"}:
            return path
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _stage(self, group: str) -> str | None:
        folded = _clean(group).casefold()
        for needle, stage in self.group_stages.items():
            if needle in folded:
                return stage
        return None

    async def _walk(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        )
        collected: list[dict[str, Any]] = []
        details = 0
        try:
            entries = parse_index(
                await self._fetch(client, self.index_url),
                base_url=self.index_url,
                content_selector=self.content_selector,
                item_selector=self.item_selector,
                heading_tags=self.heading_tags,
                same_host_only=self.same_host_only,
            )
            for entry in entries[: self.max_projects]:
                record = dict(entry)
                record["detail"] = {}
                if self.fetch_details:
                    if self.min_request_interval_seconds:
                        await asyncio.sleep(self.min_request_interval_seconds)
                    record["detail"] = parse_detail(
                        await self._fetch(client, entry["url"]),
                        content_selector=self.detail_content_selector,
                        section_tags=self.section_tags,
                    )
                    details += 1
                collected.append(record)
        finally:
            if owns:
                await client.aclose()
        return collected, {"index_entries": len(collected), "detail_pages_fetched": details}

    def _record(self, entry: dict[str, Any]) -> NormalizedRecord:
        detail: dict[str, Any] = entry["detail"]
        normalized: dict[str, Any] = {
            "record_kind": "curated_project",
            "name": detail.get("title") or entry["title"],
            "description": detail.get("description"),
            # The section the city filed this link under. Named for what it is,
            # because it is weaker evidence than the page's own words.
            "index_section": entry.get("group") or None,
            "project_page": entry["url"],
        }
        stage = self._stage(entry.get("group") or "")
        if stage:
            normalized["index_lifecycle_hint"] = stage
        sections = detail.get("sections") or {}
        for key, value in sections.items():
            normalized.setdefault(key, value)
        for canonical, names in self.section_aliases.items():
            for name in names:
                if sections.get(name):
                    normalized.setdefault(canonical, sections[name])
                    break

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=self._identity(entry["url"]),
            canonical_url=entry["url"],
            raw_payload={"index": {k: v for k, v in entry.items() if k != "detail"},
                         "detail": detail},
            normalized_payload=normalized,
        )

    async def canary(self) -> bool:
        """The index must still resolve to linked, titled projects.

        A city does not stop building. An index that yields nothing is a moved page
        or a template change, so it fails rather than passing as a quiet run.
        """

        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        )
        try:
            entries = parse_index(
                await self._fetch(client, self.index_url),
                base_url=self.index_url,
                content_selector=self.content_selector,
                item_selector=self.item_selector,
                heading_tags=self.heading_tags,
                same_host_only=self.same_host_only,
            )
        except (httpx.HTTPError, SourceBlockedError):
            return False
        finally:
            if owns:
                await client.aclose()
        return len(entries) >= self.min_expected_projects

    async def collect(self) -> CollectorResult:
        collected, counters = await self._walk()
        records = [self._record(entry) for entry in collected]

        groups = sorted({str(entry.get("group") or "") for entry in collected if entry.get("group")})
        labels = sorted(
            {key for entry in collected for key in (entry["detail"].get("sections") or {})}
        )
        # The group names are part of the shape even when no page carries sections:
        # a city that renames "Active Projects" has changed what the list means.
        shape = groups + labels
        fingerprint = hashlib.sha256("|".join(shape).encode()).hexdigest() if shape else None
        described = sum(1 for record in records if record.normalized_payload.get("description"))
        return CollectorResult(
            records=records,
            schema_fingerprint=fingerprint,
            parser_yield=(len(records) / counters["index_entries"]) if counters["index_entries"] else 0.0,
            metadata={
                **counters,
                "index_sections_seen": groups,
                "detail_sections_seen": labels,
                "projects_with_a_description": described,
            },
        )
