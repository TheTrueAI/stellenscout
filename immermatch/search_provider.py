"""Abstract search-provider interface and provider factory.

Every job-search backend (Bundesagentur für Arbeit, SerpApi, …) implements
the ``SearchProvider`` protocol so the rest of the pipeline can be
search-engine-agnostic.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Protocol, runtime_checkable

from .models import JobListing

logger = logging.getLogger(__name__)

_PROVIDER_QUERY_PREFIX = "provider="
_PROVIDER_QUERY_SEPARATOR = "::"


def format_provider_query(provider_name: str, query: str) -> str:
    """Format a query with explicit provider routing metadata."""
    return f"{_PROVIDER_QUERY_PREFIX}{provider_name}{_PROVIDER_QUERY_SEPARATOR}{query}"


def parse_provider_query(query: str) -> tuple[str | None, str]:
    """Parse an optionally provider-targeted query.

    Query format:
        provider=<provider name>::<actual query>

    Returns:
        (target_provider_name, clean_query)
    """
    if query.startswith(_PROVIDER_QUERY_PREFIX) and _PROVIDER_QUERY_SEPARATOR in query:
        meta, clean_query = query.split(_PROVIDER_QUERY_SEPARATOR, 1)
        target_provider = meta.removeprefix(_PROVIDER_QUERY_PREFIX).strip()
        if target_provider and clean_query.strip():
            return target_provider, clean_query.strip()
    return None, query


def get_provider_fingerprint(provider: SearchProvider) -> str:
    """Return a stable fingerprint for the active provider configuration.

    Used by query cache to avoid reusing provider-targeted query sets when
    provider configuration changes (e.g. SerpApi enabled/disabled).
    """

    def _provider_key(p: SearchProvider) -> str:
        source_id = getattr(p, "source_id", None)
        if isinstance(source_id, str) and source_id.strip():
            return source_id.strip().lower()
        name = getattr(p, "name", "")
        if isinstance(name, str) and name.strip():
            return name.strip().lower()
        return type(p).__name__.lower()

    providers = provider.providers if isinstance(provider, CombinedSearchProvider) else [provider]
    return "|".join(sorted({_provider_key(p) for p in providers}))


@runtime_checkable
class SearchProvider(Protocol):
    """Pluggable interface for job-search backends.

    Implementations must expose a ``name`` attribute and a ``search`` method
    that translate a keyword + location into a list of ``JobListing`` objects.
    """

    name: str
    """Human-readable provider name, e.g. ``"Bundesagentur für Arbeit"``."""

    def search(
        self,
        query: str,
        location: str,
        max_results: int = 50,
    ) -> list[JobListing]:
        """Run a single search and return parsed job listings.

        Args:
            query: Free-text keyword (job title, skill, …).
            location: Free-text target location (city, region, country).
            max_results: Upper bound on results to return.

        Returns:
            De-duplicated list of ``JobListing`` objects.
        """
        ...


class CombinedSearchProvider:
    """Run multiple providers for each query and merge their results."""

    name: str = "Bundesagentur + SerpApi"

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = providers

    def search(
        self,
        query: str,
        location: str,
        max_results: int = 50,
    ) -> list[JobListing]:
        if not self.providers:
            return []

        target_provider, clean_query = parse_provider_query(query)
        providers = self.providers
        if target_provider is not None:
            providers = [provider for provider in self.providers if provider.name == target_provider]
            if not providers:
                logger.warning(
                    "Unknown targeted provider '%s' in query, falling back to all providers", target_provider
                )
                providers = self.providers

        if not providers:
            return []

        if max_results <= 0:
            return []

        merged: dict[str, JobListing] = {}
        per_provider = max(1, math.ceil(max_results / len(providers)))
        for provider in providers:
            try:
                jobs = provider.search(clean_query, location, max_results=per_provider)
            except Exception:
                logger.exception("Provider '%s' failed for query '%s'", provider.name, clean_query)
                continue

            for job in jobs:
                key = f"{job.title}|{job.company_name}|{job.location}"
                if key not in merged:
                    merged[key] = job

        return list(merged.values())[:max_results]


def get_provider(location: str = "") -> SearchProvider:  # noqa: ARG001
    """Return the appropriate ``SearchProvider`` for *location*.

    Returns a combined provider that merges Bundesagentur and SerpApi
    results when ``SERPAPI_KEY`` is available. If SerpApi is not
    configured, falls back to Bundesagentur only.
    """
    # Lazy import so the module can be loaded without pulling in httpx
    # when only the protocol is needed (e.g. for type-checking).
    from .bundesagentur import BundesagenturProvider  # noqa: PLC0415
    from .serpapi_provider import SerpApiProvider  # noqa: PLC0415

    providers: list[SearchProvider] = [BundesagenturProvider()]
    if os.getenv("SERPAPI_KEY"):
        providers.append(SerpApiProvider())

    if len(providers) == 1:
        return providers[0]
    return CombinedSearchProvider(providers)
