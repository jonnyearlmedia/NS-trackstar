"""Agency pages that publish a project list as headings rather than as a database.

A small planning department with no permit portal still has to notice projects
publicly, and the shape it reaches for is a single page where each project is a
heading followed by its description, its status line and links to its documents.
Dixon and unincorporated Solano County both publish their CEQA review pipeline this
way, and between them they show why this needs its own adapter rather than reuse.

Two things are deliberate here.

*   **Projects are delimited by document order, not by sibling structure.** On the
    Solano County page a project heading's content really is its following siblings.
    On Dixon's page every line is a row of a single-column layout table, so a
    heading's description is not a sibling of the heading at all - it is a sibling of
    the heading's grandparent. Walking the document in order and starting a new
    project at each heading reads both without knowing which is which, and without a
    per-site rule that a template change would silently break.

*   **The section a project is filed under is a hint and never its status.** Dixon's
    page carries one heading reading "UNDER REVIEW ENVIRONMENTAL REVIEW DOCUMENTS"
    above entries running from 1994 to 2026, and each entry states its own real
    status inline - adopted, certified, or a comment deadline. Believing the section
    heading would mark thirty years of finished work as under review.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

# Patterns an agency writes into the entry itself. Each is optional: a page that
# stops carrying one is reported through the field coverage in run metadata rather
# than by silently producing thinner records.
_SCH_NUMBER = re.compile(r"SCH\s*#?\s*:?\s*(\d{7,12})", re.IGNORECASE)
_CASE_NUMBER = re.compile(r"\(([A-Z]{1,4}-\d{2}-\d{2,4})\)")
_COMMENT_DEADLINE = re.compile(
    r"(?:public\s+)?comment(?:\s+period)?\s+deadline\s*:?\s*([0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_STREET_ADDRESS = re.compile(
    r"\b\d{2,6}(?:\s*[-–]\s*\d{2,6})?\s+[A-Z][A-Za-z0-9.'-]*(?:\s+[A-Z][A-Za-z0-9.'-]*){0,4}\s+"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Lane|Ln|Way|Boulevard|Blvd|Court|Ct|Place|Pl|Highway|Hwy)\b",
)


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def _parse_short_date(value: str) -> datetime | None:
    for shape in ("%m-%d-%Y", "%m/%d/%Y", "%m-%d-%y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, shape).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class HeadingProjectListAdapter(CollectorAdapter):
    """Collect a project list an agency publishes as headings on one page."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        options = config.options
        self.page_url = str(options.get("page_url") or config.base_url)
        parsed = urlparse(self.page_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("heading_project_list page_url must be an absolute https URL")
        self._allowed_host = parsed.hostname
        # Which tags count as a project heading and which as a section label is a
        # per-site fact, not a property of the shape, so both are config. Dixon and
        # Solano both happen to use h3/h2; a city that uses h4 needs no code change.
        self.project_heading_tags = [
            str(tag).lower() for tag in (options.get("project_heading_tags") or ["h3"])
        ]
        self.section_heading_tags = [
            str(tag).lower() for tag in (options.get("section_heading_tags") or ["h2"])
        ]
        # A page does not always reserve its section tag for sections. Dixon marks one
        # project up as an h2, and without this it becomes a section heading that
        # swallows every project after it - 19 real projects filed under a 20th. So a
        # heading in the section tags only counts as a section when it matches one of
        # these, and anything else in those tags is read as a project. Which labels are
        # sections is a fact about the page, so it lives in config.
        self.section_heading_patterns = [
            re.compile(str(pattern), re.IGNORECASE)
            for pattern in (options.get("section_heading_patterns") or [])
        ]
        self.content_root_selector = options.get("content_root_selector")
        self.min_expected_projects = int(options.get("min_expected_projects", 1))
        self.canary_title_contains = str(options.get("canary_title_contains") or "")
        self.exclude_title_patterns = [
            re.compile(str(pattern), re.IGNORECASE)
            for pattern in (options.get("exclude_title_patterns") or [])
        ]
        self.document_link_hosts = [
            str(host).lower() for host in (options.get("document_link_hosts") or [])
        ]
        self.timeout_seconds = float(options.get("timeout_seconds", 45))

    # ------------------------------------------------------------------ transport

    async def _fetch(self) -> str:
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": str(
                self.config.options.get("user_agent")
                or "Mozilla/5.0 (compatible; NS-Trackstar/0.1;"
                " +https://github.com/jonnyearlmedia/NS-trackstar)"
            ),
        }
        if self._client is not None:
            response = await self._client.get(self.page_url, headers=headers)
        else:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, follow_redirects=True
            ) as client:
                response = await client.get(self.page_url, headers=headers)
        if response.status_code in {401, 403}:
            raise SourceBlockedError(
                f"{self._allowed_host} refused the request with HTTP {response.status_code}"
            )
        response.raise_for_status()
        return response.text

    # ------------------------------------------------------------------ parsing

    def _root(self, soup: BeautifulSoup) -> Tag:
        if self.content_root_selector:
            found = soup.select_one(str(self.content_root_selector))
            if found is not None:
                return found
        return soup.body or soup

    def _is_section_label(self, text: str) -> bool:
        if not self.section_heading_patterns:
            return True
        return any(pattern.search(text) for pattern in self.section_heading_patterns)

    def _entries(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        root = self._root(soup)

        entries: list[dict[str, Any]] = []
        section = ""
        current: dict[str, Any] | None = None
        seen_headings: set[int] = set()

        for node in root.descendants:
            if isinstance(node, Tag):
                name = node.name.lower()
                if name in self.section_heading_tags:
                    text = _clean(node.get_text(" ", strip=True))
                    if not text:
                        continue
                    if self._is_section_label(text):
                        section = text
                        current = None
                        continue
                    # Marked up as a section, written as a project. Treat it as one.
                    seen_headings.add(id(node))
                    current = {
                        "title": text,
                        "section": section,
                        "text": [],
                        "documents": [],
                        "heading_tag": name,
                    }
                    entries.append(current)
                    continue
                if name in self.project_heading_tags:
                    text = _clean(node.get_text(" ", strip=True))
                    if not text:
                        continue
                    seen_headings.add(id(node))
                    current = {
                        "title": text,
                        "section": section,
                        "text": [],
                        "documents": [],
                        "heading_tag": name,
                    }
                    entries.append(current)
                    continue
                if current is not None and name == "a":
                    href = node.get("href") or ""
                    label = _clean(node.get_text(" ", strip=True))
                    if href and not href.lower().startswith("mailto:"):
                        current["documents"].append(
                            {"title": label or None, "url": urljoin(self.page_url, href)}
                        )
                continue

            if isinstance(node, NavigableString) and current is not None:
                # Skip text that belongs to a heading we already consumed, so a title
                # is not repeated into its own body.
                parent = node.parent
                if isinstance(parent, Tag) and id(parent) in seen_headings:
                    continue
                text = _clean(str(node))
                if text:
                    current["text"].append(text)

        return entries

    def _record(self, entry: dict[str, Any]) -> NormalizedRecord | None:
        title = entry["title"]
        if any(pattern.search(title) for pattern in self.exclude_title_patterns):
            return None
        body = _clean(" ".join(entry["text"]))
        combined = f"{title} {body}"

        documents = []
        seen_urls: set[str] = set()
        for document in entry["documents"]:
            url = document["url"]
            if url in seen_urls:
                continue
            if self.document_link_hosts:
                host = (urlparse(url).hostname or "").lower()
                if not any(host.endswith(allowed) for allowed in self.document_link_hosts):
                    continue
            seen_urls.add(url)
            documents.append(document)

        sch = _SCH_NUMBER.search(combined)
        case = _CASE_NUMBER.search(title)
        deadline = _COMMENT_DEADLINE.search(combined)
        email = _EMAIL.search(body)
        address = _STREET_ADDRESS.search(body)
        deadline_at = _parse_short_date(deadline.group(1)) if deadline else None

        normalized = {
            "record_kind": "environmental_review_project",
            "title": title,
            # The section is what the agency filed this under. It is a hint about
            # where to look, never a claim about the project's state: Dixon files
            # thirty years of finished reviews under one "under review" heading.
            "index_section": entry["section"] or None,
            "description": body or None,
            "sch_number": sch.group(1) if sch else None,
            "case_number": case.group(1) if case else None,
            "public_comment_deadline": deadline_at.date().isoformat() if deadline_at else None,
            "contact_email": email.group(0) if email else None,
            "address": _clean(address.group(0)) if address else None,
            "documents": documents or None,
            "document_count": len(documents) or None,
        }
        normalized = {key: value for key, value in normalized.items() if value not in (None, "", [])}

        identity = sch.group(1) if sch else (case.group(1) if case else title)
        external_id = hashlib.sha256(identity.encode()).hexdigest()[:24]

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=external_id,
            canonical_url=self.page_url,
            source_created_at=None,
            source_updated_at=deadline_at,
            raw_payload={
                "title": title,
                "section": entry["section"],
                "body": body,
                "documents": entry["documents"],
            },
            normalized_payload=normalized,
        )

    # ------------------------------------------------------------------ contract

    async def canary(self) -> bool:
        html = await self._fetch()
        entries = self._entries(html)
        if len(entries) < self.min_expected_projects:
            return False
        if self.canary_title_contains:
            needle = self.canary_title_contains.casefold()
            return any(needle in entry["title"].casefold() for entry in entries)
        return True

    async def collect(self) -> CollectorResult:
        html = await self._fetch()
        entries = self._entries(html)
        records: list[NormalizedRecord] = []
        excluded = 0
        for entry in entries:
            record = self._record(entry)
            if record is None:
                excluded += 1
                continue
            records.append(record)

        # A page that quietly stops carrying its clearinghouse numbers or its comment
        # deadlines still parses, so field coverage is reported rather than left to be
        # noticed by a resident.
        coverage = {
            field: sum(1 for record in records if field in record.normalized_payload)
            for field in ("sch_number", "case_number", "public_comment_deadline", "address")
        }
        sections: dict[str, int] = {}
        for record in records:
            label = str(record.normalized_payload.get("index_section") or "unfiled")
            sections[label] = sections.get(label, 0) + 1

        keys: set[str] = set()
        for record in records:
            keys.update(record.normalized_payload.keys())

        return CollectorResult(
            records=records,
            schema_fingerprint=hashlib.sha256(
                json.dumps(sorted(keys), separators=(",", ":")).encode()
            ).hexdigest(),
            parser_yield=len(records) / len(entries) if entries else 1.0,
            metadata={
                "page_url": self.page_url,
                "headings_seen": len(entries),
                "excluded_by_pattern": excluded,
                "field_coverage": coverage,
                "index_sections": sections,
                "headings_promoted_from_section_tag": sum(
                    1
                    for entry in entries
                    if entry.get("heading_tag") in self.section_heading_tags
                ),
            },
        )
