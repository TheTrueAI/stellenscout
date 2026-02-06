"""Search Agent module - Generates optimized job search queries using LLM."""

import os
from google import genai
from serpapi import GoogleSearch

from .models import CandidateProfile, JobListing
from .llm import call_gemini, parse_json

# System prompt for the Profiler agent
PROFILER_SYSTEM_PROMPT = """You are an expert technical recruiter with deep knowledge of the German job market.
You will be given the raw text of a candidate's CV. Extract a comprehensive profile.

Be THOROUGH — capture everything relevant. Do not summarize away important details.

Return a JSON object with:
- "skills": List of ALL hard skills, tools, frameworks, methodologies, and technical competencies mentioned. Include specific tools (e.g., "SAP", "Power BI"), standards (e.g., "ISO 14064", "GHG Protocol"), and methods. Aim for 15-20 items.
- "experience_level": One of "Junior" (<2 years), "Mid" (2-5 years), "Senior" (5-10 years), "Lead" (10+ years), "CTO".
- "years_of_experience": (int) Total years of professional experience. Calculate from work history dates.
- "roles": List of 5 job titles the candidate is suited for, ordered from most to least specific. Include both English and German titles where relevant.
- "languages": List of spoken languages with proficiency level (e.g., "German B2", "English Native", "Urdu Native").
- "domain_expertise": List of all industries and domains the candidate has worked in.
- "certifications": List of professional certifications, accreditations, or licenses (e.g., "PMP", "AWS Solutions Architect"). Empty list if none.
- "education": List of degrees with field of study (e.g., "MSc Environmental Engineering", "BSc Computer Science"). Include the university name if mentioned.
- "summary": A 2-3 sentence professional summary describing the candidate's core strengths and career trajectory.

Return ONLY valid JSON, no markdown or explanation."""

# System prompt for the Headhunter agent
HEADHUNTER_SYSTEM_PROMPT = """You are a Search Specialist. Based on the candidate's profile and location, generate 10 distinct search queries to find relevant job openings in Germany.

IMPORTANT: Keep queries SHORT and SIMPLE (1-3 words). Google Jobs works best with simple, broad queries.

Strategy for MAXIMUM coverage:
- Generate a MIX of broad and specific queries
- Include BOTH English and German job titles (e.g., "Consultant München" AND "Berater München")
- Include some queries WITHOUT a city to find remote/nationwide jobs
- Use different synonyms for the same role (e.g., "Manager", "Lead", "Specialist", "Analyst")
- Include 1-2 broad industry/domain queries (e.g., "Nachhaltigkeit München", "ESG Germany")

Return ONLY a JSON array of 10 search query strings, no explanation.
Example: ["Python Developer Berlin", "Backend Engineer Berlin", "Softwareentwickler Berlin", "Developer remote Germany", "Entwickler Berlin", "Software Engineer", "IT Berater Berlin", "Cloud Engineer Berlin", "DevOps Berlin", "Programmierer Berlin"]"""


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
    location: str = "Germany",
    num_queries: int = 10,
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

        job = JobListing(
            title=job_data.get("title", "Unknown"),
            company_name=job_data.get("company_name", "Unknown"),
            location=job_data.get("location", "Germany"),
            description="\n".join(description_parts),
            link=job_data.get("share_link", job_data.get("link", "")),
            posted_at=job_data.get("detected_extensions", {}).get("posted_at", ""),
        )
        jobs.append(job)

    return jobs


def search_jobs(query: str, num_results: int = 10) -> list[JobListing]:
    """
    Search for jobs using SerpApi Google Jobs engine with pagination.

    Args:
        query: Search query string.
        num_results: Maximum number of results to return.

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
            "gl": "de",  # Germany
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
    location: str = "Germany",
) -> list[JobListing]:
    """
    Search for jobs across multiple queries and deduplicate results.
    Queries without a location keyword get the location appended automatically,
    since Google Jobs returns nothing without geographic context.

    Args:
        queries: List of search queries.
        jobs_per_query: Number of jobs to fetch per query.
        location: Target location to append to queries missing one.

    Returns:
        Deduplicated list of job listings.
    """
    # Common German city names / location keywords for detection
    _LOCATION_KEYWORDS = {
        "berlin", "münchen", "munich", "hamburg", "frankfurt", "köln", "cologne",
        "düsseldorf", "stuttgart", "dortmund", "essen", "leipzig", "bremen",
        "dresden", "hannover", "nürnberg", "nuremberg", "germany", "deutschland",
        "remote",
    }

    all_jobs: dict[str, JobListing] = {}  # Use title+company as key for dedup

    for query in queries:
        # If the query doesn't already mention a location, append one
        query_lower = query.lower()
        has_location = any(kw in query_lower for kw in _LOCATION_KEYWORDS)
        search_query = query if has_location else f"{query} {location}"

        jobs = search_jobs(search_query, num_results=jobs_per_query)
        for job in jobs:
            key = f"{job.title}|{job.company_name}"
            if key not in all_jobs:
                all_jobs[key] = job

    return list(all_jobs.values())
