from __future__ import annotations

from datetime import date

import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.civicweb import CivicWebAdapter, meeting_id_of, split_title

LIST_PAGE = """<html><body>
  <div class="portal">
    <a href="/Portal/MeetingInformation.aspx?Id=4712">*Amended Agenda* City Council - Regular Meeting - Sep 15 2026</a>
    <a href="/Portal/MeetingInformation.aspx?Id=4659">Planning Commission - Sep 09 2026</a>
    <a href="/Portal/MeetingInformation.aspx?Id=4658">* MEETING CANCELLED* Planning Commission</a>
    <a href="/Portal/MeetingInformation.aspx?Id=4715">*SPECIAL MEETING* - Housing Advisory Committee - Jul 27 2026 (Rescheduling of Jul 20 2026))</a>
    <a href="/Portal/MeetingInformation.aspx?Id=4712">City Council duplicate link</a>
    <a href="/Portal/Help.aspx">Portal Help</a>
  </div>
</body></html>"""

EMPTY_PAGE = "<html><body><div class='portal'><a href='/Portal/Help.aspx'>Help</a></div></body></html>"


def build(*, status: int = 200, body: str = LIST_PAGE, **options) -> CivicWebAdapter:
    def handler(_request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="blocked")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CivicWebAdapter(
        SourceConfig(
            key="calistoga.civicweb",
            name="Calistoga CivicWeb",
            jurisdiction="City of Calistoga",
            base_url="https://city.civicweb.example",
            poll_minutes=120,
            options={
                "portal_url": "https://city.civicweb.example",
                "min_expected_meetings": 1,
                **options,
            },
        ),
        client=client,
    )


def test_a_status_prefix_is_lifted_off_the_body_name():
    body, note, when = split_title("*Amended Agenda* City Council - Regular Meeting - Sep 15 2026")

    assert body == "City Council - Regular Meeting"
    assert note == "Amended Agenda"
    assert when == date(2026, 9, 15)


def test_a_dash_left_behind_by_a_removed_prefix_is_trimmed():
    body, note, when = split_title(
        "*SPECIAL MEETING* - Housing Advisory Committee - Jul 27 2026 (Rescheduling of Jul 20 2026))"
    )

    assert body == "Housing Advisory Committee"
    assert when == date(2026, 7, 27)
    # The parenthetical is kept, because it says why the meeting moved.
    assert note == "SPECIAL MEETING; Rescheduling of Jul 20 2026"


def test_a_title_with_no_date_keeps_its_whole_body_name():
    body, note, when = split_title("* MEETING CANCELLED* Planning Commission")

    assert body == "Planning Commission"
    assert note == "MEETING CANCELLED"
    assert when is None


def test_the_meeting_id_is_read_from_the_query_string():
    assert meeting_id_of("https://x/Portal/MeetingInformation.aspx?Id=4712") == "4712"
    assert meeting_id_of("https://x/Portal/Help.aspx") is None


@pytest.mark.asyncio
async def test_only_meeting_links_become_records_and_duplicates_collapse():
    result = await build().collect()

    assert sorted(record.external_id for record in result.records) == [
        "4658",
        "4659",
        "4712",
        "4715",
    ]
    assert result.parser_yield == 1.0
    assert result.metadata["meetings_in_list"] == 4


@pytest.mark.asyncio
async def test_a_meeting_with_no_parseable_date_is_reported_not_dropped():
    result = await build().collect()

    assert result.metadata["meetings_without_a_parsed_date"] == ["4658"]
    cancelled = next(r for r in result.records if r.external_id == "4658")
    assert cancelled.normalized_payload["meeting_date"] is None
    assert cancelled.normalized_payload["meeting_status_note"] == "MEETING CANCELLED"


@pytest.mark.asyncio
async def test_a_template_change_that_hides_every_meeting_fails_the_canary():
    assert await build(body=EMPTY_PAGE).canary() is False
    assert await build().canary() is True


@pytest.mark.asyncio
async def test_a_blocked_portal_is_reported_as_blocked_not_as_an_empty_run():
    with pytest.raises(SourceBlockedError):
        await build(status=403).collect()
    assert await build(status=403).canary() is False
