"""Search Agent module - Generates optimized job search queries using LLM."""

import os
import re
from google import genai
from serpapi import GoogleSearch

from .models import CandidateProfile, JobListing, ApplyOption
from .llm import call_gemini, parse_json

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
    "germany": "de", "deutschland": "de",
    "france": "fr",
    "netherlands": "nl", "holland": "nl",
    "belgium": "be",
    "austria": "at", "österreich": "at",
    "switzerland": "ch", "schweiz": "ch", "suisse": "ch",
    "spain": "es", "españa": "es",
    "italy": "it", "italia": "it",
    "portugal": "pt",
    "poland": "pl", "polska": "pl",
    "sweden": "se", "sverige": "se",
    "norway": "no", "norge": "no",
    "denmark": "dk", "danmark": "dk",
    "finland": "fi", "suomi": "fi",
    "ireland": "ie",
    "czech republic": "cz", "czechia": "cz",
    "romania": "ro",
    "hungary": "hu",
    "greece": "gr",
    "luxembourg": "lu",
    "uk": "uk", "united kingdom": "uk", "england": "uk",
    # Major cities → country
    "berlin": "de", "munich": "de", "münchen": "de", "hamburg": "de",
    "frankfurt": "de", "stuttgart": "de", "düsseldorf": "de", "köln": "de",
    "cologne": "de", "hannover": "de", "nürnberg": "de", "nuremberg": "de",
    "leipzig": "de", "dresden": "de", "dortmund": "de", "essen": "de",
    "bremen": "de",
    "paris": "fr", "lyon": "fr", "marseille": "fr", "toulouse": "fr",
    "amsterdam": "nl", "rotterdam": "nl", "eindhoven": "nl", "utrecht": "nl",
    "brussels": "be", "bruxelles": "be", "antwerp": "be",
    "vienna": "at", "wien": "at", "graz": "at",
    "zurich": "ch", "zürich": "ch", "geneva": "ch", "genève": "ch", "basel": "ch", "bern": "ch",
    "madrid": "es", "barcelona": "es",
    "rome": "it", "milan": "it", "milano": "it",
    "lisbon": "pt", "porto": "pt",
    "warsaw": "pl", "kraków": "pl", "krakow": "pl", "wrocław": "pl",
    "stockholm": "se", "gothenburg": "se", "malmö": "se",
    "oslo": "no",
    "copenhagen": "dk",
    "helsinki": "fi",
    "dublin": "ie",
    "prague": "cz",
    "bucharest": "ro",
    "budapest": "hu",
    "athens": "gr",
    "london": "uk", "manchester": "uk", "edinburgh": "uk",
}


def _infer_gl(location: str) -> str:
    """Infer a Google gl= country code from a free-form location string.

    Falls back to "de" (Germany) when no country can be determined,
    since SerpApi defaults to "us" otherwise and returns 0 European results.
    """
    loc_lower = location.lower()
    for name, code in _GL_CODES.items():
        if name in loc_lower:
            return code
    return "de"


# English city names → local names used by Google Jobs.
# Google Jobs with gl=de returns 0 results for "Munich" but 30 for "München".
_CITY_LOCALISE: dict[str, str] = {
    # German
    "munich": "München", "cologne": "Köln", "nuremberg": "Nürnberg",
    "hanover": "Hannover", "dusseldorf": "Düsseldorf",
    # Austrian
    "vienna": "Wien",
    # Swiss
    "zurich": "Zürich", "geneva": "Genève",
    # Czech
    "prague": "Praha",
    # Polish
    "warsaw": "Warszawa", "krakow": "Kraków", "wroclaw": "Wrocław",
    # Danish
    "copenhagen": "København",
    # Greek
    "athens": "Athína",
    # Romanian
    "bucharest": "București",
    # Italian
    "milan": "Milano", "rome": "Roma",
    # Portuguese
    "lisbon": "Lisboa",
    # Belgian
    "brussels": "Bruxelles",
    "antwerp": "Antwerpen",
    # Swedish
    "gothenburg": "Göteborg",
}

# Build a case-insensitive regex that matches any English city name as a whole word
_LOCALISE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _CITY_LOCALISE) + r")\b",
    re.IGNORECASE,
)


def _localise_query(query: str) -> str:
    """Replace English city names with their local equivalents in a query."""
    return _LOCALISE_PATTERN.sub(
        lambda m: _CITY_LOCALISE[m.group(0).lower()], query
    )

# System prompt for the Profiler agent
PROFILER_SYSTEM_PROMPT = """You are an expert technical recruiter with deep knowledge of European job markets.
You will be given the raw text of a candidate's CV. Extract a comprehensive profile.

Be THOROUGH — capture everything relevant. Do not summarize away important details.

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

Return ONLY valid JSON, no markdown or explanation."""

# System prompt for the Headhunter agent
HEADHUNTER_SYSTEM_PROMPT = """You are a Search Specialist. Based on the candidate's profile and location, generate 20 distinct search queries to find relevant job openings in Europe.

IMPORTANT: Keep queries SHORT and SIMPLE (1-3 words). Google Jobs works best with simple, broad queries.

CRITICAL: Always use LOCAL city names, not English ones. For example use "München" not "Munich", "Köln" not "Cologne", "Wien" not "Vienna", "Zürich" not "Zurich", "Praha" not "Prague".

ORDER queries from MOST SPECIFIC to MOST GENERAL — this is critical:
1. Queries 1-5: Exact role titles + local city name (e.g. "Carbon Accounting Manager München")
2. Queries 6-10: Broader role synonyms + city (e.g. "Sustainability Consultant München")
3. Queries 11-15: Industry/domain keywords without city or with "remote" (e.g. "ESG Analyst remote")
4. Queries 16-20: Very broad industry terms (e.g. "Environmental Engineer", "Data Analyst")

Additional strategy:
- Include BOTH English and local-language job titles for the target country
- Use different synonyms for the same role (e.g., "Manager", "Lead", "Specialist", "Analyst")

Return ONLY a JSON array of 20 search query strings, no explanation.
Example: ["Carbon Accounting Manager München", "Sustainability Manager München", "ESG Manager München", "Climate Analyst München", "Nachhaltigkeitsmanager München", "Sustainability Consultant München", "Environmental Manager München", "CSR Manager München", "Green Finance München", "Umweltberater München", "ESG Analyst remote", "Carbon Footprint Analyst", "Sustainability Analyst remote", "Climate Risk Analyst", "GHG Protocol Specialist", "Environmental Engineer", "Data Analyst Sustainability", "ESG Reporting", "Corporate Sustainability", "Environmental Consultant"]"""


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

    content = call_gemini(client, prompt, temperature=0.3, max_tokens=8192)
    data = parse_json(content)
    return CandidateProfile(**data)


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
- Skills: {', '.join(profile.skills)}
- Experience Level: {profile.experience_level}
- Target Roles: {', '.join(profile.roles)}
- Languages: {', '.join(profile.languages)}
- Domain Expertise: {', '.join(profile.domain_expertise)}
- Target Location: {location}"""

    prompt = (
        f"{HEADHUNTER_SYSTEM_PROMPT}\n\n"
        f"Generate exactly {num_queries} queries.\n\n"
        f"{profile_text}"
    )

    content = call_gemini(client, prompt, temperature=0.5, max_tokens=8192)
    queries = parse_json(content)
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
                    apply_options.append(
                        ApplyOption(source=option["title"], url=option["link"])
                    )

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


def search_jobs(query: str, num_results: int = 10, gl: str = "de") -> list[JobListing]:
    """
    Search for jobs using SerpApi Google Jobs engine with pagination.

    Args:
        query: Search query string.
        num_results: Maximum number of results to return.
        gl: Google country code (e.g. "de", "fr").

    Returns:
        List of job listings.
    """
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        raise ValueError("SERPAPI_KEY environment variable not set")

    all_jobs: list[JobListing] = []
    next_page_token = None

    while len(all_jobs) < num_results:
        params = {
            "engine": "google_jobs",
            "q": query,
            "gl": gl,
            "hl": "en",  # English results
            "api_key": api_key,
        }
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
    on_progress: "None | callable" = None,
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
        on_progress: Optional callback(query_index, total_queries, unique_jobs_count)
            invoked after each query completes.

    Returns:
        Deduplicated list of job listings.
    """
    # Translate English city names to local names (e.g. Munich → München)
    local_location = _localise_query(location)

    # Build location keywords from BOTH original and localised forms
    _location_words = set()
    for loc in (location, local_location):
        for w in loc.split():
            cleaned = re.sub(r"[^\w]", "", w).lower()
            if len(cleaned) >= 3:
                _location_words.add(cleaned)
    _location_words.add("remote")

    # Infer Google country code for localisation
    gl = _infer_gl(location)

    all_jobs: dict[str, JobListing] = {}  # Use title+company as key for dedup

    for qi, query in enumerate(queries, 1):
        # If the query doesn't already mention a location, append one
        query_lower = query.lower()
        has_location = any(kw in query_lower for kw in _location_words)
        search_query = query if has_location else f"{query} {local_location}"

        # Translate any English city names in the query itself
        search_query = _localise_query(search_query)

        jobs = search_jobs(search_query, num_results=jobs_per_query, gl=gl)
        for job in jobs:
            key = f"{job.title}|{job.company_name}"
            if key not in all_jobs:
                all_jobs[key] = job

        if on_progress is not None:
            on_progress(qi, len(queries), len(all_jobs))

        if min_unique_jobs and len(all_jobs) >= min_unique_jobs:
            break

    return list(all_jobs.values())
