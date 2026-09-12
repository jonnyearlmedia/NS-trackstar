from urllib.parse import parse_qs

import httpx
import pytest

from ns_trackstar.adapters.accela_aca import AccelaAcaAdapter
from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig

_SEARCH_HTML = """
<html><body><form id="aspnetForm" method="post">
<input type="hidden" name="__VIEWSTATE" value="state-one" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="generator-one" />
<input type="hidden" name="ACA_CS_FIELD" value="csrf-one" />
<select id="ctl00_PlaceHolderMain_ddlSearchType"
        name="ctl00$PlaceHolderMain$ddlSearchType">
  <option value="General Search" selected>General Search</option>
</select>
<input id="ctl00_PlaceHolderMain_generalSearchForm_txtGSPermitNumber"
       name="ctl00$PlaceHolderMain$generalSearchForm$txtGSPermitNumber" />
<input id="ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate"
       name="ctl00$PlaceHolderMain$generalSearchForm$txtGSStartDate" />
<input id="ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate"
       name="ctl00$PlaceHolderMain$generalSearchForm$txtGSEndDate" />
<a id="ctl00_PlaceHolderMain_btnNewSearch"
   href="javascript:__doPostBack('ctl00$PlaceHolderMain$btnNewSearch','')">Search</a>
</form></body></html>
"""

_PAGE_ONE = """
<html><body><form id="aspnetForm" method="post">
<input type="hidden" name="__VIEWSTATE" value="state-two" />
<input type="hidden" name="ACA_CS_FIELD" value="csrf-two" />
<table id="ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList">
<tr><th>Date</th><th>Record Number</th><th>Record Type</th><th>Address</th><th>Status</th></tr>
<tr>
<td>09/10/2026</td>
<td><a href="Cap/CapDetail.aspx?capID1=26ABC&amp;capID2=00000&amp;capID3=00001">BLD26-0001</a></td>
<td>Commercial Building</td><td>100 Main St</td><td>Issued</td>
</tr>
</table>
<a href="javascript:__doPostBack('ctl00$PlaceHolderMain$dgvPermitList$gdvPermitList$ctl23$ctl01','')">Next &gt;</a>
</form></body></html>
"""

_PAGE_TWO = """
<html><body><form id="aspnetForm" method="post">
<input type="hidden" name="__VIEWSTATE" value="state-three" />
<input type="hidden" name="ACA_CS_FIELD" value="csrf-three" />
<table id="ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList">
<tr><th>Date</th><th>Record Number</th><th>Record Type</th><th>Address</th><th>Status</th></tr>
<tr>
<td>09/11/2026</td>
<td><a href="Cap/CapDetail.aspx?capID1=26ABC&amp;capID2=00000&amp;capID3=00002">BLD26-0002</a></td>
<td>Tenant Improvement</td><td>200 Main St</td><td>In Review</td>
</tr>
</table>
</form></body></html>
"""

_DETAIL_HTML = """
<html><body>
<span id="ctl00_PlaceHolderMain_lblPermitNumber">BLD26-0001</span>
<span id="ctl00_PlaceHolderMain_lblPermitType">Commercial Building</span>
<span id="ctl00_PlaceHolderMain_lblRecordStatus">Issued</span>
<table id="ctl00_PlaceHolderMain_tbl_worklocation"><tr><td>100 Main St</td></tr></table>
<div>Parcel Number: 0123-456-789</div>
</body></html>
"""


def _config(**options: object) -> SourceConfig:
    base_options: dict[str, object] = {
        "base_url": "https://aca-prod.accela.test/SOLANOCO",
        "modules": ["Building"],
        "lookback_days": 14,
        "max_pages": 5,
        "fetch_details": True,
        "min_request_interval_seconds": 0,
    }
    base_options.update(options)
    return SourceConfig(
        key="solano.accela",
        name="Solano County Accela",
        jurisdiction="Solano County",
        base_url="https://aca-prod.accela.test/SOLANOCO",
        poll_minutes=240,
        options=base_options,
    )


@pytest.mark.asyncio
async def test_collect_preserves_webforms_state_and_paginates() -> None:
    posts: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Cap/CapDetail.aspx"):
            record = request.url.params.get("capID3")
            detail = _DETAIL_HTML.replace("BLD26-0001", f"BLD26-{record[-4:]}")
            return httpx.Response(200, text=detail)
        if request.method == "GET":
            return httpx.Response(200, text=_SEARCH_HTML)
        if request.method == "POST":
            posted = parse_qs(request.content.decode())
            posts.append(posted)
            target = posted.get("__EVENTTARGET", [""])[0]
            if "gdvPermitList" in target:
                return httpx.Response(200, text=_PAGE_TWO)
            return httpx.Response(200, text=_PAGE_ONE)
        return httpx.Response(405)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AccelaAcaAdapter(_config(), client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert len(result.records) == 2
    assert result.metadata["modules"] == {"Building": 2}
    first = result.records[0]
    assert first.external_id == "Building:BLD26-0001"
    assert first.normalized_payload["status"] == "Issued"
    assert first.normalized_payload["parcel_number"] == "0123-456-789"
    assert first.normalized_payload["cap_id_parts"] == ["26ABC", "00000", "00001"]

    search_post = posts[0]
    assert search_post["__VIEWSTATE"] == ["state-one"]
    assert search_post["ACA_CS_FIELD"] == ["csrf-one"]
    assert search_post["__EVENTTARGET"] == ["ctl00$PlaceHolderMain$btnNewSearch"]
    assert search_post["ctl00$PlaceHolderMain$generalSearchForm$txtGSStartDate"]
    assert search_post["ctl00$PlaceHolderMain$generalSearchForm$txtGSEndDate"]

    page_post = posts[1]
    assert page_post["__VIEWSTATE"] == ["state-two"]
    assert page_post["ACA_CS_FIELD"] == ["csrf-two"]
    assert "gdvPermitList" in page_post["__EVENTTARGET"][0]


@pytest.mark.asyncio
async def test_canary_can_require_known_record() -> None:
    result_html = _PAGE_ONE.replace("BLD26-0001", "KNOWN-123")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=_SEARCH_HTML)
        if request.method == "POST":
            posted = parse_qs(request.content.decode())
            assert posted[
                "ctl00$PlaceHolderMain$generalSearchForm$txtGSPermitNumber"
            ] == ["KNOWN-123"]
            return httpx.Response(200, text=result_html)
        return httpx.Response(405)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AccelaAcaAdapter(
            _config(canary_records={"Building": "KNOWN-123"}, fetch_details=False),
            client=client,
        )
        assert await adapter.canary() is True


@pytest.mark.asyncio
async def test_access_restriction_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, text="forbidden")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AccelaAcaAdapter(_config(), client=client)
        with pytest.raises(SourceBlockedError, match="HTTP 403"):
            await adapter.canary()

    assert calls == 1
