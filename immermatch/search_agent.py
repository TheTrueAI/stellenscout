"""Search Agent module - Generates optimized job search queries using LLM."""

import os
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from pydantic import ValidationError
from serpapi import GoogleSearch

from .llm import call_gemini, parse_json
from .models import ApplyOption, CandidateProfile, JobListing

# Questionable job portals that often have expired listings or paywalls
_BLOCKED_PORTALS = {
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

# Map country/city names to Google gl= codes so SerpApi doesn't default to "us"
_GL_CODES: dict[str, str] = {
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


# Tokens that signal a purely remote / worldwide search (no single country).
_REMOTE_TOKENS = {"remote", "worldwide", "global", "anywhere", "weltweit"}


def _is_remote_only(location: str) -> bool:
    """Return True when the location string contains ONLY remote-like tokens."""
    words = {re.sub(r"[^\w]", "", w).lower() for w in location.split() if w.strip()}
    return bool(words) and words <= _REMOTE_TOKENS


def _infer_gl(location: str) -> str | None:
    """Infer a Google gl= country code from a free-form location string.

    Returns *None* for purely remote/global searches so CallerCode can
    decide whether to set ``gl`` at all (SerpApi defaults to "us").
    Falls back to "de" when a location is given but no country can be
    determined, since SerpApi defaults to "us" otherwise and returns
    0 European results.
    """
    if _is_remote_only(location):
        return None

    loc_lower = location.lower()
    for name, code in _GL_CODES.items():
        if name in loc_lower:
            return code
    return "de"


# English city names → local names used by Google Jobs.
# Google Jobs with gl=de returns 0 results for "Munich" but 30 for "München".
_CITY_LOCALISE: dict[str, str] = {
    # German
    "munich": "München",
    "cologne": "Köln",
    "nuremberg": "Nürnberg",
    "hanover": "Hannover",
    "dusseldorf": "Düsseldorf",
    # Austrian
    "vienna": "Wien",
    # Swiss
    "zurich": "Zürich",
    "geneva": "Genève",
    # Czech
    "prague": "Praha",
    # Polish
    "warsaw": "Warszawa",
    "krakow": "Kraków",
    "wroclaw": "Wrocław",
    # Danish
    "copenhagen": "København",
    # Greek
    "athens": "Athína",
    # Romanian
    "bucharest": "București",
    # Italian
    "milan": "Milano",
    "rome": "Roma",
    # Portuguese
    "lisbon": "Lisboa",
    # Belgian
    "brussels": "Bruxelles",
    "antwerp": "Antwerpen",
    # Swedish
    "gothenburg": "Göteborg",
}

# English country names → local names for search queries.
_COUNTRY_LOCALISE: dict[str, str] = {
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

# Build a case-insensitive regex that matches any English city name as a whole word
_LOCALISE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _CITY_LOCALISE) + r")\b",
    re.IGNORECASE,
)

# Same for country names (longer keys first so "czech republic" beats "czech")
_COUNTRY_LOCALISE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_COUNTRY_LOCALISE, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _localise_query(query: str) -> str:
    """Replace English city and country names with their local equivalents."""
    query = _LOCALISE_PATTERN.sub(lambda m: _CITY_LOCALISE[m.group(0).lower()], query)
    query = _COUNTRY_LOCALISE_PATTERN.sub(lambda m: _COUNTRY_LOCALISE[m.group(0).lower()], query)
    return query


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
) -> list[str]:
    """
    Generate optimized job search queries based on candidate profile.

    Args:
        client: Gemini client instance.
        profile: Structured candidate profile.
        location: Target job location.

    Returns:
        List of search query strings.
    """
    profile_text = f"""Candidate Profile:
- Skills: {", ".join(profile.skills)}
- Experience Level: {profile.experience_level}
- Target Roles: {", ".join(profile.roles)}
- Languages: {", ".join(profile.languages)}
- Domain Expertise: {", ".join(profile.domain_expertise)}
- Target Location: {location}"""

    prompt = f"{HEADHUNTER_SYSTEM_PROMPT}\n\nGenerate exactly {num_queries} queries.\n\n{profile_text}"

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


def _parse_job_results(results: dict) -> list[JobListing]:
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

        # Extract apply options (LinkedIn, company website, etc.)
        # Filter out questionable job portals
        apply_options = []
        for option in job_data.get("apply_options", []):
            if "title" in option and "link" in option:
                url = option["link"].lower()
                # Skip if the URL contains any blocked portal domain
                if not any(blocked in url for blocked in _BLOCKED_PORTALS):
                    apply_options.append(ApplyOption(source=option["title"], url=option["link"]))

        # Skip jobs that only have questionable portal links or no links at all
        if not apply_options:
            continue

        job = JobListing(
            title=job_data.get("title", "Unknown"),
            company_name=job_data.get("company_name", "Unknown"),
            location=job_data.get("location", "Unknown"),
            description="\n".join(description_parts),
            link=job_data.get("share_link", job_data.get("link", "")),
            posted_at=job_data.get("detected_extensions", {}).get("posted_at", ""),
            apply_options=apply_options,
        )
        jobs.append(job)

    return jobs


def search_jobs(
    query: str,
    num_results: int = 10,
    gl: str | None = "de",
    location: str | None = None,
) -> list[JobListing]:
    """
    Search for jobs using SerpApi Google Jobs engine with pagination.

    Args:
        query: Search query string.
        num_results: Maximum number of results to return.
        gl: Google country code (e.g. "de", "fr"). *None* to omit.
        location: SerpApi ``location`` parameter for geographic filtering
            (e.g. "Germany", "Munich, Bavaria, Germany"). *None* to omit.

    Returns:
        List of job listings.
    """
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        raise ValueError("SERPAPI_KEY environment variable not set")

    all_jobs: list[JobListing] = []
    next_page_token = None

    while len(all_jobs) < num_results:
        params: dict[str, str] = {
            "engine": "google_jobs",
            "q": query,
            "hl": "en",  # English results
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

        page_jobs = _parse_job_results(results)
        if not page_jobs:
            break

        all_jobs.extend(page_jobs)

        # Check for next page
        pagination = results.get("serpapi_pagination", {})
        next_page_token = pagination.get("next_page_token")
        if not next_page_token:
            break

    return all_jobs[:num_results]


def search_all_queries(
    queries: list[str],
    jobs_per_query: int = 10,
    location: str = "",
    min_unique_jobs: int = 50,
    on_progress: "None | Callable" = None,
    on_jobs_found: "None | Callable[[list[JobListing]], None]" = None,
) -> list[JobListing]:
    """
    Search for jobs across multiple queries and deduplicate results.
    Queries without a location keyword get the location appended automatically,
    since Google Jobs returns nothing without geographic context.

    Stops early once *min_unique_jobs* unique listings have been collected,
    saving SerpAPI calls for candidates in active markets.

    Args:
        queries: List of search queries.
        jobs_per_query: Number of jobs to fetch per query.
        location: Target location to append to queries missing one.
        min_unique_jobs: Stop after collecting this many unique jobs (0 to disable).
        on_progress: Optional callback(completed_count, total_queries, unique_jobs_count)
            invoked after each query completes. Because queries run in
            parallel, completed_count reflects finish order, not the
            original query index.
        on_jobs_found: Optional callback(new_unique_jobs) invoked with each batch
            of newly discovered unique jobs as soon as a query completes.
            Enables the caller to start processing (e.g. evaluating) jobs before
            all searches finish.

    Returns:
        Deduplicated list of job listings.
    """
    # Translate English city/country names to local names (e.g. Munich → München)
    local_location = _localise_query(location)
    remote_search = _is_remote_only(location)

    # Build location keywords from BOTH original and localised forms
    _location_words = set()
    for loc in (location, local_location):
        for w in loc.split():
            cleaned = re.sub(r"[^\w]", "", w).lower()
            if len(cleaned) >= 3:
                _location_words.add(cleaned)
    _location_words.add("remote")

    # Infer Google country code for localisation (None for remote-only)
    gl = _infer_gl(location)

    # Determine SerpApi `location` param for geographic filtering.
    # For remote searches we omit it; for everything else we pass the
    # raw user-supplied string which SerpApi resolves to its geo DB.
    serpapi_location: str | None = None if remote_search else location or None

    all_jobs: dict[str, JobListing] = {}  # Use title+company as key for dedup
    lock = threading.Lock()
    completed = 0
    early_stop = threading.Event()

    # Prepare all search queries upfront (localisation, location append)
    prepared_queries: list[str] = []
    for query in queries:
        query_lower = query.lower()
        has_location = any(kw in query_lower for kw in _location_words)
        search_query = query if has_location else f"{query} {local_location}"
        search_query = _localise_query(search_query)
        prepared_queries.append(search_query)

    def _search_one(search_query: str) -> list[JobListing]:
        if early_stop.is_set():
            return []
        return search_jobs(
            search_query,
            num_results=jobs_per_query,
            gl=gl,
            location=serpapi_location,
        )

    with ThreadPoolExecutor(max_workers=min(5, max(1, len(prepared_queries)))) as executor:
        futures = [executor.submit(_search_one, sq) for sq in prepared_queries]
        for future in as_completed(futures):
            jobs = future.result()
            batch_new: list[JobListing] = []
            with lock:
                for job in jobs:
                    key = f"{job.title}|{job.company_name}"
                    if key not in all_jobs:
                        all_jobs[key] = job
                        batch_new.append(job)
                completed += 1
                progress_args = (completed, len(queries), len(all_jobs))
                if min_unique_jobs and len(all_jobs) >= min_unique_jobs:
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

    return list(all_jobs.values())
