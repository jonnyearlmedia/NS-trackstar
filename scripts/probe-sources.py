#!/usr/bin/env python3
"""Probe every candidate Trackstar source host and say what is actually reachable.

Why this exists: a coverage pass run from a sandboxed CI box recorded six
jurisdictions as "blocked" when the truth was narrower. The sandbox's egress policy
refused CONNECT to those hosts. That is a fact about the sandbox, not about the city.
"Blocked" and "blocked from where I happened to be standing" are different findings,
and only one of them is a reason to stop.

So: run this from the machine that will actually do the collecting. That means the
OVHcloud VM first, because it is the ground truth for what production can reach, and
a laptop second as a cross-check. Anywhere a result differs between the two, the
network is the variable, not the source.

    python3 scripts/probe-sources.py                 # table to stdout
    python3 scripts/probe-sources.py --json out.json # machine readable

Stdlib only, so it runs on a bare VM with no virtualenv.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "NS-Trackstar-probe/1.0 (+coverage reachability check)"
TIMEOUT = 25

# (jurisdiction, category, label, url)
# A host recorded as None is one whose address is not known yet and has to be found
# from the city's own site. Guessing a URL for it would be inventing an endpoint.
TARGETS: list[tuple[str, str, str, str | None]] = [
    # --- The six jurisdictions with no local source at all ---
    ("vacaville", "current_development", "City site (development activity, CIP, bids)",
     "https://www.ci.vacaville.ca.gov/"),
    ("vacaville", "government_meetings", "eScribe meeting portal",
     "https://vacaville.escribemeetings.com/"),
    ("vacaville", "government_meetings", "Legistar portal",
     "https://vacaville.legistar.com/Calendar.aspx"),
    ("vacaville", "permits", "eTRAKiT tenant host", None),
    ("dixon", "current_development", "City site",
     "https://www.ci.dixon.ca.us/"),
    ("dixon", "permits", "Tyler EnerGov SelfService",
     "https://dixonca-energovweb.tylerhost.net/apps/SelfService/"),
    ("dixon", "government_meetings", "Granicus agenda feed",
     "https://dixon-ca.granicus.com/ViewPublisherRSS.php?view_id=6&mode=agendas"),
    ("rio-vista", "current_development", "City site",
     "https://www.riovistacity.com/"),
    ("rio-vista", "permits", "MaintStar tenant", None),
    ("rio-vista", "government_meetings", "Granicus agenda feed",
     "https://riovista-ca.granicus.com/ViewPublisherRSS.php?view_id=1&mode=agendas"),
    ("benicia", "government_meetings", "Granicus agenda feed",
     "https://benicia.granicus.com/ViewPublisherRSS.php?view_id=1&mode=agendas"),
    ("yountville", "current_development", "Town site",
     "https://www.yountville.gov/"),
    ("yountville", "permits", "OpenGov tenant", None),
    ("st-helena", "current_development", "City site",
     "https://www.cityofsthelena.org/"),
    ("st-helena", "permits", "eTRAKiT tenant host", None),
    ("calistoga", "current_development", "City site",
     "https://www.ci.calistoga.ca.us/"),
    ("calistoga", "permits", "Citizenserve tenant", None),

    # --- Recorded as blocked; worth retesting from a different network ---
    ("fairfield", "current_development", "City site (Akamai 403 from sandbox)",
     "https://www.fairfield.ca.gov/"),
    ("fairfield", "permits", "Tyler Civic Access tenant", None),
    ("fairfield", "government_meetings", "eScribe meeting portal",
     "https://fairfield.escribemeetings.com/"),
    ("napa-county", "permits", "Accela Citizen Access (NAPACO)",
     "https://aca-prod.accela.com/NAPACO/Default.aspx"),
    ("solano-county", "permits", "Accela Citizen Access (SOLANOCO)",
     "https://aca-prod.accela.com/SOLANOCO/Default.aspx"),
    ("american-canyon", "permits", "OpenGov storefront",
     "https://americancanyonca.viewpointcloud.com/"),
    ("benicia", "permits", "OpenGov storefront",
     "https://beniciaca.viewpointcloud.com/"),

    # --- Statewide and regional ---
    ("all", "business_openings", "California ABC daily reports (Cloudflare challenge)",
     "https://www.abc.ca.gov/licensing/licensing-reports/new-applications/"),
    ("all", "business_openings", "California open data portal (sanctioned bulk route)",
     "https://data.ca.gov/api/3/action/package_search?q=alcoholic+beverage+control"),
    ("all", "transportation", "511 SF Bay traffic events (needs token)",
     "https://api.511.org/traffic/events"),

    # --- Known good, as a control. If these fail the probe itself is wrong. ---
    ("napa-county", "gis_spatial", "CONTROL: Napa County GIS",
     "https://gis.napacounty.gov/arcgis/rest/services?f=pjson"),
    ("vallejo", "permits", "CONTROL: Vallejo eTRAKiT",
     "https://vall-trk.aspgov.com/eTRAKiT/"),
]

CHALLENGE_MARKERS = (
    "challenges.cloudflare.com",
    "just a moment",
    "cf-mitigated",
    "_incapsula_",
    "access denied",
)


def classify(url: str) -> dict:
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
            body = response.read(4096).decode("utf-8", "replace").lower()
            challenged = any(marker in body for marker in CHALLENGE_MARKERS)
            return {
                "status": response.status,
                "verdict": "challenged" if challenged else "reachable",
                "seconds": round(time.monotonic() - started, 2),
            }
    except urllib.error.HTTPError as error:
        header_challenge = error.headers.get("cf-mitigated") == "challenge"
        body = ""
        try:
            body = error.read(4096).decode("utf-8", "replace").lower()
        except Exception:
            pass
        challenged = header_challenge or any(m in body for m in CHALLENGE_MARKERS)
        # A 401 means the door is there and wants a key, which is not the same as a wall.
        verdict = "challenged" if challenged else (
            "needs_credential" if error.code == 401 else f"http_{error.code}"
        )
        return {"status": error.code, "verdict": verdict,
                "seconds": round(time.monotonic() - started, 2)}
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as error:
        return {"status": None, "verdict": "unreachable",
                "detail": str(getattr(error, "reason", error))[:90],
                "seconds": round(time.monotonic() - started, 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="also write results to this path")
    args = parser.parse_args()

    todo = [t for t in TARGETS if t[3]]
    unknown = [t for t in TARGETS if not t[3]]

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(lambda t: classify(t[3]), todo))

    results = [
        {"jurisdiction": j, "category": c, "label": label, "url": url, **outcome}
        for (j, c, label, url), outcome in zip(todo, outcomes)
    ]

    width = max(len(r["jurisdiction"]) for r in results)
    print(f"\n{'JURISDICTION'.ljust(width)}  {'VERDICT':<16} {'CODE':<5} LABEL")
    print("-" * (width + 70))
    for row in sorted(results, key=lambda r: (r["verdict"], r["jurisdiction"])):
        code = str(row["status"] or "-")
        print(f"{row['jurisdiction'].ljust(width)}  {row['verdict']:<16} {code:<5} {row['label']}")
        if row.get("detail"):
            print(f"{' ' * (width + 2)}  ^ {row['detail']}")

    if unknown:
        print("\nHosts not yet known. Find these from the city's own site rather than\n"
              "guessing a URL, then add them to TARGETS:")
        for jurisdiction, _category, label, _url in unknown:
            print(f"  {jurisdiction:<{width}}  {label}")

    counts: dict[str, int] = {}
    for row in results:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    print("\n" + "  ".join(f"{verdict}={count}" for verdict, count in sorted(counts.items())))

    if args.json:
        payload = {"probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "results": results,
                   "hosts_unknown": [
                       {"jurisdiction": j, "category": c, "label": label}
                       for j, c, label, _ in unknown
                   ]}
        with open(args.json, "w") as handle:
            json.dump(payload, handle, indent=2)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
