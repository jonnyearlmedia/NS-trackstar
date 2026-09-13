from __future__ import annotations

import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.opencities_project_list import (
    OpenCitiesProjectListAdapter,
    parse_detail_page,
    parse_latlong,
    parse_list_page,
)

LIST_PAGE = """<html><body><div class="content-main-container">
 <div class="oc-quick-list">
  <div class="list-item-container"><article>
    <a href="https://city.example.gov/Projects/515-Foothill">
      <h2 class="list-item-title">515 Foothill Blvd - Calistoga Hills Resort</h2>
      <p class="oc-thumbnail-image"><img src="/x.jpg"/></p>
      <p>88-acre resort with 110 guestrooms.</p>
    </a>
  </article></div>
  <div class="list-item-container"><article>
    <a href="/Projects/2008-Grant">
      <h2 class="list-item-title">2008 Grant St - Residential Subdivision</h2>
      <p>6-acre residential subdivision consisting of 15 lots.</p>
    </a>
  </article></div>
  <div class="list-item-container"><article>
    <a href="https://elsewhere.example.com/Projects/offsite">
      <h2 class="list-item-title">Offsite</h2></a>
  </article></div>
 </div>
</div></body></html>"""

DETAIL_WITH_POINT = """<html><body><div class="content-main-container">
 <div class="col-m-8">
  <h1 class="oc-page-title">515 Foothill Blvd - Calistoga Hills Resort</h1>
  <ul class="content-details-list">
    <li><span class="field-label">Project type</span><span class="field-value">Visitor Accommodations</span></li>
    <li><span class="field-label">Contractor name</span><span class="field-value">CTF Development</span></li>
  </ul>
  <p>The proposed resort includes a check-in structure and a spa building.</p>
  <p>It also includes 20 private villas.</p>
  <div class="oc-wysiwyg-container-panel"><h2>TRAFFIC DISRUPTIONS</h2>
    <div class="oc-wysiwyg-container-panel-content"><p>No traffic disruptions at this time.</p></div>
  </div>
 </div>
 <div class="gmap-marker">
   <div class="gmap-latlong">38.57325900000001,-122.574393</div>
   <div class="gmap-address">515 Foothill Blvd , Calistoga, CA 94515</div>
 </div>
</div></body></html>"""

DETAIL_WITHOUT_POINT = """<html><body><div class="content-main-container">
 <div class="col-m-8">
  <h1 class="oc-page-title">2008 Grant St - Residential Subdivision</h1>
  <p>Fifteen lots on six acres.</p>
 </div>
 <div class="gmap-marker"><div class="gmap-latlong">0,0</div></div>
</div></body></html>"""

PAGES = {
    "https://city.example.gov/Projects/Active": LIST_PAGE,
    "https://city.example.gov/Projects/515-Foothill": DETAIL_WITH_POINT,
    "https://city.example.gov/Projects/2008-Grant": DETAIL_WITHOUT_POINT,
}


def build(*, status: int = 200, list_body: str = LIST_PAGE, **options):
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="blocked")
        url = str(request.url)
        body = list_body if url.endswith("/Projects/Active") else PAGES.get(url)
        if body is None:
            return httpx.Response(404, text="missing")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenCitiesProjectListAdapter(
        SourceConfig(
            key="city.active-construction-projects",
            name="Example Active Construction",
            jurisdiction="City of Example",
            base_url="https://city.example.gov/Projects/Active",
            poll_minutes=240,
            options={
                "site_url": "https://city.example.gov",
                "min_request_interval_seconds": 0,
                "min_expected_projects": 1,
                "lists": [
                    {
                        "url": "/Projects/Active",
                        "label": "Active Construction Projects",
                        "lifecycle_stage": "under_construction",
                    }
                ],
                **options,
            },
        ),
        client=client,
    )


def test_an_unusable_marker_never_becomes_a_coordinate():
    assert parse_latlong("38.5732,-122.5743") == (38.5732, -122.5743)
    # 0,0 is an unset marker, not a project in the Gulf of Guinea.
    assert parse_latlong("0,0") is None
    assert parse_latlong("200,-400") is None
    assert parse_latlong("") is None


def test_the_list_widget_yields_projects_and_ignores_offsite_links():
    entries = parse_list_page(LIST_PAGE, base_url="https://city.example.gov/Projects/Active")

    assert [entry["title"] for entry in entries] == [
        "515 Foothill Blvd - Calistoga Hills Resort",
        "2008 Grant St - Residential Subdivision",
    ]
    # A thumbnail paragraph is not a summary.
    assert entries[0]["summary"] == "88-acre resort with 110 guestrooms."


def test_a_detail_page_yields_its_labelled_fields_and_named_panels():
    detail = parse_detail_page(DETAIL_WITH_POINT)

    assert detail["project_type"] == "Visitor Accommodations"
    assert detail["contractor_name"] == "CTF Development"
    assert detail["panels"]["traffic_disruptions"] == "No traffic disruptions at this time."
    assert detail["address"] == "515 Foothill Blvd, Calistoga, CA 94515"
    assert detail["latitude"] == 38.57325900000001
    # The page's own prose, not the one-line list summary.
    assert "20 private villas" in detail["description"]


@pytest.mark.asyncio
async def test_identity_is_the_city_s_own_slug_so_a_retitle_does_not_fork_a_project():
    result = await build().collect()

    assert [record.external_id for record in result.records] == ["515-Foothill", "2008-Grant"]
    assert result.parser_yield == 1.0


@pytest.mark.asyncio
async def test_a_published_marker_becomes_an_address_level_point_attributed_to_its_page():
    result = await build().collect()
    resort = next(r for r in result.records if r.external_id == "515-Foothill")
    subdivision = next(r for r in result.records if r.external_id == "2008-Grant")

    assert resort.geometry_geojson == {
        "type": "Point",
        "coordinates": [-122.574393, 38.57325900000001],
    }
    assert resort.location_accuracy is not None
    assert resort.geometry_source == "https://city.example.gov/Projects/515-Foothill"
    # An unset marker leaves the project without a location rather than at 0,0.
    assert subdivision.geometry_geojson is None
    assert subdivision.location_accuracy is None
    assert result.metadata["projects_with_published_coordinates"] == 1


@pytest.mark.asyncio
async def test_a_template_change_that_empties_the_list_fails_the_canary():
    empty = '<html><body><div class="content-main-container"></div></body></html>'
    assert await build(list_body=empty).canary() is False
    assert await build().canary() is True


@pytest.mark.asyncio
async def test_a_blocked_site_is_reported_as_blocked_not_as_an_empty_run():
    with pytest.raises(SourceBlockedError):
        await build(status=403).collect()
    assert await build(status=403).canary() is False
