"""SerpApi-backed job search provider (Google Jobs).

This module wraps the existing SerpApi integration behind the
:class:`~immermatch.search_provider.SearchProvider` protocol so it can
be swapped in alongside other providers (e.g. Bundesagentur für Arbeit).
"""

from __future__ import annotations

import os
import re

from serpapi import GoogleSearch

from .models import ApplyOption, JobListing

# ---------------------------------------------------------------------------
# Blocked portal list (questionable job aggregators / paywalls)
# ---------------------------------------------------------------------------

BLOCKED_PORTALS = {
    "bebee",
    "trabajo",
    "jooble",
    "adzuna",
    "jobrapido",
    "neuvoo",
    "mitula",
    "trovit",
    "jobomas",
    "jobijoba",
    "talent",
    "jobatus",
    "jobsora",
    "studysmarter",
    "jobilize",
    "learn4good",
    "grabjobs",
    "jobtensor",
    "zycto",
    "terra.do",
    "jobzmall",
    "simplyhired",
}

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

    for job_data in results.get("jobs_results", []):
        description_parts = []
        if "description" in job_data:
            description_parts.append(job_data["description"])
        if "highlights" in job_data:
            for highlight in job_data.get("highlights", []):
                if "items" in highlight:
                    description_parts.extend(highlight["items"])

        apply_options = []
        for option in job_data.get("apply_options", []):
            if "title" in option and "link" in option:
                url = option["link"].lower()
                if not any(blocked in url for blocked in BLOCKED_PORTALS):
                    apply_options.append(ApplyOption(source=option["title"], url=option["link"]))

        if not apply_options:
            continue

        job = JobListing(
            title=job_data.get("title", "Unknown"),
            company_name=job_data.get("company_name", "Unknown"),
            location=job_data.get("location", "Unknown"),
            description="\n".join(description_parts),
            link=job_data.get("share_link", job_data.get("link", "")),
            posted_at=job_data.get("detected_extensions", {}).get("posted_at", ""),
            source="serpapi",
            apply_options=apply_options,
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

    Satisfies the :class:`~immermatch.search_provider.SearchProvider` protocol.
    """

    name: str = "SerpApi (Google Jobs)"

    def search(
        self,
        query: str,
        location: str,
        max_results: int = 50,
    ) -> list[JobListing]:
        """Run a single SerpApi search with localisation and gl-code inference."""
        remote = is_remote_only(location)
        gl = infer_gl(location)
        serpapi_location: str | None = None if remote else location or None
        localised_query = localise_query(query)
        return search_jobs(localised_query, num_results=max_results, gl=gl, location=serpapi_location)
