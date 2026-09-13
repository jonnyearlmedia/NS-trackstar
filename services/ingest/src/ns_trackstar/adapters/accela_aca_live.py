from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ns_trackstar.adapters.accela_aca import AccelaAcaAdapter as BaseAccelaAcaAdapter
from ns_trackstar.adapters.accela_aca import (
    _attribute,
    _find_control,
    _form_values,
    _next_page_postback,
    _parse_result_rows,
    _postback,
    _set_control_value,
)


def _form_action_url(soup: BeautifulSoup, fallback_url: str) -> str:
    form = soup.find("form", id="aspnetForm") or soup.find("form")
    if not isinstance(form, Tag):
        return fallback_url
    action = _attribute(form, "action")
    return urljoin(fallback_url, action) if action else fallback_url


class AccelaAcaAdapter(BaseAccelaAcaAdapter):
    """ACA adapter compatibility layer for current public Accela WebForms markup."""

    def _search_post_data(
        self,
        soup: BeautifulSoup,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        record_number: str | None = None,
    ) -> dict[str, str]:
        self._assert_search_contract(soup)
        data = _form_values(soup)
        search_button = _find_control(soup, "btnNewSearch")
        postback = _postback(search_button)
        if postback is None:
            raise RuntimeError("Accela ACA search button has no usable postback target")
        data["__EVENTTARGET"], data["__EVENTARGUMENT"] = postback

        search_type = _find_control(soup, "ddlSearchType")
        search_type_name = _attribute(search_type, "name")
        if search_type_name:
            data[search_type_name] = "General Search"

        if start_date is not None and not _set_control_value(
            data, soup, "txtGSStartDate", start_date
        ):
            raise RuntimeError("Accela ACA start-date control disappeared")
        if end_date is not None and not _set_control_value(data, soup, "txtGSEndDate", end_date):
            raise RuntimeError("Accela ACA end-date control disappeared")
        if record_number is not None:
            record_suffixes = ("txtGSPermitNumber", "txtGSRecordNumber", "txtGSNumber")
            if not any(
                _set_control_value(data, soup, suffix, record_number)
                for suffix in record_suffixes
            ):
                raise RuntimeError("Accela ACA record-number control was not found")
        return data

    async def _search(
        self,
        client: Any,
        module: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        record_number: str | None = None,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        search_url = self._search_url(module)
        initial_html = await self._request(client, "GET", search_url)
        soup = BeautifulSoup(initial_html, "html.parser")
        post_data = self._search_post_data(
            soup,
            start_date=start_date,
            end_date=end_date,
            record_number=record_number,
        )
        post_url = _form_action_url(soup, search_url)
        result_html = await self._request(client, "POST", post_url, data=post_data)

        records: list[dict[str, Any]] = []
        seen_pages: set[str] = set()
        page_limit = max_pages or self.max_pages
        for _ in range(page_limit):
            page_hash = hashlib.sha256(result_html.encode()).hexdigest()
            if page_hash in seen_pages:
                break
            seen_pages.add(page_hash)
            result_soup = BeautifulSoup(result_html, "html.parser")
            for record in _parse_result_rows(result_soup, self.base_url):
                if record not in records:
                    records.append(record)

            next_postback = _next_page_postback(result_soup)
            if next_postback is None:
                break
            next_data = _form_values(result_soup)
            next_data["__EVENTTARGET"], next_data["__EVENTARGUMENT"] = next_postback
            next_url = _form_action_url(result_soup, post_url)
            result_html = await self._request(client, "POST", next_url, data=next_data)
            post_url = next_url
        return records
