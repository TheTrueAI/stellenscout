"""SerpApi-backed job search provider (Google Jobs).

This module wraps the existing SerpApi integration behind the
:class:`~immermatch.search_api.search_provider.SearchProvider` protocol so it can
be swapped in alongside other providers (e.g. Bundesagentur für Arbeit).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from serpapi import GoogleSearch

from ..location import location_search_variants
from ..models import ApplyOption, JobListing

# ---------------------------------------------------------------------------
# Blocked portal list (loaded from external file)
# ---------------------------------------------------------------------------


def _load_blocked_portals() -> set[str]:
    path = Path(__file__).parent / "blocked_portals.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    return {line.strip().lower() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")}


BLOCKED_PORTALS: set[str] = _load_blocked_portals()

# ---------------------------------------------------------------------------
# Trusted portal list (known legitimate job boards)
# ---------------------------------------------------------------------------

_TRUSTED_PORTALS: set[str] = {
    "linkedin",
    "xing",
    "stepstone",
    "indeed",
    "glassdoor",
    "kununu",
    "karriere",
    "monster",
    "softgarden",
    "oproma",
    "personio",
    "ashby",
}

# ---------------------------------------------------------------------------
# Staleness filter
# ---------------------------------------------------------------------------

_STALE_THRESHOLD_DAYS = 14


def _is_stale(posted_at: str) -> bool:
    """Return True when a listing's posted_at text indicates it is too old."""
    if not posted_at:
        return False
    lower = posted_at.lower().strip()
    match = re.match(r"(\d+)\+?\s*days?\s*ago", lower)
    if match and int(match.group(1)) > _STALE_THRESHOLD_DAYS:
        return True
    return "month" in lower or "year" in lower


# ---------------------------------------------------------------------------
# Google gl= country codes
# ---------------------------------------------------------------------------

GL_CODES: dict[str, str] = {
    # Countries
    "germany": "de",
    "deutschland": "de",
    "france": "fr",
    "netherlands": "nl",
    "holland": "nl",
    "belgium": "be",
    "austria": "at",
    "österreich": "at",
    "switzerland": "ch",
    "schweiz": "ch",
    "suisse": "ch",
    "spain": "es",
    "españa": "es",
    "italy": "it",
    "italia": "it",
    "portugal": "pt",
    "poland": "pl",
    "polska": "pl",
    "sweden": "se",
    "sverige": "se",
    "norway": "no",
    "norge": "no",
    "denmark": "dk",
    "danmark": "dk",
    "finland": "fi",
    "suomi": "fi",
    "ireland": "ie",
    "czech republic": "cz",
    "czechia": "cz",
    "romania": "ro",
    "hungary": "hu",
    "greece": "gr",
    "luxembourg": "lu",
    "uk": "uk",
    "united kingdom": "uk",
    "england": "uk",
    # Major cities → country
    "berlin": "de",
    "munich": "de",
    "münchen": "de",
    "hamburg": "de",
    "frankfurt": "de",
    "stuttgart": "de",
    "düsseldorf": "de",
    "köln": "de",
    "cologne": "de",
    "hannover": "de",
    "nürnberg": "de",
    "nuremberg": "de",
    "leipzig": "de",
    "dresden": "de",
    "dortmund": "de",
    "essen": "de",
    "bremen": "de",
    "paris": "fr",
    "lyon": "fr",
    "marseille": "fr",
    "toulouse": "fr",
    "amsterdam": "nl",
    "rotterdam": "nl",
    "eindhoven": "nl",
    "utrecht": "nl",
    "brussels": "be",
    "bruxelles": "be",
    "antwerp": "be",
    "vienna": "at",
    "wien": "at",
    "graz": "at",
    "zurich": "ch",
    "zürich": "ch",
    "geneva": "ch",
    "genève": "ch",
    "basel": "ch",
    "bern": "ch",
    "madrid": "es",
    "barcelona": "es",
    "rome": "it",
    "milan": "it",
    "milano": "it",
    "lisbon": "pt",
    "porto": "pt",
    "warsaw": "pl",
    "kraków": "pl",
    "krakow": "pl",
    "wrocław": "pl",
    "stockholm": "se",
    "gothenburg": "se",
    "malmö": "se",
    "oslo": "no",
    "copenhagen": "dk",
    "helsinki": "fi",
    "dublin": "ie",
    "prague": "cz",
    "bucharest": "ro",
    "budapest": "hu",
    "athens": "gr",
    "london": "uk",
    "manchester": "uk",
    "edinburgh": "uk",
}

# ---------------------------------------------------------------------------
# Remote-search helpers
# ---------------------------------------------------------------------------

_REMOTE_TOKENS = {"remote", "worldwide", "global", "anywhere", "weltweit"}


def is_remote_only(location: str) -> bool:
    """Return True when the location string contains ONLY remote-like tokens."""
    words = {re.sub(r"[^\w]", "", w).lower() for w in location.split() if w.strip()}
    return bool(words) and words <= _REMOTE_TOKENS


def infer_gl(location: str) -> str | None:
    """Infer a Google gl= country code from a free-form location string.

    Returns *None* for purely remote/global searches so the caller can
    decide whether to set ``gl`` at all (SerpApi defaults to "us").
    Falls back to "de" when a location is given but no country can be
    determined.
    """
    if is_remote_only(location):
        return None
    loc_lower = location.lower()
    for name, code in GL_CODES.items():
        if name in loc_lower:
            return code
    return "de"


# ---------------------------------------------------------------------------
# City / country localisation for Google Jobs queries
# ---------------------------------------------------------------------------

CITY_LOCALISE: dict[str, str] = {
    "munich": "München",
    "cologne": "Köln",
    "nuremberg": "Nürnberg",
    "hanover": "Hannover",
    "dusseldorf": "Düsseldorf",
    "vienna": "Wien",
    "zurich": "Zürich",
    "geneva": "Genève",
    "prague": "Praha",
    "warsaw": "Warszawa",
    "krakow": "Kraków",
    "wroclaw": "Wrocław",
    "copenhagen": "København",
    "athens": "Athína",
    "bucharest": "București",
    "milan": "Milano",
    "rome": "Roma",
    "lisbon": "Lisboa",
    "brussels": "Bruxelles",
    "antwerp": "Antwerpen",
    "gothenburg": "Göteborg",
}

COUNTRY_LOCALISE: dict[str, str] = {
    "germany": "Deutschland",
    "austria": "Österreich",
    "switzerland": "Schweiz",
    "netherlands": "Niederlande",
    "czech republic": "Česká republika",
    "czechia": "Česko",
    "poland": "Polska",
    "sweden": "Sverige",
    "norway": "Norge",
    "denmark": "Danmark",
    "finland": "Suomi",
    "hungary": "Magyarország",
    "romania": "România",
    "greece": "Ελλάδα",
}

_LOCALISE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in CITY_LOCALISE) + r")\b",
    re.IGNORECASE,
)

_COUNTRY_LOCALISE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(COUNTRY_LOCALISE, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def localise_query(query: str) -> str:
    """Replace English city and country names with their local equivalents."""
    query = _LOCALISE_PATTERN.sub(lambda m: CITY_LOCALISE[m.group(0).lower()], query)
    return _COUNTRY_LOCALISE_PATTERN.sub(lambda m: COUNTRY_LOCALISE[m.group(0).lower()], query)


# ---------------------------------------------------------------------------
# SerpApi response parsing
# ---------------------------------------------------------------------------


def parse_job_results(results: dict) -> list[JobListing]:
    """Parse job listings from a SerpApi response dict."""
    jobs: list[JobListing] = []

    def _normalize_link(link: str) -> str:
        stripped = link.strip()
        if not stripped:
            return ""
        if "://" not in stripped:
            return f"https://{stripped.lstrip('/')}"
        return stripped

    def _extract_domain(link: str) -> str:
        netloc = urlparse(_normalize_link(link)).netloc.lower().strip()
        if netloc.startswith("www."):
            return netloc[4:]
        return netloc

    def _domain_matches(domain: str, token: str) -> bool:
        token = token.strip().lower().lstrip(".")
        if not domain or not token:
            return False
        if "." in token:
            return domain == token or domain.endswith(f".{token}")
        return token in domain.split(".")

    for job_data in results.get("jobs_results", []):
        posted_at = job_data.get("detected_extensions", {}).get("posted_at", "")
        if _is_stale(posted_at):
            continue

        description_parts = []
        if "description" in job_data:
            description_parts.append(job_data["description"])
        if "highlights" in job_data:
            for highlight in job_data.get("highlights", []):
                if "items" in highlight:
                    description_parts.extend(highlight["items"])

        apply_options = []
        has_trusted = False
        has_company_career = False
        for option in job_data.get("apply_options", []):
            if "title" not in option or "link" not in option:
                continue
            normalized_link = _normalize_link(option["link"])
            if not normalized_link:
                continue
            domain = _extract_domain(normalized_link)
            if not domain:
                continue
            if any(_domain_matches(domain, blocked) for blocked in BLOCKED_PORTALS):
                continue
            apply_options.append(ApplyOption(source=option["title"], url=normalized_link))
            if any(_domain_matches(domain, trusted) for trusted in _TRUSTED_PORTALS):
                has_trusted = True
            source_lower = option["title"].lower()
            if "career" in source_lower or "company" in source_lower:
                has_company_career = True

        if not apply_options:
            continue

        reliability: Literal["aggregator", "unverified"] = (
            "aggregator" if (has_trusted or has_company_career) else "unverified"
        )

        job = JobListing(
            title=job_data.get("title", "Unknown"),
            company_name=job_data.get("company_name", "Unknown"),
            location=job_data.get("location", "Unknown"),
            description="\n".join(description_parts),
            link=job_data.get("share_link", job_data.get("link", "")),
            posted_at=posted_at,
            source="serpapi",
            apply_options=apply_options,
            reliability=reliability,
        )
        jobs.append(job)

    return jobs


# ---------------------------------------------------------------------------
# Direct SerpApi search
# ---------------------------------------------------------------------------


def search_jobs(
    query: str,
    num_results: int = 10,
    gl: str | None = "de",
    location: str | None = None,
) -> list[JobListing]:
    """Search for jobs using SerpApi Google Jobs engine with pagination."""
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        raise ValueError("SERPAPI_KEY environment variable not set")

    all_jobs: list[JobListing] = []
    next_page_token = None

    while len(all_jobs) < num_results:
        params: dict[str, str] = {
            "engine": "google_jobs",
            "q": query,
            "hl": "en",
            "chips": "date_posted:week",
            "api_key": api_key,
        }
        if gl is not None:
            params["gl"] = gl
        if location is not None:
            params["location"] = location
        if next_page_token:
            params["next_page_token"] = next_page_token

        search = GoogleSearch(params)
        results = search.get_dict()

        page_jobs = parse_job_results(results)
        if not page_jobs:
            break

        all_jobs.extend(page_jobs)

        pagination = results.get("serpapi_pagination", {})
        next_page_token = pagination.get("next_page_token")
        if not next_page_token:
            break

    return all_jobs[:num_results]


# ---------------------------------------------------------------------------
# SerpApiProvider (SearchProvider protocol)
# ---------------------------------------------------------------------------


class SerpApiProvider:
    """Google Jobs search via SerpApi.

    Satisfies the :class:`~immermatch.search_api.search_provider.SearchProvider` protocol.
    """

    name: str = "SerpApi (Google Jobs)"
    source_id: str = "serpapi"

    def search(
        self,
        query: str,
        location: str,
        max_results: int = 50,
    ) -> list[JobListing]:
        """Run SerpApi searches across all location variants and merge results."""
        localised_query = localise_query(query)
        variants = location_search_variants(location)
        per_variant = max(max_results // len(variants), 10)

        seen: set[str] = set()
        all_jobs: list[JobListing] = []

        for variant in variants:
            remote = is_remote_only(variant)
            gl = infer_gl(variant)
            serpapi_location: str | None = None if remote else variant or None
            jobs = search_jobs(localised_query, num_results=per_variant, gl=gl, location=serpapi_location)
            for job in jobs:
                dedup_key = f"{job.title}|{job.company_name}|{job.location}"
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    all_jobs.append(job)

        return all_jobs[:max_results]
