"""Search Agent module - Generates optimized job search queries using LLM.

The SerpApi-specific helpers (``_infer_gl``, ``_localise_query``, etc.) live
in :mod:`immermatch.serpapi_provider` and are re-exported here for backward
compatibility.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from pydantic import ValidationError

from .llm import call_gemini, parse_json
from .models import CandidateProfile, JobListing
from .search_provider import CombinedSearchProvider, SearchProvider, get_provider, parse_provider_query

# Re-export SerpApi helpers so existing imports keep working.
from .serpapi_provider import BLOCKED_PORTALS as _BLOCKED_PORTALS  # noqa: F401
from .serpapi_provider import CITY_LOCALISE as _CITY_LOCALISE  # noqa: F401
from .serpapi_provider import COUNTRY_LOCALISE as _COUNTRY_LOCALISE  # noqa: F401
from .serpapi_provider import GL_CODES as _GL_CODES  # noqa: F401
from .serpapi_provider import infer_gl as _infer_gl  # noqa: F401
from .serpapi_provider import is_remote_only as _is_remote_only  # noqa: F401
from .serpapi_provider import localise_query as _localise_query  # noqa: F401
from .serpapi_provider import parse_job_results as _parse_job_results  # noqa: F401
from .serpapi_provider import search_jobs  # noqa: F401

logger = logging.getLogger(__name__)
_MIN_JOBS_PER_PROVIDER = 30


def _provider_quota_source_key(provider: SearchProvider) -> str:
    """Return a stable source key for per-provider quota accounting."""
    source_id = getattr(provider, "source_id", None)
    if isinstance(source_id, str) and source_id.strip():
        return source_id.strip().lower()
    if getattr(provider, "name", None) == "Bundesagentur für Arbeit":
        return "bundesagentur"
    return type(provider).__name__.lower()


# System prompt for the Profiler agent
PROFILER_SYSTEM_PROMPT = """You are an expert technical recruiter with deep knowledge of European job markets.
You will be given the raw text of a candidate's CV. Extract a comprehensive profile.

Be THOROUGH — capture everything relevant. Do not summarize away important details.
Pay special attention to DATES and DURATIONS for each role and degree.

Return a JSON object with:
- "skills": List of ALL hard skills, tools, frameworks, methodologies, and technical competencies mentioned. Include specific tools (e.g., "SAP", "Power BI"), standards (e.g., "ISO 14064", "GHG Protocol"), and methods. Aim for 15-20 items.
- "experience_level": One of "Junior" (<2 years), "Mid" (2-5 years), "Senior" (5-10 years), "Lead" (10+ years), "CTO".
- "years_of_experience": (int) Total years of professional experience. Calculate from work history dates.
- "roles": List of 5 job titles the candidate is suited for, ordered from most to least specific. Include both English and local-language titles where relevant.
- "languages": List of spoken languages with proficiency level (e.g., "German B2", "English Native", "French C1").
- "domain_expertise": List of all industries and domains the candidate has worked in.
- "certifications": List of professional certifications, accreditations, or licenses (e.g., "PMP", "AWS Solutions Architect"). Empty list if none.
- "education": List of degrees with field of study (e.g., "MSc Environmental Engineering", "BSc Computer Science"). Include the university name if mentioned.
- "summary": A 2-3 sentence professional summary describing the candidate's core strengths and career trajectory.
- "work_history": Array of work-experience objects, ordered MOST RECENT FIRST. Each object has:
  - "title": (string) Job title held.
  - "company": (string) Employer name.
  - "start_date": (string) e.g. "2020-03" or "2020". Use the best precision available.
  - "end_date": (string or null) null means this is the CURRENT role.
  - "duration_months": (int or null) Estimated duration in months. Calculate from dates; if dates are vague, estimate.
  - "skills_used": (list of strings) Key skills, tools, and technologies used in THIS specific role.
  - "description": (string) One-sentence summary of responsibilities/achievements.
- "education_history": Array of education objects. Each object has:
  - "degree": (string) e.g. "MSc Computer Science".
  - "institution": (string) University or school name.
  - "start_date": (string or null) Start date if available.
  - "end_date": (string or null) Graduation date, or null if still studying.
  - "status": One of "completed", "in_progress", "dropped". If the CV says "expected 2026" or has no graduation date and appears current, use "in_progress".

Be precise about dates:
- If the CV says "2020 – present", set end_date to null.
- If it says "2018 – 2020", estimate duration_months (e.g. 24).
- For education, mark degrees without a graduation date or with "expected" as "in_progress".

Return ONLY valid JSON, no markdown or explanation."""

# System prompt for the Headhunter agent
HEADHUNTER_SYSTEM_PROMPT = """You are a Search Specialist. Based on the candidate's profile and location, generate 20 distinct search queries to find relevant job openings.

IMPORTANT: Keep queries SHORT and SIMPLE (1-3 words). Google Jobs works best with simple, broad queries.

CRITICAL: Always use LOCAL names, not English ones. For example use "München" not "Munich", "Köln" not "Cologne", "Wien" not "Vienna", "Zürich" not "Zurich", "Praha" not "Prague", "Deutschland" not "Germany".

**Adapt your strategy to the SCOPE of the Target Location:**

A) If the location is a CITY (e.g. "München", "Amsterdam"):
   1. Queries 1-5: Exact role titles + local city name
   2. Queries 6-10: Broader role synonyms + city
   3. Queries 11-15: Industry/domain keywords without city or with "remote"
   4. Queries 16-20: Very broad industry terms

B) If the location is a COUNTRY (e.g. "Germany", "Netherlands"):
   1. Queries 1-5: Exact role titles + local country name (e.g. "Data Engineer Deutschland")
   2. Queries 6-10: Same roles + major cities in that country (e.g. "Backend Developer München", "Backend Developer Berlin")
   3. Queries 11-15: Broader role synonyms + country or "remote"
   4. Queries 16-20: Very broad industry terms

C) If the location is "remote", "worldwide", or similar:
   1. Queries 1-10: Exact role titles + "remote" (e.g. "Data Engineer remote")
   2. Queries 11-15: Broader role synonyms + "remote"
   3. Queries 16-20: Very broad industry terms without any location

Additional strategy:
- Include BOTH English and local-language job titles for the target country
- Use different synonyms for the same role (e.g., "Manager", "Lead", "Specialist", "Analyst")

Return ONLY a JSON array of 20 search query strings, no explanation."""

# System prompt for keyword-only queries used with Bundesagentur für Arbeit API.
# The BA API has a dedicated ``wo`` (where) parameter, so queries must NOT
# contain any location tokens.
BA_HEADHUNTER_SYSTEM_PROMPT = """You are a Search Specialist generating keyword queries for the German Federal Employment Agency job search API (Bundesagentur für Arbeit).

Based on the candidate's profile, generate distinct keyword queries to find relevant job openings. The API searches across German job listings and handles location filtering separately.

IMPORTANT RULES:
- Queries must be SHORT: 1-3 words ONLY
- Do NOT include any city, region, or country names — location is handled by the API
- Do NOT include "remote", "hybrid", or similar work-mode keywords
- Include BOTH German and English job titles (the API indexes both)
- Use different synonyms for the same role

Strategy:
1. First third: Exact role titles in German (e.g., "Softwareentwickler", "Datenanalyst", "Projektleiter")
2. Second third: Exact role titles in English (e.g., "Software Developer", "Data Analyst", "Project Manager")
3. Final third: Technology + role combinations and broader terms (e.g., "Python Entwickler", "Machine Learning", "DevOps Engineer")

Return ONLY a JSON array of search query strings, no explanation."""


def profile_candidate(client: genai.Client, cv_text: str) -> CandidateProfile:
    """
    Analyze CV text and extract a structured profile.

    Args:
        client: Gemini client instance.
        cv_text: Raw text extracted from CV.

    Returns:
        Structured candidate profile
    """
    prompt = f"{PROFILER_SYSTEM_PROMPT}\n\nExtract the profile from this CV:\n\n{cv_text}"
    recovery_suffix = """

IMPORTANT OUTPUT RULES:
- Return ONLY valid JSON (no markdown, no prose).
- Include ALL required top-level fields exactly once.
- Keep text concise to avoid truncation:
  - summary: 2-3 short sentences
  - each work_history.description: one short sentence (<= 25 words)
"""

    last_error: Exception | None = None

    for attempt in range(3):
        content = call_gemini(client, prompt, temperature=0.3, max_tokens=8192)

        try:
            data = parse_json(content)
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object for profile")
            return CandidateProfile(**data)
        except (ValueError, ValidationError, TypeError) as exc:
            last_error = exc
            if attempt == 2:
                break
            prompt = (
                f"{PROFILER_SYSTEM_PROMPT}\n\n"
                "Your previous response was invalid or incomplete JSON. "
                "Re-generate the FULL profile from this CV as one valid JSON object.\n\n"
                f"{cv_text}"
                f"{recovery_suffix}"
            )

    raise ValueError(f"Failed to generate a valid candidate profile JSON: {last_error}")


def generate_search_queries(
    client: genai.Client,
    profile: CandidateProfile,
    location: str = "",
    num_queries: int = 20,
    *,
    provider: SearchProvider | None = None,
) -> list[str]:
    """Generate optimized job search queries based on candidate profile.

    When a :class:`~immermatch.bundesagentur.BundesagenturProvider` is active
    the prompt asks the LLM for short keyword-only queries (no location
    tokens).  For SerpApi / Google Jobs the prompt includes location-enrichment
    strategies.

    Args:
        client: Gemini client instance.
        profile: Structured candidate profile.
        location: Target job location.
        num_queries: Number of queries to generate.
        provider: Explicit provider; defaults to ``get_provider(location)``.

    Returns:
        List of search query strings.
    """
    if provider is None:
        provider = get_provider(location)

    if isinstance(provider, CombinedSearchProvider):
        provider_count = len(provider.providers)
        if provider_count == 0:
            return []

        per_provider = num_queries // provider_count
        remainder = num_queries % provider_count
        merged_queries: list[str] = []

        for index, child_provider in enumerate(provider.providers):
            child_count = per_provider + (1 if index < remainder else 0)
            if child_count <= 0:
                continue
            child_queries = _generate_search_queries_for_provider(
                client,
                profile,
                location,
                child_count,
                child_provider,
            )
            merged_queries.extend([f"provider={child_provider.name}::{query}" for query in child_queries])

        seen: set[str] = set()
        unique_queries: list[str] = []
        for query in merged_queries:
            if query in seen:
                continue
            seen.add(query)
            unique_queries.append(query)
            if len(unique_queries) >= num_queries:
                break
        return unique_queries

    return _generate_search_queries_for_provider(client, profile, location, num_queries, provider)


def _generate_search_queries_for_provider(
    client: genai.Client,
    profile: CandidateProfile,
    location: str,
    num_queries: int,
    provider: SearchProvider,
) -> list[str]:
    # Select system prompt based on active provider
    if provider.name == "Bundesagentur für Arbeit":
        system_prompt = BA_HEADHUNTER_SYSTEM_PROMPT
    else:
        system_prompt = HEADHUNTER_SYSTEM_PROMPT

    profile_text = f"""Candidate Profile:
- Skills: {", ".join(profile.skills)}
- Experience Level: {profile.experience_level}
- Target Roles: {", ".join(profile.roles)}
- Languages: {", ".join(profile.languages)}
- Domain Expertise: {", ".join(profile.domain_expertise)}
- Target Location: {location}"""

    prompt = f"{system_prompt}\n\nGenerate exactly {num_queries} queries.\n\n{profile_text}"

    retry_prompt = (
        f"{prompt}\n\nIMPORTANT: Return ONLY a valid JSON array of strings with exactly {num_queries} queries."
    )

    for attempt in range(2):
        content = call_gemini(client, prompt if attempt == 0 else retry_prompt, temperature=0.5, max_tokens=8192)
        try:
            queries = parse_json(content)
        except ValueError:
            continue

        if isinstance(queries, list):
            return queries[:num_queries]

    return []


def search_all_queries(
    queries: list[str],
    jobs_per_query: int = 10,
    location: str = "",
    min_unique_jobs: int = 50,
    on_progress: None | Callable = None,
    on_jobs_found: None | Callable[[list[JobListing]], None] = None,
    *,
    provider: SearchProvider | None = None,
) -> list[JobListing]:
    """Search for jobs across multiple queries and deduplicate results.

    Each query is forwarded to the active :class:`SearchProvider` which handles
    location filtering, API-specific localisation, and pagination internally.

    Stops early once *min_unique_jobs* unique listings have been collected.

    Args:
        queries: List of search queries (keywords).
        jobs_per_query: Number of jobs to fetch per query.
        location: Target location passed to the provider.
        min_unique_jobs: Stop after collecting this many unique jobs (0 to disable).
        on_progress: Optional callback(completed_count, total_queries, unique_jobs_count)
            invoked after each query completes.  Because queries run in
            parallel, completed_count reflects finish order, not the
            original query index.
        on_jobs_found: Optional callback(new_unique_jobs) invoked with each batch
            of newly discovered unique jobs as soon as a query completes.
            Enables the caller to start processing (e.g. evaluating) jobs before
            all searches finish.
        provider: Explicit provider instance; defaults to ``get_provider(location)``.

    Returns:
        Deduplicated list of job listings.
    """
    if provider is None:
        provider = get_provider(location)

    quota_sources: set[str] = set()
    if isinstance(provider, CombinedSearchProvider):
        quota_sources = {_provider_quota_source_key(p) for p in provider.providers}
        if quota_sources and min_unique_jobs > 0:
            min_unique_jobs = max(min_unique_jobs, _MIN_JOBS_PER_PROVIDER * len(quota_sources))

    all_jobs: dict[str, JobListing] = {}  # Use title+company+location as key for dedup
    source_counts: dict[str, int] = {}
    lock = threading.Lock()
    completed = 0
    early_stop = threading.Event()

    def _search_one(query: str) -> list[JobListing]:
        if early_stop.is_set():
            return []
        clean_query = query
        if not isinstance(provider, CombinedSearchProvider):
            _, clean_query = parse_provider_query(query)
        return provider.search(clean_query, location, max_results=jobs_per_query)

    with ThreadPoolExecutor(max_workers=min(5, max(1, len(queries)))) as executor:
        futures = [executor.submit(_search_one, q) for q in queries]
        for future in as_completed(futures):
            jobs: list[JobListing] = []
            try:
                jobs = future.result()
            except Exception:
                logger.exception("A search query failed")
            batch_new: list[JobListing] = []
            with lock:
                for job in jobs:
                    key = f"{job.title}|{job.company_name}|{job.location}"
                    if key not in all_jobs:
                        all_jobs[key] = job
                        batch_new.append(job)
                        source = (job.source or "unknown").lower()
                        source_counts[source] = source_counts.get(source, 0) + 1
                completed += 1
                progress_args = (completed, len(queries), len(all_jobs))
                quota_met = True
                if quota_sources:
                    quota_met = all(source_counts.get(source, 0) >= _MIN_JOBS_PER_PROVIDER for source in quota_sources)
                if min_unique_jobs and len(all_jobs) >= min_unique_jobs and quota_met:
                    early_stop.set()
            # Callbacks outside the lock to avoid blocking other threads
            if on_progress is not None:
                on_progress(*progress_args)
            if batch_new and on_jobs_found is not None:
                on_jobs_found(batch_new)
            # Cancel pending futures once we have enough unique jobs
            if early_stop.is_set():
                for f in futures:
                    if f is not future and not f.done():
                        f.cancel()
                break

    if source_counts:
        counts_text = ", ".join(f"{source}={count}" for source, count in sorted(source_counts.items()))
        logger.info("Search source counts for location '%s': %s", location or "(none)", counts_text)
        if quota_sources:
            missing = [
                source for source in sorted(quota_sources) if source_counts.get(source, 0) < _MIN_JOBS_PER_PROVIDER
            ]
            if missing:
                logger.warning(
                    "Provider quota not reached for location '%s': %s (required >= %d each)",
                    location or "(none)",
                    ", ".join(missing),
                    _MIN_JOBS_PER_PROVIDER,
                )

    return list(all_jobs.values())
