from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FreshnessClass = Literal[
    "meeting_feed",
    "active_project_tracker",
    "state_project_watch",
    "regulatory_watch",
    "project_specific_record",
    "parcel_reference",
    "spatial_reference",
]


@dataclass(frozen=True, slots=True)
class SourceFreshnessPolicy:
    freshness_class: FreshnessClass
    meaningful_change_window: str
    recommended_min_minutes: int
    recommended_max_minutes: int
    rationale: str


SOURCE_FRESHNESS_POLICIES: dict[str, SourceFreshnessPolicy] = {
    "american-canyon.granicus-archives": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Published meeting feed carrying Council and the boards; a newly posted agenda "
        "is the earliest public signal that a project is about to be decided.",
    ),
    "american-canyon.granicus-events": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "The second panel of the city's own meetings page. It reaches further back for "
        "Planning Commission and the commissions than the archive panel, whose 101-item "
        "feed cap is taken up by Council.",
    ),
    "american-canyon.construction-development-updates": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 240,
        "Active municipal construction/development tracker; same-day stage/project edits are useful.",
    ),
    "benicia.granicus": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Published meeting feed where a newly posted agenda is the earliest public "
        "signal that a project is about to be decided.",
    ),
    "benicia.current-planning-applications": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 240,
        "Current planning application inventory; useful changes are typically municipal business-day edits.",
    ),
    "bia.scotts-valley-gaming-decisions": SourceFreshnessPolicy(
        "regulatory_watch", "daily", 720, 1440,
        "Federal decision/document set; important when it changes, but sub-hour polling adds little value.",
    ),
    "california.ceqanet.napa-solano": SourceFreshnessPolicy(
        "state_project_watch", "within_day", 360, 720,
        "State environmental filings can materially change project context during the day.",
    ),
    "caltrans.building-ca.napa-solano": SourceFreshnessPolicy(
        "state_project_watch", "within_day", 360, 720,
        "State transportation project updates are valuable same-day but are not minute-by-minute events.",
    ),
    "fairfield.one-lake-assessor-map": SourceFreshnessPolicy(
        "project_specific_record", "rare", 1440, 10080,
        "Authoritative project-specific reference document; changes are infrequent.",
    ),
    "fairfield.one-lake-council-goals": SourceFreshnessPolicy(
        "project_specific_record", "rare", 1440, 10080,
        "Project-specific council/reference record with low expected edit frequency.",
    ),
    "fairfield.vanden-canon-overcrossing": SourceFreshnessPolicy(
        "project_specific_record", "rare", 1440, 10080,
        "Project-specific official record; useful as evidence but not a fast-changing feed.",
    ),
    "dixon.granicus": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Published meeting feed where a newly posted agenda is the earliest public "
        "signal that a project is about to be decided.",
    ),
    "federal-register.napa-solano": SourceFreshnessPolicy(
        "regulatory_watch", "daily", 1440, 1440,
        "Federal Register publication cadence makes daily checks sufficient for local intelligence.",
    ),
    "napa-city.etrakit": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 480,
        "Permit and planning case records where a same-day status change is real news; "
        "discovery is prefix-partitioned so a faster cadence would not find more.",
    ),
    "napa-city.legistar": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Structured public meeting/agendum feed; same-day agenda and item changes matter.",
    ),
    "napa-city.napa-pipe-amendments": SourceFreshnessPolicy(
        "project_specific_record", "rare", 1440, 10080,
        "Allowlisted authoritative project documents; changes are infrequent and discrete.",
    ),
    "napa-city.public-works-cip": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 240,
        "Municipal capital-project tracker where construction/status changes are useful within the day.",
    ),
    "napa-city.water-cip": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 240,
        "Municipal water capital-project tracker; useful changes are operationally same-day, not real-time.",
    ),
    "napa-county.legistar": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "County Board of Supervisors and Zoning Administrator feed; this is where "
        "unincorporated Napa County land-use decisions are noticed, so a newly posted "
        "agenda is the earliest public signal.",
    ),
    "napa-county.current-projects-explorer": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 240,
        "County current-project explorer directly supports Trackstar's site/project identification job.",
    ),
    "napa-county.napa-pipe-development-plan": SourceFreshnessPolicy(
        "project_specific_record", "rare", 1440, 10080,
        "Authoritative project-specific plan; useful evidence with low expected change frequency.",
    ),
    "napa-county.parcels": SourceFreshnessPolicy(
        "parcel_reference", "rare", 1440, 10080,
        "Parcel geometry/reference data changes slowly and should not be polled like an activity feed.",
    ),
    "nigc.scotts-valley-gaming-ordinance": SourceFreshnessPolicy(
        "regulatory_watch", "daily", 720, 1440,
        "Federal gaming regulatory record; significant but low-frequency changes.",
    ),
    "napa-county.addresses": SourceFreshnessPolicy(
        "spatial_reference", "rare", 1440, 10080,
        "Address points are the base layer used to place a record, not an activity feed.",
    ),
    "napa-county.city-boundaries": SourceFreshnessPolicy(
        "spatial_reference", "rare", 1440, 10080,
        "Incorporated city limits change through annexation, which is a rare and discrete event.",
    ),
    "napa-county.road-centerlines": SourceFreshnessPolicy(
        "spatial_reference", "rare", 1440, 10080,
        "Road centrelines anchor corridor and intersection geometry; they change slowly.",
    ),
    "napa-county.zoning": SourceFreshnessPolicy(
        "spatial_reference", "rare", 1440, 10080,
        "Zoning is context for what a site may become, and is amended rarely.",
    ),
    "rio-vista.granicus": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Published meeting feed where a newly posted agenda is the earliest public "
        "signal that a project is about to be decided.",
    ),
    "st-helena.civicclerk": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Published meeting feed; a newly posted agenda is the earliest public signal "
        "that a project is about to be decided.",
    ),
    "st-helena.planning-projects": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 240,
        "The city's own hand-maintained planning-project pages. Staff edit them during "
        "the business day when a case is deemed complete or approved.",
    ),
    "solano-county.city-boundaries": SourceFreshnessPolicy(
        "spatial_reference", "rare", 1440, 10080,
        "Incorporated city limits change through annexation, which is a rare and discrete event.",
    ),
    "solano-county.streets": SourceFreshnessPolicy(
        "spatial_reference", "rare", 1440, 10080,
        "Street centrelines with address ranges are the base layer for address-level geocoding.",
    ),
    "solano-county.legistar": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Structured public meeting/agendum feed; same-day agenda and item changes matter.",
    ),
    "solano-county.parcels": SourceFreshnessPolicy(
        "parcel_reference", "rare", 1440, 10080,
        "Parcel geometry/reference data changes slowly and should not be polled like an activity feed.",
    ),
    "suisun-city.granicus": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Published meeting feed carrying Council, Planning Commission and the standing "
        "committees; a newly posted agenda is the earliest public signal that a project "
        "is about to be decided.",
    ),
    "suisun-city.development-calendar": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 240,
        "Current municipal development inventory; same-day status/project changes are useful.",
    ),
    "suisun-city.dutch-bros-public-notice": SourceFreshnessPolicy(
        "project_specific_record", "rare", 1440, 10080,
        "Single-project official notice/document evidence, not a continuously changing tracker.",
    ),
    "vacaville.escribe": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Published meeting feed carrying Council, Planning Commission and the Parks "
        "and Recreation Commission; a newly posted agenda is the earliest public "
        "signal that a project is about to be decided.",
    ),
    "vallejo.civicclerk": SourceFreshnessPolicy(
        "meeting_feed", "same_day", 60, 120,
        "Meeting/agendum feed where same-day changes matter; current 120-minute polling is temporary while churn is audited.",
    ),
    "vallejo.etrakit": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 480,
        "Permit and planning case records where a same-day status change is real news; "
        "discovery is prefix-partitioned so a faster cadence would not find more.",
    ),
    "vallejo.value-current-development": SourceFreshnessPolicy(
        "active_project_tracker", "within_day", 120, 240,
        "Current development tracker directly supports site identification and project-stage discovery.",
    ),
}


def source_freshness_policy(source_key: str) -> SourceFreshnessPolicy | None:
    return SOURCE_FRESHNESS_POLICIES.get(source_key)
