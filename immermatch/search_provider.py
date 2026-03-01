"""Abstract search-provider interface and provider factory.

Every job-search backend (Bundesagentur für Arbeit, SerpApi, …) implements
the ``SearchProvider`` protocol so the rest of the pipeline can be
search-engine-agnostic.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from .models import JobListing

logger = logging.getLogger(__name__)


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


def get_provider(location: str = "") -> SearchProvider:  # noqa: ARG001
    """Return the appropriate ``SearchProvider`` for *location*.

    Currently always returns the Bundesagentur für Arbeit provider
    (Germany-only).  This factory is the single extension point for
    future per-country routing — e.g. returning ``SerpApiProvider``
    for non-German locations.
    """
    # Lazy import so the module can be loaded without pulling in httpx
    # when only the protocol is needed (e.g. for type-checking).
    from .bundesagentur import BundesagenturProvider  # noqa: PLC0415

    return BundesagenturProvider()
