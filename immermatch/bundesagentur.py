"""Bundesagentur für Arbeit job-search provider.

Accesses the free, public REST API of Germany's Federal Employment Agency
to search the largest verified job database in the country.

API docs: https://jobsuche.api.bund.dev/
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from .models import ApplyOption, JobListing

logger = logging.getLogger(__name__)

_BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
_API_KEY = "jobboerse-jobsuche"  # pragma: allowlist secret  # noqa: S105 — public API key, not a secret
_DEFAULT_HEADERS = {
    "X-API-Key": _API_KEY,
    "Accept": "application/json",
}

# How many days back to accept listings (keeps results fresh).
_DEFAULT_DAYS_PUBLISHED = 7

# Retry settings for transient server errors.
_MAX_RETRIES = 3
_BASE_DELAY = 2  # seconds


def _build_ba_link(hash_id: str) -> str:
    """Construct the public Arbeitsagentur URL for a listing."""
    return f"https://www.arbeitsagentur.de/jobsuche/suche?id={hash_id}"


def _parse_location(arbeitsort: dict) -> str:
    """Build a human-readable location string from the API's *arbeitsort*."""
    parts: list[str] = []
    if ort := arbeitsort.get("ort"):
        parts.append(ort)
    if region := arbeitsort.get("region"):
        # Avoid duplicating city name when region == city
        if region != ort:
            parts.append(region)
    if land := arbeitsort.get("land"):
        if land not in parts:
            parts.append(land)
    return ", ".join(parts) if parts else "Germany"


def _parse_search_results(data: dict) -> list[_JobStub]:
    """Parse the search endpoint response into lightweight stubs."""
    stubs: list[_JobStub] = []
    for item in data.get("stellenangebote", []):
        hash_id = item.get("hashId", "")
        if not hash_id:
            continue
        arbeitsort = item.get("arbeitsort", {})
        stubs.append(
            _JobStub(
                hash_id=hash_id,
                title=item.get("beruf", item.get("titel", "Unknown")),
                company_name=item.get("arbeitgeber", "Unknown"),
                location=_parse_location(arbeitsort),
                posted_at=item.get("aktuelleVeroeffentlichungsdatum", ""),
                refnr=item.get("refnr", ""),
            )
        )
    return stubs


class _JobStub:
    """Minimal data from the search endpoint before detail-fetching."""

    __slots__ = ("hash_id", "title", "company_name", "location", "posted_at", "refnr")

    def __init__(
        self,
        hash_id: str,
        title: str,
        company_name: str,
        location: str,
        posted_at: str,
        refnr: str,
    ) -> None:
        self.hash_id = hash_id
        self.title = title
        self.company_name = company_name
        self.location = location
        self.posted_at = posted_at
        self.refnr = refnr


def _fetch_job_details(client: httpx.Client, hash_id: str) -> dict:
    """Fetch full job details for a single listing (with retry)."""
    url = f"{_BASE_URL}/pc/v2/jobdetails/{hash_id}"
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.json()  # type: ignore[no-any-return]
            if resp.status_code in {429, 500, 502, 503}:
                delay = _BASE_DELAY * (2**attempt)
                logger.warning("BA detail %s returned %s, retrying in %ss", hash_id, resp.status_code, delay)
                time.sleep(delay)
                continue
            # 404 or other client error → give up immediately
            logger.debug("BA detail %s returned %s, skipping", hash_id, resp.status_code)
            return {}
        except httpx.HTTPError as exc:
            last_exc = exc
            delay = _BASE_DELAY * (2**attempt)
            logger.warning("BA detail %s network error: %s, retrying in %ss", hash_id, exc, delay)
            time.sleep(delay)
    if last_exc:
        logger.error("BA detail %s failed after %d retries: %s", hash_id, _MAX_RETRIES, last_exc)
    return {}


def _stub_to_listing(stub: _JobStub, details: dict) -> JobListing:
    """Merge a search stub with its full details into a ``JobListing``."""
    description = details.get("stellenbeschreibung", "")
    link = _build_ba_link(stub.hash_id)

    apply_options = [ApplyOption(source="Arbeitsagentur", url=link)]
    if external_url := details.get("allianzPartnerUrl"):
        apply_options.append(ApplyOption(source="Company Website", url=external_url))

    # Prefer the more specific title from details when available
    title = details.get("titel", stub.title) or stub.title
    company = details.get("arbeitgeber", stub.company_name) or stub.company_name

    return JobListing(
        title=title,
        company_name=company,
        location=stub.location,
        description=description,
        link=link,
        posted_at=stub.posted_at,
        source="bundesagentur",
        apply_options=apply_options,
    )


class BundesagenturProvider:
    """Job-search provider backed by the Bundesagentur für Arbeit API.

    Satisfies the :class:`~immermatch.search_provider.SearchProvider` protocol.
    """

    name: str = "Bundesagentur für Arbeit"

    def __init__(
        self,
        days_published: int = _DEFAULT_DAYS_PUBLISHED,
        detail_workers: int = 10,
    ) -> None:
        self._days_published = days_published
        self._detail_workers = detail_workers

    # ------------------------------------------------------------------
    # Public API (SearchProvider protocol)
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        location: str,
        max_results: int = 50,
    ) -> list[JobListing]:
        """Search for jobs and return listings with full descriptions.

        Args:
            query: Free-text keyword (job title, skill, …).
            location: City / region in Germany.
            max_results: Upper bound on total results.

        Returns:
            List of ``JobListing`` objects with descriptions fetched from
            the detail endpoint.
        """
        stubs = self._search_stubs(query, location, max_results)
        if not stubs:
            return []
        return self._enrich_stubs(stubs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search_stubs(
        self,
        query: str,
        location: str,
        max_results: int,
    ) -> list[_JobStub]:
        """Paginate through the search endpoint and collect stubs."""
        page_size = min(max_results, 50)  # BA allows up to 100, 50 is safe
        stubs: list[_JobStub] = []
        page = 0

        with httpx.Client(headers=_DEFAULT_HEADERS, timeout=30) as client:
            while len(stubs) < max_results:
                params: dict[str, str | int] = {
                    "was": query,
                    "size": page_size,
                    "page": page,
                    "veroeffentlichtseit": self._days_published,
                    "angebotsart": 1,  # jobs only (not self-employed / training)
                }
                if location.strip():
                    params["wo"] = location

                resp = self._get_with_retry(client, f"{_BASE_URL}/pc/v4/jobs", params)
                if resp is None:
                    break

                data = resp.json()
                page_stubs = _parse_search_results(data)
                if not page_stubs:
                    break

                stubs.extend(page_stubs)
                total = int(data.get("maxErgebnisse", 0))
                if len(stubs) >= total or len(stubs) >= max_results:
                    break

                page += 1

        return stubs[:max_results]

    def _enrich_stubs(self, stubs: list[_JobStub]) -> list[JobListing]:
        """Batch-fetch full details and convert stubs to listings."""
        listings: list[JobListing] = []

        with httpx.Client(headers=_DEFAULT_HEADERS, timeout=30) as client:
            with ThreadPoolExecutor(max_workers=self._detail_workers) as pool:
                future_to_stub = {pool.submit(_fetch_job_details, client, stub.hash_id): stub for stub in stubs}
                for future in as_completed(future_to_stub):
                    stub = future_to_stub[future]
                    try:
                        details = future.result()
                    except Exception:
                        logger.exception("Failed to fetch details for %s", stub.hash_id)
                        details = {}
                    listings.append(_stub_to_listing(stub, details))

        return listings

    @staticmethod
    def _get_with_retry(
        client: httpx.Client,
        url: str,
        params: dict,
    ) -> httpx.Response | None:
        """GET with retry on transient errors."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    return resp
                if resp.status_code in {429, 500, 502, 503}:
                    delay = _BASE_DELAY * (2**attempt)
                    logger.warning("BA search %s returned %s, retry in %ss", url, resp.status_code, delay)
                    time.sleep(delay)
                    continue
                logger.warning("BA search %s returned %s, giving up", url, resp.status_code)
                return None
            except httpx.HTTPError as exc:
                last_exc = exc
                delay = _BASE_DELAY * (2**attempt)
                logger.warning("BA search network error: %s, retry in %ss", exc, delay)
                time.sleep(delay)
        if last_exc:
            logger.error("BA search failed after %d retries: %s", _MAX_RETRIES, last_exc)
        return None
