from __future__ import annotations

import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.linked_project_pages import (
    LinkedProjectPagesAdapter,
    parse_detail,
    parse_index,
)

# The next group's heading is authored inside the last item of the previous group.
# That is not a contrived case; it is how the real page is written.
INDEX = """<html><body><div class="main">
  <h1>Capital Improvement Projects</h1>
  <h3>Active Projects</h3>
  <article class="summaryDisplay">
    <h2><a class="item" href="/index.asp?SEC=AAA&amp;DE=111">Lopes Road Reconstruction Project</a></h2>
    <div class="body"></div>
  </article>
  <article class="summaryDisplay">
    <h2><a class="item" href="/index.asp?SEC=AAA&amp;DE=222">2026 Citywide Curb Ramp Project</a></h2>
    <div class="body"><h3>Upcoming Projects</h3></div>
  </article>
  <article class="summaryDisplay">
    <h2><a class="item" href="/index.asp?SEC=AAA&amp;DE=333">2027 Pavement Project</a></h2>
  </article>
  <p><a href="https://elsewhere.example.com/x">Offsite</a></p>
</div></body></html>"""

# Section labels are bold runs inside paragraphs, not real headings.
DETAIL = """<html><body><div class="main">
  <h1>Lopes Road Reconstruction Project</h1>
  <p><strong>Scope</strong></p>
  <p>Reconstruct the roadway and replace the water pipeline beneath it.</p>
  <p><strong>Construction Cost</strong></p>
  <p>$5,283,795</p>
  <p><strong>Potential Resident Impact</strong></p>
  <p>Expect street closures and detours during the work.</p>
</div></body></html>"""

PLAIN_DETAIL = """<html><body><div class="main">
  <h1>2027 Pavement Project</h1>
  <p>Design is not yet under way.</p>
</div></body></html>"""

PAGES = {
    "https://city.example.gov/cip": INDEX,
    "https://city.example.gov/index.asp?SEC=AAA&DE=111": DETAIL,
    "https://city.example.gov/index.asp?SEC=AAA&DE=222": DETAIL,
    "https://city.example.gov/index.asp?SEC=AAA&DE=333": PLAIN_DETAIL,
}


def build(*, status: int = 200, index_body: str = INDEX, **options):
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="blocked")
        url = str(request.url)
        body = index_body if url.endswith("/cip") else PAGES.get(url)
        if body is None:
            return httpx.Response(404, text="missing")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LinkedProjectPagesAdapter(
        SourceConfig(
            key="city.capital-improvement-projects",
            name="Example CIP",
            jurisdiction="City of Example",
            base_url="https://city.example.gov/cip",
            poll_minutes=240,
            options={
                "index_url": "https://city.example.gov/cip",
                "content_selector": "div.main",
                "detail_content_selector": "div.main",
                "item_selector": "article.summaryDisplay h2 a.item",
                "id_query_param": "DE",
                "detail_section_tags": ["strong", "h2", "h3"],
                "min_request_interval_seconds": 0,
                "min_expected_projects": 1,
                "group_stages": {"active": "under_construction", "upcoming": "planned"},
                **options,
            },
        ),
        client=client,
    )


def test_a_heading_that_wraps_a_project_link_is_a_title_not_a_group():
    entries = parse_index(
        INDEX,
        base_url="https://city.example.gov/cip",
        content_selector="div.main",
        item_selector="article.summaryDisplay h2 a.item",
    )

    assert [e["title"] for e in entries] == [
        "Lopes Road Reconstruction Project",
        "2026 Citywide Curb Ramp Project",
        "2027 Pavement Project",
    ]
    # Read in document order, so the heading buried in the previous item still lands
    # on the project that follows it.
    assert [e["group"] for e in entries] == [
        "Active Projects",
        "Active Projects",
        "Upcoming Projects",
    ]
    assert all("elsewhere.example.com" not in e["url"] for e in entries)


def test_a_bold_run_is_read_as_a_section_label():
    detail = parse_detail(DETAIL, content_selector="div.main", section_tags=("strong",))

    assert detail["title"] == "Lopes Road Reconstruction Project"
    assert detail["sections"]["scope"].startswith("Reconstruct the roadway")
    assert detail["sections"]["construction_cost"] == "$5,283,795"
    assert detail["sections"]["potential_resident_impact"].startswith("Expect street closures")
    # The h1 is the project's name, never the first section's body.
    assert "Lopes Road" not in detail["sections"]["scope"]


def test_a_page_with_no_section_labels_still_yields_its_prose():
    detail = parse_detail(PLAIN_DETAIL, content_selector="div.main", section_tags=("strong",))

    assert "sections" not in detail
    assert detail["description"] == "Design is not yet under way."


@pytest.mark.asyncio
async def test_identity_is_the_city_s_own_record_id_not_the_url():
    result = await build().collect()

    assert [r.external_id for r in result.records] == ["111", "222", "333"]
    assert result.parser_yield == 1.0


@pytest.mark.asyncio
async def test_the_section_a_link_was_filed_under_is_a_hint_not_a_status():
    result = await build().collect()
    lopes = next(r for r in result.records if r.external_id == "111")

    assert lopes.normalized_payload["index_section"] == "Active Projects"
    assert lopes.normalized_payload["index_lifecycle_hint"] == "under_construction"
    # Named for what it is. Nothing here claims to be the project's own status.
    assert "official_status_text" not in lopes.normalized_payload


@pytest.mark.asyncio
async def test_configured_synonyms_fold_together_without_losing_the_page_s_label():
    result = await build(
        section_aliases={"cost_text": ["construction_cost", "cost"]}
    ).collect()
    lopes = next(r for r in result.records if r.external_id == "111")

    assert lopes.normalized_payload["cost_text"] == "$5,283,795"
    # The label the city actually wrote is still there.
    assert lopes.normalized_payload["construction_cost"] == "$5,283,795"


@pytest.mark.asyncio
async def test_a_template_change_that_empties_the_index_fails_the_canary():
    assert await build(index_body='<html><body><div class="main"></div></body></html>').canary() is False
    assert await build().canary() is True


@pytest.mark.asyncio
async def test_a_blocked_site_is_reported_as_blocked_not_as_an_empty_run():
    with pytest.raises(SourceBlockedError):
        await build(status=403).collect()
    assert await build(status=403).canary() is False


# A list written as bold group labels over plain <ul> items, with one entry the
# city deliberately points at a state programme page.
BOLD_INDEX = """<html><body><div class="main">
  <p><strong>Active Projects</strong></p>
  <ul>
    <li><a href="/media/wwtf.pdf">Waste Water Treatment Facility Expansion</a></li>
    <li><a href="https://dot.ca.gov/programs/hsip">HSIP Cycle 11 Pedestrian Improvements</a></li>
  </ul>
  <p><strong>Recently Completed</strong></p>
  <ul><li><a href="/media/pardi.pdf">Pardi Plaza</a></li></ul>
</div></body></html>"""


def test_bold_group_labels_and_an_offsite_entry_are_both_kept():
    entries = parse_index(
        BOLD_INDEX,
        base_url="https://city.example.gov/capitalprojects",
        content_selector="div.main",
        item_selector="ul li a",
        heading_tags=("strong", "b"),
        same_host_only=False,
    )

    assert [e["title"] for e in entries] == [
        "Waste Water Treatment Facility Expansion",
        "HSIP Cycle 11 Pedestrian Improvements",
        "Pardi Plaza",
    ]
    assert [e["group"] for e in entries] == [
        "Active Projects",
        "Active Projects",
        "Recently Completed",
    ]


def test_off_site_links_are_dropped_when_the_source_says_so():
    entries = parse_index(
        BOLD_INDEX,
        base_url="https://city.example.gov/capitalprojects",
        content_selector="div.main",
        item_selector="ul li a",
        heading_tags=("strong",),
        same_host_only=True,
    )

    assert [e["title"] for e in entries] == [
        "Waste Water Treatment Facility Expansion",
        "Pardi Plaza",
    ]


def test_renaming_a_group_reads_as_a_shape_change_even_with_no_detail_sections():
    """A list of PDF links has no sections; its group names are the whole shape."""

    def fingerprint_of(label: str) -> str:
        import asyncio

        adapter = build(
            index_body=BOLD_INDEX.replace("Active Projects", label),
            item_selector="ul li a",
            index_heading_tags=["strong"],
            same_host_only=False,
            fetch_details=False,
        )
        return asyncio.run(adapter.collect()).schema_fingerprint

    before = fingerprint_of("Active Projects")
    after = fingerprint_of("Projects Under Way")
    assert before and after and before != after
