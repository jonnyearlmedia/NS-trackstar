from __future__ import annotations

import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.civicplus_project_index import (
    CivicPlusProjectIndexAdapter,
    child_page_links,
    page_id_of,
    parse_field_block,
    street_address,
)


def page(headline: str, body: str) -> str:
    """A CivicPlus page: a headline, the page body, then the reused site chrome.

    The trailing chrome block matters. CivicPlus gives the global quick-links and
    footer the same `pageContent` class as the page body, and an earlier crawl walked
    the whole site because of it.
    """

    return f"""<html><body>
      <h1 id="versionHeadLine" class="headline">{headline}</h1>
      <div class="pageContent cpGrid cpGrid24">{body}</div>
      <div class="pageContent">
        <a href="/194/Library">Library</a>
        <a href="/204/Parks-Recreation">Parks &amp; Recreation</a>
      </div>
    </body></html>"""


INDEX = page(
    "Active Projects",
    """<div class="fr-view">
         <a href="/756/PL24-045-Castellucci">Link to page</a>
         <a href="/790/SB-330-Applications">Link to page</a>
       </div>""",
)

SUB_INDEX = page(
    "SB 330 Applications",
    '<div class="fr-view"><a href="/910/PL25-034-Spring-Vineyard">Link to page</a></div>',
)

PROJECT = page(
    "(PL25-034)&#160; 1933 Spring St.- Spring Vineyard Design Review",
    """<div class="fr-view">
         <h2 class="subhead1">Project ID</h2><p>PL25-034</p><p><br></p>
         <h2 class="subhead1">Project Type</h2><p>Design Review &amp; Density Bonus</p>
       </div>
       <div class="fr-view">
         <h2 class="subhead1">Project Status</h2><p>Approved</p>
         <h2 class="subhead1">Date Received</h2><p>Tuesday, August 26, 2025</p>
         <h2 class="subhead1">Other Meeting Date</h2><p>N/A</p>
       </div>
       <div class="fr-view">
         <h2 class="subhead1">Location</h2>
         <p>1933 Spring St.</p><p>St. Helena, CA 94574</p>
         <p><a href="https://www.google.com/maps/place/x/@38.49,-122.47,16z">See map</a></p>
       </div>""",
)

NAMED_LOCATION = page(
    "(PL17-006) 1000 Mills Lane - Farmstead",
    """<div class="fr-view">
         <h2 class="subhead1">Project ID</h2><p>PL17-006</p>
         <h2 class="subhead1">Project Status</h2><p>Approved</p>
         <h2 class="subhead1">Location</h2>
         <p>Farmstead at Long Meadow Ranch</p><p>1000 Mills Lane</p><p>St. Helena, CA 94574</p>
       </div>""",
)

PAGES = {
    "https://city.example.gov/506/Active-Projects": INDEX,
    "https://city.example.gov/790/SB-330-Applications": SUB_INDEX,
    "https://city.example.gov/756/PL24-045-Castellucci": NAMED_LOCATION,
    "https://city.example.gov/910/PL25-034-Spring-Vineyard": PROJECT,
}


def build(**options) -> CivicPlusProjectIndexAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        body = PAGES.get(str(request.url))
        if body is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CivicPlusProjectIndexAdapter(
        SourceConfig(
            key="city.planning-projects",
            name="Example Planning Projects",
            jurisdiction="City of Example",
            base_url="https://city.example.gov/506/Active-Projects",
            poll_minutes=240,
            options={
                "site_url": "https://city.example.gov",
                "min_request_interval_seconds": 0,
                "min_expected_projects": 1,
                "max_depth": 2,
                "indexes": [
                    {
                        "url": "/506/Active-Projects",
                        "label": "Active Projects",
                        "lifecycle_stage": "under_review",
                    }
                ],
                **options,
            },
        ),
        client=client,
    )


def test_page_identity_comes_from_the_numeric_page_id_not_the_slug():
    assert page_id_of("https://city.example.gov/910/PL25-034-Spring-Vineyard") == "910"
    assert page_id_of("https://city.example.gov/910/A-Retitled-Page") == "910"
    assert page_id_of("https://city.example.gov/Calendar.aspx?EID=1") is None


def test_a_field_block_keeps_its_lines_and_drops_placeholders():
    fields = parse_field_block(PROJECT)

    assert fields["project_id"] == ["PL25-034"]
    assert fields["project_type"] == ["Design Review & Density Bonus"]
    assert fields["location"] == ["1933 Spring St.", "St. Helena, CA 94574", "See map"]
    # "N/A" is the city saying there is no value, so it must not become one.
    assert "other_meeting_date" not in fields


def test_a_trade_name_above_the_street_line_is_not_treated_as_the_address():
    lines = ["Farmstead at Long Meadow Ranch", "1000 Mills Lane", "St. Helena, CA 94574"]
    assert street_address(lines) == "1000 Mills Lane"
    assert street_address(["Hunter Residential Subdivision"]) is None


def test_site_chrome_is_not_crawled():
    links = child_page_links(INDEX, base_url="https://city.example.gov/506/Active-Projects")

    assert links == [
        "https://city.example.gov/756/PL24-045-Castellucci",
        "https://city.example.gov/790/SB-330-Applications",
    ]
    assert not any(link.endswith("/194/Library") for link in links)


@pytest.mark.asyncio
async def test_projects_are_found_through_a_sub_index():
    result = await build().collect()

    assert {record.external_id for record in result.records} == {"756", "910"}
    assert result.parser_yield == 1.0
    assert result.metadata["project_pages"] == 2


@pytest.mark.asyncio
async def test_the_index_section_is_recorded_as_a_hint_not_as_the_status():
    result = await build().collect()
    spring = next(record for record in result.records if record.external_id == "910")

    assert spring.normalized_payload["planning_case"] == "PL25-034"
    assert spring.normalized_payload["project_status"] == "Approved"
    assert spring.normalized_payload["address"] == "1933 Spring St."
    assert spring.normalized_payload["index_label"] == "Active Projects"
    # The section a clerk filed the link under never becomes the project's status.
    assert spring.normalized_payload["index_lifecycle_hint"] == "under_review"
    assert "lifecycle_stage" not in spring.normalized_payload


@pytest.mark.asyncio
async def test_a_map_link_never_becomes_a_coordinate():
    result = await build().collect()

    for record in result.records:
        assert record.geometry_geojson is None
        assert record.location_accuracy is None


@pytest.mark.asyncio
async def test_the_canary_fails_when_the_index_stops_yielding_projects():
    adapter = build(min_expected_projects=3)
    assert await adapter.canary() is False
    assert await build().canary() is True
