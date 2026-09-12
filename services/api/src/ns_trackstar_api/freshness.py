from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def stale_after_minutes(poll_interval_minutes: int) -> int:
    """Use the source's own cadence to define a conservative stale threshold."""
    return max(30, poll_interval_minutes * 2)


def freshness_state(
    *,
    last_success_at: datetime | None,
    poll_interval_minutes: int,
    now: datetime,
) -> tuple[str, int | None]:
    if last_success_at is None:
        return "unknown", None
    if last_success_at.tzinfo is None:
        last_success_at = last_success_at.replace(tzinfo=UTC)
    age_minutes = max(0, int((now - last_success_at.astimezone(UTC)).total_seconds() // 60))
    threshold = stale_after_minutes(poll_interval_minutes)
    return ("stale" if age_minutes > threshold else "current"), age_minutes


@router.get("/projects/{project_id}/freshness")
async def project_freshness(request: Request, project_id: UUID) -> dict:
    project_cursor = await request.app.state.db.execute(
        "SELECT canonical_name FROM project WHERE id = %s",
        (project_id,),
    )
    project = await project_cursor.fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    cursor = await request.app.state.db.execute(
        """
        SELECT DISTINCT
          s.source_key,
          s.name,
          s.poll_interval_minutes,
          sh.health_state,
          sh.last_success_at,
          sh.last_content_change_at
        FROM project_source_record psr
        JOIN source_record sr ON sr.id = psr.source_record_id
        JOIN source s ON s.id = sr.source_id
        LEFT JOIN source_health sh ON sh.source_id = s.id
        WHERE psr.project_id = %s
        ORDER BY s.name
        """,
        (project_id,),
    )
    rows = await cursor.fetchall()

    now = datetime.now(UTC)
    sources: list[dict] = []
    for row in rows:
        interval = int(row["poll_interval_minutes"])
        state, age_minutes = freshness_state(
            last_success_at=row["last_success_at"],
            poll_interval_minutes=interval,
            now=now,
        )
        # A source can be operationally unhealthy even before the age threshold is
        # crossed. Keep public wording coarse; internal failure reasons stay private.
        if row["health_state"] in {"broken", "blocked", "schema_changed", "delayed"}:
            state = "stale" if row["last_success_at"] is not None else "unknown"
        sources.append(
            {
                "source_key": row["source_key"],
                "source_name": row["name"],
                "freshness_state": state,
                "last_success_at": (
                    row["last_success_at"].isoformat() if row["last_success_at"] else None
                ),
                "last_content_change_at": (
                    row["last_content_change_at"].isoformat()
                    if row["last_content_change_at"]
                    else None
                ),
                "checked_minutes_ago": age_minutes,
                "stale_after_minutes": stale_after_minutes(interval),
            }
        )

    known_ages = [
        source["checked_minutes_ago"]
        for source in sources
        if source["checked_minutes_ago"] is not None
    ]
    stale_sources = [source for source in sources if source["freshness_state"] == "stale"]
    unknown_sources = [source for source in sources if source["freshness_state"] == "unknown"]

    if stale_sources:
        overall = "stale"
    elif unknown_sources and len(unknown_sources) == len(sources):
        overall = "unknown"
    else:
        overall = "current"

    return {
        "project_id": str(project_id),
        "project_name": project["canonical_name"],
        "freshness_state": overall,
        "checked_minutes_ago": max(known_ages) if known_ages else None,
        "sources": sources,
        "metadata": {
            "checked_at": now.isoformat(),
            "source_count": len(sources),
            "stale_source_count": len(stale_sources),
            "unknown_source_count": len(unknown_sources),
            "note": (
                "Freshness describes Trackstar's last successful official-source check; "
                "it does not guarantee the agency changed its underlying record at that time."
            ),
        },
    }
