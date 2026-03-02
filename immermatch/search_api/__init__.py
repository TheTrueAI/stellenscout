"""Search API domain package.

Canonical location for search provider implementations and orchestration.
"""

from .bundesagentur import BundesagenturProvider
from .search_agent import (
    BA_HEADHUNTER_SYSTEM_PROMPT,
    HEADHUNTER_SYSTEM_PROMPT,
    PROFILER_SYSTEM_PROMPT,
    generate_search_queries,
    profile_candidate,
    search_all_queries,
)
from .search_provider import CombinedSearchProvider, SearchProvider, get_provider
from .serpapi_provider import SerpApiProvider

__all__ = [
    "BA_HEADHUNTER_SYSTEM_PROMPT",
    "BundesagenturProvider",
    "CombinedSearchProvider",
    "HEADHUNTER_SYSTEM_PROMPT",
    "PROFILER_SYSTEM_PROMPT",
    "SearchProvider",
    "SerpApiProvider",
    "generate_search_queries",
    "get_provider",
    "profile_candidate",
    "search_all_queries",
]
