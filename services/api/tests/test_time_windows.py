from datetime import datetime

from ns_trackstar_api.app import _time_window_sql


def test_all_window_has_no_activity_filter() -> None:
    sql, params = _time_window_sql("all")
    assert sql == ""
    assert params == {}


def test_today_window_has_timezone_aware_boundary() -> None:
    sql, params = _time_window_sql("today")
    assert "last_activity_at" in sql
    boundary = params["activity_after"]
    assert isinstance(boundary, datetime)
    assert boundary.tzinfo is not None


def test_upcoming_excludes_completed_and_active_construction() -> None:
    sql, params = _time_window_sql("upcoming")
    assert "project_status_dimension" in sql
    assert "completed" in sql
    assert "construction" in sql
    assert params == {}
