from urllib.parse import parse_qs

import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.etrakit import ETrakitAdapter

_SEARCH_HTML = """
<html><body><form method="post">
<input type="hidden" name="__VIEWSTATE" value="state-one" />
<input type="hidden" name="__EVENTVALIDATION" value="validation-one" />
<select id="ctl00_cplMain_ddSearchBy" name="ctl00$cplMain$ddSearchBy">
  <option value="Permit_Main.PERMIT_NO">Permit #</option>
  <option value="Permit_Main.SITE_ADDR">Address</option>
</select>
<select id="ctl00_cplMain_ddSearchOper" name="ctl00$cplMain$ddSearchOper">
  <option value="BEGINS WITH">Begins With</option>
  <option value="CONTAINS">Contains</option>
</select>
<input id="ctl00_cplMain_txtSearchString" name="ctl00$cplMain$txtSearchString" />
<input type="submit" id="ctl00_cplMain_btnSearch" name="ctl00$cplMain$btnSearch" value="Search" />
</form></body></html>
"""

_RESULT_HTML = """
<html><body><form method="post">
<input type="hidden" name="__VIEWSTATE" value="state-two" />
<a href="permit.aspx?activityNo=BP26-0042">BP26-0042</a>
</form></body></html>
"""

_DETAIL_HTML = """
<html><body>
<span id="ctl00_cplMain_lblPermitType">COMMERCIAL TENANT IMPROVEMENT</span>
<span id="ctl00_cplMain_lblPermitSubtype">RESTAURANT</span>
<span id="ctl00_cplMain_lblPermitDesc">Interior tenant improvement</span>
<span id="ctl00_cplMain_lblPermitStatus">ISSUED</span>
<span id="ctl00_cplMain_lblPermitAppliedDate">09/01/2026</span>
<span id="ctl00_cplMain_lblPermitApprovedDate">09/05/2026</span>
<span id="ctl00_cplMain_lblPermitIssuedDate">09/06/2026</span>
<a id="ctl00_cplMain_hlSiteAddress">500 Main St Ste 12</a>
<a href="parcel.aspx?activityNo=123-456-789">123-456-789</a>
<span id="ctl00_cplMain_lblSiteCityStateZip">Vallejo, CA 94590</span>
<table id="ctl00_cplMain_rgInspectionInfo">
<tr><th>Date</th><th>Result</th></tr><tr><td>09/10/2026</td><td>Passed</td></tr>
</table>
</body></html>
"""


@pytest.fixture
def config() -> SourceConfig:
    return SourceConfig(
        key="vallejo.etrakit",
        name="Vallejo eTRAKiT",
        jurisdiction="City of Vallejo",
        base_url="https://example.test/eTRAKiT",
        poll_minutes=240,
        options={
            "base_url": "https://example.test/eTRAKiT",
            "canary_kinds": ["permit"],
            "min_request_interval_seconds": 0,
            "searches": [
                {
                    "kind": "permit",
                    "search_by_value": "Permit_Main.PERMIT_NO",
                    "operator_value": "BEGINS WITH",
                    "value": "BP26-",
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_search_preserves_webforms_state_and_fetches_detail(config: SourceConfig) -> None:
    posted: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("activityNo") == "BP26-0042":
            return httpx.Response(200, text=_DETAIL_HTML)
        if request.method == "GET" and request.url.path.endswith("/Search/permit.aspx"):
            return httpx.Response(200, text=_SEARCH_HTML)
        if request.method == "POST" and request.url.path.endswith("/Search/permit.aspx"):
            posted.update(parse_qs(request.content.decode()))
            return httpx.Response(200, text=_RESULT_HTML)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ETrakitAdapter(config, client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert posted["__VIEWSTATE"] == ["state-one"]
    assert posted["__EVENTTARGET"] == ["ctl00$cplMain$btnSearch"]
    assert posted["ctl00$cplMain$ddSearchBy"] == ["Permit_Main.PERMIT_NO"]
    assert posted["ctl00$cplMain$ddSearchOper"] == ["BEGINS WITH"]
    assert posted["ctl00$cplMain$txtSearchString"] == ["BP26-"]
    assert len(result.records) == 1
    record = result.records[0]
    assert record.external_id == "permit:BP26-0042"
    assert record.normalized_payload["status"] == "ISSUED"
    assert record.normalized_payload["address"] == "500 Main St Ste 12"
    assert record.normalized_payload["apn"] == "123-456-789"
    assert record.normalized_payload["detail_grids"]["ctl00_cplMain_rgInspectionInfo"][1] == [
        "09/10/2026",
        "Passed",
    ]


@pytest.mark.asyncio
async def test_explicit_project_record_does_not_require_search(config: SourceConfig) -> None:
    project_html = """
    <span id="ctl00_cplMain_lblProjectType">PLANNING APPLICATION</span>
    <span id="ctl00_cplMain_lblProjectName">Kaiser Road Warehouse</span>
    <span id="ctl00_cplMain_lblProjectStatus">APPROVED</span>
    <span id="ctl00_cplMain_lblProjectAppliedDate">01/05/2023</span>
    <a id="ctl00_cplMain_hlSiteAddress">1030 Kaiser Rd</a>
    """

    explicit_config = SourceConfig(
        key="napa.etrakit",
        name="Napa eTRAKiT",
        jurisdiction="City of Napa",
        base_url="https://example.test/etrakit",
        poll_minutes=240,
        options={
            "base_url": "https://example.test/etrakit",
            "canary_kinds": ["project"],
            "explicit_records": [{"kind": "project", "id": "PL23-0135"}],
            "min_request_interval_seconds": 0,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("activityNo") == "PL23-0135":
            return httpx.Response(200, text=project_html)
        if request.url.path.endswith("/Search/project.aspx"):
            search_html = _SEARCH_HTML.replace("Permit_Main.PERMIT_NO", "Project_Main.PROJECT_NO")
            return httpx.Response(200, text=search_html)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ETrakitAdapter(explicit_config, client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert len(result.records) == 1
    assert result.records[0].external_id == "project:PL23-0135"
    assert result.records[0].normalized_payload["name"] == "Kaiser Road Warehouse"
