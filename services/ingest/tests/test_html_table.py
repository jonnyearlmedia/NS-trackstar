import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.html_table import HtmlTableAdapter, parse_html_table

HTML = """
<table>
  <tr><th>FILE NO</th><th>PROJECT NAME</th><th>PROJECT LOCATION</th><th>PROJECT TYPE</th></tr>
  <tr><td>Explanation</td><td>Project Name</td><td>Address</td><td>Type</td></tr>
  <tr><td><a href="/records/DR2022-005">DR2022-005</a></td><td>Raising Cane's</td>
      <td>1420 Travis Blvd. (APN: 0033-240-030)</td><td>Commercial, Drive-Through</td></tr>
</table>
"""


def test_parses_semantic_project_table_without_inventing_geometry() -> None:
    records, headers = parse_html_table(
        HTML,
        source_key="fairfield.development-activity",
        source_url="https://example.test/projects",
        table_selector="table",
        columns=["planning_case", "name", "location_description", "source_project_type"],
        skip_rows=2,
        id_field="planning_case",
    )

    assert headers == ["FILE NO", "PROJECT NAME", "PROJECT LOCATION", "PROJECT TYPE"]
    assert records[0].external_id == "DR2022-005"
    assert records[0].canonical_url == "https://example.test/records/DR2022-005"
    assert records[0].geometry_geojson is None
    assert records[0].normalized_payload["name"] == "Raising Cane's"


@pytest.mark.asyncio
async def test_canary_and_collect_require_expected_table_contract() -> None:
    config = SourceConfig(
        key="fairfield.development-activity",
        name="Fairfield Development Activity",
        jurisdiction="City of Fairfield",
        base_url="https://example.test/projects",
        poll_minutes=1440,
        options={
            "columns": [
                "planning_case",
                "name",
                "location_description",
                "source_project_type",
            ],
            "skip_rows": 2,
            "id_field": "planning_case",
            "expected_project_count": 1,
            "canary_markers": ["FILE NO", "PROJECT LOCATION"],
        },
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = HtmlTableAdapter(config, client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert len(result.records) == 1
    assert result.parser_yield == 1.0


@pytest.mark.asyncio
async def test_browser_fetch_mode_uses_browser_session(monkeypatch: pytest.MonkeyPatch) -> None:
    config = SourceConfig(
        key="fairfield.development-activity",
        name="Fairfield Development Activity",
        jurisdiction="City of Fairfield",
        base_url="https://example.test/projects",
        poll_minutes=1440,
        options={
            "fetch_mode": "browser_session",
            "columns": [
                "planning_case",
                "name",
                "location_description",
                "source_project_type",
            ],
            "skip_rows": 2,
            "id_field": "planning_case",
            "expected_project_count": 1,
            "canary_markers": ["FILE NO"],
        },
    )
    adapter = HtmlTableAdapter(config)

    async def browser_download() -> tuple[str, dict[str, str]]:
        return HTML, {"x-ns-trackstar-fetch-mode": "browser_session"}

    monkeypatch.setattr(adapter, "_download_browser", browser_download)

    assert await adapter.canary() is True
    result = await adapter.collect()
    assert len(result.records) == 1
