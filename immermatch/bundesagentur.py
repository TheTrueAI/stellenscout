"""Bundesagentur für Arbeit job-search provider.

Accesses the free, public REST API of Germany's Federal Employment Agency
to search the largest verified job database in the country.

Search uses the ``/pc/v4/jobs`` JSON API (X-API-Key auth).  Full job
descriptions are extracted from the server-side-rendered public detail
pages (``arbeitsagentur.de/jobsuche/jobdetail/{refnr}``) where Angular
embeds a ``<script id="ng-state">`` JSON blob containing the complete
listing data.

API docs: https://jobsuche.api.bund.dev/
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

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
_DEFAULT_DAYS_PUBLISHED = 28

# Retry settings for transient server errors.
_MAX_RETRIES = 3
_BASE_DELAY = 2  # seconds
_MAX_PAGES = 100
_BACKOFF_JITTER = 0.5

# Regex to extract the Angular SSR state from the detail page.
_NG_STATE_RE = re.compile(
    r'<script\s+id="ng-state"\s+type="application/json">(.*?)</script>',
    re.DOTALL,
)


def _build_ba_link(refnr: str) -> str:
    """Construct the public Arbeitsagentur URL for a listing."""
    return f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"


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


def _clean_html(raw: str) -> str:
    """Strip HTML tags and decode entities, collapse whitespace."""
    text = html_mod.unescape(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------------------
# Detail page scraping
# ------------------------------------------------------------------


def _fetch_detail(client: httpx.Client, refnr: str) -> dict:
    """Fetch the public detail page and extract the ng-state JSON.

    Returns the ``jobdetail`` dict on success, or ``{}`` on any failure.
    """
    url = _build_ba_link(refnr)
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                match = _NG_STATE_RE.search(resp.text)
                if match:
                    state = json.loads(match.group(1))
                    return state.get("jobdetail", {})  # type: ignore[no-any-return]
                logger.debug("BA detail %s: ng-state not found in HTML", refnr)
                return {}
            if resp.status_code in {403, 429, 500, 502, 503}:
                delay = _BASE_DELAY * (2**attempt) + _BACKOFF_JITTER
                logger.warning(
                    "BA detail page %s returned %s, retrying in %ss",
                    refnr,
                    resp.status_code,
                    delay,
                )
                time.sleep(delay)
                continue
            logger.debug("BA detail page %s returned %s, skipping", refnr, resp.status_code)
            return {}
        except httpx.HTTPError as exc:
            last_exc = exc
            delay = _BASE_DELAY * (2**attempt) + _BACKOFF_JITTER
            logger.warning("BA detail %s network error: %s, retrying in %ss", refnr, exc, delay)
            time.sleep(delay)
    if last_exc:
        logger.error("BA detail %s failed after %d retries: %s", refnr, _MAX_RETRIES, last_exc)
    return {}


def _fetch_detail_api(client: httpx.Client, refnr: str) -> dict:
    """Fetch structured job detail JSON from the BA API using plain ``refnr``.

    Returns the detail dict on success, or ``{}`` on any failure.
    """
    url = f"{_BASE_URL}/pc/v4/jobdetails/{refnr}"
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, dict) else {}
            if resp.status_code in {403, 429, 500, 502, 503}:
                delay = _BASE_DELAY * (2**attempt) + _BACKOFF_JITTER
                logger.warning(
                    "BA API detail %s returned %s, retrying in %ss",
                    refnr,
                    resp.status_code,
                    delay,
                )
                time.sleep(delay)
                continue
            logger.debug("BA API detail %s returned %s, skipping", refnr, resp.status_code)
            return {}
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            delay = _BASE_DELAY * (2**attempt) + _BACKOFF_JITTER
            logger.warning("BA API detail %s error: %s, retrying in %ss", refnr, exc, delay)
            time.sleep(delay)
    if last_exc:
        logger.error("BA API detail %s failed after %d retries: %s", refnr, _MAX_RETRIES, last_exc)
    return {}


# ------------------------------------------------------------------
# Search result parsing
# ------------------------------------------------------------------


def _parse_listing(item: dict, detail: dict | None = None) -> JobListing | None:
    """Convert a search-result item (+ optional detail) into a :class:`JobListing`.

    Returns ``None`` when the item lacks a ``refnr`` (the unique job ID).
    """
    refnr = item.get("refnr", "")
    if not refnr:
        return None

    arbeitsort = item.get("arbeitsort", {})
    link = _build_ba_link(refnr)

    titel = item.get("titel", "")
    beruf = item.get("beruf", "")
    arbeitgeber = item.get("arbeitgeber", "")
    ort = _parse_location(arbeitsort)

    # Prefer the rich description from the detail page when available.
    description = ""
    if detail:
        raw_desc = detail.get("stellenangebotsBeschreibung", "")
        if raw_desc:
            description = _clean_html(raw_desc)

    # Fallback: build a minimal description from search fields.
    if not description:
        parts: list[str] = []
        if beruf and beruf != titel:
            parts.append(f"Beruf: {beruf}")
        if arbeitgeber:
            parts.append(f"Arbeitgeber: {arbeitgeber}")
        if ort:
            parts.append(f"Standort: {ort}")
        description = "\n".join(parts)

    # Build apply options — always include the Arbeitsagentur page link,
    # plus an external career-site link when available in the detail data.
    apply_options = [ApplyOption(source="Arbeitsagentur", url=link)]
    if detail:
        ext_url = str(detail.get("allianzpartnerUrl", "")).strip()
        if ext_url:
            if ext_url.startswith("//"):
                ext_url = f"https:{ext_url}"
            elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", ext_url):
                ext_url = f"https://{ext_url}"
            ext_name = detail.get("allianzpartnerName", "Company Website")
            apply_options.append(ApplyOption(source=ext_name, url=ext_url))

    return JobListing(
        title=titel or beruf or "Unknown",
        company_name=arbeitgeber or "Unknown",
        location=ort,
        description=description,
        link=link,
        posted_at=item.get("aktuelleVeroeffentlichungsdatum", ""),
        source="bundesagentur",
        apply_options=apply_options,
    )


def _parse_search_results(data: dict) -> list[dict]:
    """Return the raw search-result items (dicts) that have a ``refnr``."""
    return [item for item in data.get("stellenangebote", []) if item.get("refnr")]


class BundesagenturProvider:
    """Job-search provider backed by the Bundesagentur für Arbeit API.

    Satisfies the :class:`~immermatch.search_provider.SearchProvider` protocol.
    """

    name: str = "Bundesagentur für Arbeit"

    def __init__(
        self,
        days_published: int = _DEFAULT_DAYS_PUBLISHED,
        detail_workers: int = 5,
        detail_strategy: Literal["api_then_html", "api_only", "html_only"] = "api_then_html",
    ) -> None:
        self._days_published = days_published
        self._detail_workers = detail_workers
        self._detail_strategy = detail_strategy

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
            List of ``JobListing`` objects.  When possible, descriptions
            are scraped from the public detail pages; otherwise a minimal
            fallback description is built from the search data.
        """
        if not query or not query.strip():
            logger.debug("Skipping BA search: empty query")
            return []

        items = self._search_items(query, location, max_results)
        if not items:
            return []
        return self._enrich(items)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search_items(
        self,
        query: str,
        location: str,
        max_results: int,
    ) -> list[dict]:
        """Paginate through the search endpoint and collect raw items."""
        page_size = min(max_results, 50)  # BA allows up to 100, 50 is safe
        items: list[dict] = []
        page = 1  # BA API pages are 1-indexed

        with httpx.Client(headers=_DEFAULT_HEADERS, timeout=30) as client:
            while len(items) < max_results and page <= _MAX_PAGES:
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
                page_items = _parse_search_results(data)
                if not page_items:
                    break

                items.extend(page_items)
                total = int(data.get("maxErgebnisse", 0))
                if len(items) >= total or len(items) >= max_results:
                    break

                page += 1

        if page > _MAX_PAGES and len(items) < max_results:
            logger.warning("Reached BA page cap (%s) while searching query=%r", _MAX_PAGES, query)

        return items[:max_results]

    def _enrich(self, items: list[dict]) -> list[JobListing]:
        """Fetch detail pages in parallel and build ``JobListing`` objects."""
        # Map refnr → detail dict (fetched in parallel).
        details: dict[str, dict] = {}
        with (
            httpx.Client(headers=_DEFAULT_HEADERS, timeout=30) as api_client,
            httpx.Client(
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Immermatch/1.0)",
                    "Accept": "text/html",
                },
                follow_redirects=True,
            ) as html_client,
        ):
            with ThreadPoolExecutor(max_workers=self._detail_workers) as pool:
                future_to_refnr = {
                    pool.submit(self._get_detail, api_client, html_client, item["refnr"]): item["refnr"]
                    for item in items
                }
                for future in as_completed(future_to_refnr):
                    refnr = future_to_refnr[future]
                    try:
                        details[refnr] = future.result()
                    except Exception:
                        logger.exception("Failed to fetch detail for %s", refnr)
                        details[refnr] = {}

        listings: list[JobListing] = []
        for item in items:
            refnr = item["refnr"]
            listing = _parse_listing(item, detail=details.get(refnr))
            if listing is not None:
                listings.append(listing)
        return listings

    def _get_detail(self, api_client: httpx.Client, html_client: httpx.Client, refnr: str) -> dict:
        """Resolve job detail using the configured endpoint strategy."""
        if self._detail_strategy == "api_only":
            return _fetch_detail_api(api_client, refnr)
        if self._detail_strategy == "html_only":
            return _fetch_detail(html_client, refnr)

        detail = _fetch_detail_api(api_client, refnr)
        if detail:
            return detail
        return _fetch_detail(html_client, refnr)

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
                if resp.status_code in {403, 429, 500, 502, 503}:
                    delay = _BASE_DELAY * (2**attempt) + _BACKOFF_JITTER
                    logger.warning("BA search %s returned %s, retry in %ss", url, resp.status_code, delay)
                    time.sleep(delay)
                    continue
                logger.warning("BA search %s returned %s, giving up", url, resp.status_code)
                return None
            except httpx.HTTPError as exc:
                last_exc = exc
                delay = _BASE_DELAY * (2**attempt) + _BACKOFF_JITTER
                logger.warning("BA search network error: %s, retry in %ss", exc, delay)
                time.sleep(delay)
        if last_exc:
            logger.error("BA search failed after %d retries: %s", _MAX_RETRIES, last_exc)
        return None
