from __future__ import annotations

import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.granicus_rss import GranicusRssAdapter, split_title

FEED = """<?xml version="1.0" ?>
<rss version="2.0" xmlns:gran="https://www.granicus.com/schema/rss-supplements">
<channel>
  <title>The City of Dixon, CA: City of Dixon View (Agenda Feed)</title>
  <item>
    <guid isPermaLink="false">aaaa-1</guid>
    <title>City Council Meeting - Sep 15, 2026</title>
    <link>https://dixon-ca.granicus.com/AgendaViewer.php?view_id=6&amp;event_id=3019</link>
    <pubDate>Fri, 11 Sep 2026 01:53:27 -0700</pubDate>
    <description>&lt;p&gt;The agenda for City Council Meeting dated Tuesday.&lt;/p&gt;</description>
  </item>
  <item>
    <guid isPermaLink="false">aaaa-2</guid>
    <title>Planning Commission - Sep 08, 2026</title>
    <link>https://dixon-ca.granicus.com/AgendaViewer.php?view_id=6&amp;event_id=3001</link>
    <pubDate>Tue, 08 Sep 2026 07:00:00 -0700</pubDate>
    <description>Planning Commission agenda.</description>
  </item>
  <item>
    <guid isPermaLink="false">aaaa-3</guid>
    <title>Dixon USD Board Meeting - Tremont Elementary, MPR, 355 Pheasant Run</title>
    <link>https://dixon-ca.granicus.com/AgendaViewer.php?view_id=6&amp;event_id=2990</link>
    <pubDate>Thu, 10 Sep 2026 06:00:00 -0700</pubDate>
    <description>School board.</description>
  </item>
</channel></rss>
"""


def build(**options) -> GranicusRssAdapter:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=FEED, headers={"content-type": "text/xml"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GranicusRssAdapter(
        SourceConfig(
            key="dixon.granicus",
            name="Dixon Granicus",
            jurisdiction="City of Dixon",
            base_url="https://dixon-ca.granicus.com",
            poll_minutes=120,
            options={"view_id": "6", "mode": "agendas", "min_expected_items": 1, **options},
        ),
        client=client,
    )


def test_a_body_name_containing_a_dash_is_not_mistaken_for_a_date():
    """"Dixon USD Board Meeting - Tremont Elementary, MPR, 355 Pheasant Run" is all body."""

    body, date_text = split_title("Dixon USD Board Meeting - Tremont Elementary, MPR, 355 Pheasant Run")
    assert body == "Dixon USD Board Meeting - Tremont Elementary, MPR, 355 Pheasant Run"
    assert date_text is None


def test_a_real_trailing_date_is_split_off():
    assert split_title("City Council Meeting - Sep 15, 2026") == ("City Council Meeting", "Sep 15, 2026")
    assert split_title("Planning Commission - Sep 08, 2026") == ("Planning Commission", "Sep 08, 2026")


@pytest.mark.asyncio
async def test_every_published_meeting_is_kept_by_default():
    result = await build().collect()

    assert len(result.records) == 3
    assert result.parser_yield == 1.0
    assert result.metadata["items_in_feed"] == 3
    # The city publishes the school district in its own view; that is the city's choice.
    assert "Dixon USD Board Meeting - Tremont Elementary, MPR, 355 Pheasant Run" in (
        result.metadata["meeting_bodies_seen"]
    )


@pytest.mark.asyncio
async def test_records_carry_the_agenda_url_and_a_parsed_meeting_date():
    result = await build().collect()
    council = next(r for r in result.records if r.external_id == "aaaa-1")

    assert council.canonical_url.endswith("event_id=3019")
    assert council.normalized_payload["meeting_body"] == "City Council Meeting"
    assert council.normalized_payload["meeting_date"] == "2026-09-15"
    assert council.source_updated_at is not None
    # Description markup is stripped rather than stored as HTML.
    assert "<p>" not in council.normalized_payload["summary"]
    assert "agenda for City Council Meeting" in council.normalized_payload["summary"]


@pytest.mark.asyncio
async def test_a_config_can_narrow_to_named_bodies():
    result = await build(meeting_bodies=["Planning Commission"]).collect()

    assert [r.external_id for r in result.records] == ["aaaa-2"]
    # The feed is still reported in full so the filter cannot hide a shrinking source.
    assert result.metadata["items_in_feed"] == 3
    assert result.parser_yield < 1.0


@pytest.mark.asyncio
async def test_an_empty_feed_fails_the_canary():
    """A city view reporting no meetings is a broken feed, not a city that stopped."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='<?xml version="1.0" ?><rss><channel></channel></rss>')

    adapter = GranicusRssAdapter(
        SourceConfig(
            key="dixon.granicus", name="x", jurisdiction="x",
            base_url="https://dixon-ca.granicus.com", poll_minutes=120,
            options={"view_id": "6", "min_expected_items": 10},
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await adapter.canary() is False


@pytest.mark.asyncio
async def test_unparseable_xml_fails_the_canary_instead_of_raising():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not a feed</html>")

    adapter = GranicusRssAdapter(
        SourceConfig(
            key="dixon.granicus", name="x", jurisdiction="x",
            base_url="https://dixon-ca.granicus.com", poll_minutes=120,
            options={"view_id": "6"},
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await adapter.canary() is False


def test_a_config_must_say_which_view_to_read():
    with pytest.raises(ValueError, match="feed_url or view_id"):
        GranicusRssAdapter(
            SourceConfig(
                key="x", name="x", jurisdiction="x",
                base_url="https://dixon-ca.granicus.com", poll_minutes=120, options={},
            )
        )
