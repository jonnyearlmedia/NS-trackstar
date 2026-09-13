from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord


def parse_html_table(
    html: str,
    *,
    source_key: str,
    source_url: str,
    table_selector: str,
    columns: list[str],
    skip_rows: int,
    id_field: str,
) -> tuple[list[NormalizedRecord], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(table_selector)
    if table is None:
        raise RuntimeError(f"HTML project table was not found: {table_selector}")
    rows = table.select("tr")
    headers = [" ".join(cell.get_text(" ", strip=True).split()) for cell in rows[0].select("th,td")]
    records: list[NormalizedRecord] = []
    for row in rows[skip_rows:]:
        cells = row.select("th,td")
        if len(cells) != len(columns):
            continue
        normalized: dict[str, Any] = {"record_kind": "curated_project"}
        for field, cell in zip(columns, cells, strict=True):
            normalized[field] = " ".join(cell.get_text(" ", strip=True).split())
        external_id = normalized.get(id_field)
        name = normalized.get("name")
        if not external_id or not name:
            continue
        link = cells[columns.index(id_field)].select_one("a[href]")
        canonical_url = urljoin(source_url, str(link["href"])) if link else source_url
        records.append(
            NormalizedRecord(
                source_key=source_key,
                external_id=str(external_id),
                canonical_url=canonical_url,
                raw_payload={"row_html": str(row)},
                normalized_payload=normalized,
            )
        )
    return records, headers


class HtmlTableAdapter(CollectorAdapter):
    """Collect a municipal project inventory published as a semantic HTML table."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.table_selector = str(config.options.get("table_selector", "table"))
        self.columns = [str(value) for value in config.options["columns"]]
        self.skip_rows = int(config.options.get("skip_rows", 1))
        self.id_field = str(config.options["id_field"])
        self.expected_project_count = int(config.options.get("expected_project_count", 1))
        self.canary_markers = [str(value) for value in config.options.get("canary_markers", [])]
        self.fetch_mode = str(config.options.get("fetch_mode", "http"))
        self.browser_channel = str(config.options.get("browser_channel", "chrome"))
        self.browser_timeout_ms = int(config.options.get("browser_timeout_ms", 30_000))
        artifact_directory = config.options.get("browser_artifact_directory")
        self.browser_artifact_directory = Path(str(artifact_directory)) if artifact_directory else None
        self._client = client
        self._cached_download: tuple[str, dict[str, str]] | None = None

    async def _download_browser(self) -> tuple[str, dict[str, str]]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - depends on optional runtime extra
            raise RuntimeError(
                "HTML table browser-session fetch requires the ingest 'browser' extra"
            ) from exc

        failures: list[str] = []
        last_html = ""
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel=self.browser_channel, headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                # Four bounded attempts implement the source recovery policy: the original
                # action, an action retry, a fresh context, then a browser restart.
                for attempt in range(4):
                    if attempt == 2:
                        await context.close()
                        context = await browser.new_context()
                        page = await context.new_page()
                    elif attempt == 3:
                        await context.close()
                        await browser.close()
                        browser = await playwright.chromium.launch(
                            channel=self.browser_channel, headless=True
                        )
                        context = await browser.new_context()
                        page = await context.new_page()
                    try:
                        response = await page.goto(
                            self.config.base_url,
                            wait_until="domcontentloaded",
                            timeout=self.browser_timeout_ms,
                        )
                        if response is not None and response.status in {401, 403, 404}:
                            raise SourceBlockedError(
                                "HTML project table browser request is explicitly blocked: "
                                f"status={response.status} url={page.url}"
                            )
                        await page.wait_for_selector(
                            self.table_selector,
                            timeout=self.browser_timeout_ms,
                        )
                        last_html = await page.content()
                        if response is not None and response.status >= 400:
                            raise RuntimeError(f"browser response status {response.status}")
                        return last_html, {
                            "x-ns-trackstar-fetch-mode": "browser_session",
                            "x-ns-trackstar-final-url": page.url,
                        }
                    except SourceBlockedError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - browser errors vary by engine
                        failures.append(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}")

                if self.browser_artifact_directory is not None:
                    self.browser_artifact_directory.mkdir(parents=True, exist_ok=True)
                    html_path = self.browser_artifact_directory / f"{self.config.key}.failure.html"
                    screenshot_path = (
                        self.browser_artifact_directory / f"{self.config.key}.failure.png"
                    )
                    html_path.write_text(last_html or await page.content(), encoding="utf-8")
                    with suppress(Exception):
                        await page.screenshot(path=str(screenshot_path), full_page=True)
                raise RuntimeError(
                    "HTML project table browser recovery exhausted: " + "; ".join(failures)
                )
            finally:
                with suppress(Exception):
                    await context.close()
                with suppress(Exception):
                    await browser.close()

    async def _download(self) -> tuple[str, dict[str, str]]:
        if self._cached_download is not None:
            return self._cached_download
        if self.fetch_mode == "browser_session":
            self._cached_download = await self._download_browser()
            return self._cached_download
        if self.fetch_mode != "http":
            raise ValueError(f"Unsupported HTML table fetch mode: {self.fetch_mode}")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            response = await client.get(self.config.base_url, headers={"Accept": "text/html"})
            response.raise_for_status()
            self._cached_download = (response.text, dict(response.headers))
            return self._cached_download
        finally:
            if owns_client:
                await client.aclose()

    async def canary(self) -> bool:
        html, _ = await self._download()
        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one(self.table_selector)
        if table is None:
            return False
        text = " ".join(table.get_text(" ", strip=True).split())
        return all(marker.casefold() in text.casefold() for marker in self.canary_markers)

    async def collect(self) -> CollectorResult:
        html, headers = await self._download()
        records, table_headers = parse_html_table(
            html,
            source_key=self.config.key,
            source_url=self.config.base_url,
            table_selector=self.table_selector,
            columns=self.columns,
            skip_rows=self.skip_rows,
            id_field=self.id_field,
        )
        if len(records) < self.expected_project_count:
            raise RuntimeError(
                "HTML project table parser yield fell below expected project count: "
                f"{len(records)} < {self.expected_project_count}"
            )
        source_updated_at: datetime | None = None
        if headers.get("last-modified"):
            try:
                source_updated_at = parsedate_to_datetime(headers["last-modified"])
            except (TypeError, ValueError):
                pass
        for record in records:
            record.source_updated_at = source_updated_at
        schema = {"headers": table_headers, "columns": self.columns}
        return CollectorResult(
            records=records,
            schema_fingerprint=hashlib.sha256(
                json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            parser_yield=1.0,
            metadata={"table_headers": table_headers, "projects_parsed": len(records)},
        )
