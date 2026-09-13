import re

from ns_trackstar.adapters.tabular_pdf_project_tracker import parse_tabular_page


def test_parses_positioned_row_and_uses_nearest_project_number_for_identity() -> None:
    fragments = [
        (34, 390, "Commercial"),
        (101, 390, "Raising Canes"),
        (355, 420, "MJP24-0001"),
        (355, 390, "LR24-0007"),
        (407, 390, "New restaurant with drive-through lanes"),
        (686, 390, "Under Construction"),
        # A long preceding row can extend into this row's midpoint window.
        (355, 414, "OLD24-9999"),
    ]

    rows = parse_tabular_page(
        fragments,
        columns={
            "project_type": (0, 80),
            "name": (80, 158),
            "project_numbers": (346, 405),
            "description": (405, 680),
            "official_status_text": (680, 765),
        },
        row_labels={"Commercial"},
        page_top=495,
        page_bottom=25,
        anchor_max_x=80,
        external_id_pattern=re.compile(r"\b[A-Z]{2,4}\d{2}-\d{4}\b"),
    )

    assert len(rows) == 1
    assert rows[0]["external_id"] == "LR24-0007"
    assert rows[0]["name"] == "Raising Canes"
    assert rows[0]["official_status_text"] == "Under Construction"


def test_skips_page_headers_that_are_not_configured_row_labels() -> None:
    rows = parse_tabular_page(
        [(28, 517, "Project Type"), (95, 517, "Project Name")],
        columns={"project_numbers": (346, 405)},
        row_labels={"Commercial", "Residential"},
        page_top=495,
        page_bottom=25,
        anchor_max_x=80,
        external_id_pattern=re.compile(r"\b[A-Z]{2,4}\d{2}-\d{4}\b"),
    )

    assert rows == []
