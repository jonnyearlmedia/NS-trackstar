from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ns_trackstar.adapters.accela_aca import (
    AccelaAcaAdapter as BaseAccelaAcaAdapter,
    _attribute,
    _find_control,
    _form_values,
    _set_control_value,
)


def _live_postback(tag: Tag | None) -> tuple[str, str] | None:
    if tag is None:
        return None
    href = _attribute(tag, "href")
    if href:
        for pattern in (
            r"__doPostBack\(['\"]([^'\"]+)['\"],\s*['\"]([^'\"]*)['\"]\)",
            r"WebForm_PostBackOptions\(['\"]([^'\"]+)['\"],\s*['\"]([^'\"]*)['\"]",
        ):
            match = re.search(pattern, href)
            if match:
                return match.group(1), match.group(2)
    name = _attribute(tag, "name")
    return (name, "") if name else None


class AccelaAcaAdapter(BaseAccelaAcaAdapter):
    """ACA adapter compatibility layer for current Accela WebForm_PostBackOptions markup."""

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
        postback = _live_postback(search_button)
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
