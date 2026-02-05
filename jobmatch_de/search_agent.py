"""Search Agent module - Generates optimized job search queries using LLM."""

import json
import os
import time
import random
from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError
from serpapi import GoogleSearch

from .models import CandidateProfile, JobListing

# Retry configuration
MAX_RETRIES = 5
BASE_DELAY = 2  # seconds

# System prompt for the Profiler agent
PROFILER_SYSTEM_PROMPT = """You are an expert technical recruiter. You will be given the raw text of a candidate's CV.
Your goal is to extract the core metadata required to search for jobs.

Return a JSON object with:
- "skills": List of top 10 hard skills.
- "experience_level": One of "Junior", "Mid", "Senior", "Lead", "CTO".
- "roles": List of 3 job titles this candidate is perfectly suited for.
- "languages": List of spoken languages (e.g., "German C1", "English Native").
- "domain_expertise": Key industries (e.g., "Fintech", "Automotive", "SaaS").

Return ONLY valid JSON, no markdown or explanation."""

# System prompt for the Headhunter agent
HEADHUNTER_SYSTEM_PROMPT = """You are a Search Specialist. Based on the candidate's profile and location, generate 5 distinct search queries to find relevant job openings in Germany.

IMPORTANT: Keep queries SHORT and SIMPLE (2-4 words max). Google Jobs works best with simple queries.

Guidelines:
- Use simple job titles + location (e.g., "Software Engineer Berlin")
- Mix English and German job titles (e.g., "Berater München", "Consultant Berlin")
- DO NOT use complex boolean queries or too many keywords
- Each query should be different to maximize job variety

Return ONLY a JSON array of 5 search query strings, no explanation.
Example: ["Python Developer Berlin", "Backend Engineer München", "Softwareentwickler Hamburg", "Data Engineer remote Germany", "Entwickler Frankfurt"]"""


def retry_with_backoff(func):
    """Decorator that retries a function with exponential backoff on transient errors."""
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except ServerError as e:
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    # Exponential backoff with jitter
                    delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
            except ClientError as e:
                # For rate limits (429), also retry
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    last_exception = e
                    if attempt < MAX_RETRIES - 1:
                        delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                        time.sleep(delay)
                else:
                    raise
        raise last_exception
    return wrapper


def create_client() -> genai.Client:
    """Create a Gemini client."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable not set")

    return genai.Client(api_key=api_key)


@retry_with_backoff
def _call_gemini(client: genai.Client, prompt: str, temperature: float = 0.3, max_tokens: int = 1024) -> str:
    """Make a Gemini API call with retry logic."""
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
    )
    return response.text


def profile_candidate(client: genai.Client, cv_text: str) -> CandidateProfile:
    """
    Analyze CV text and extract a structured profile.

    Args:
        client: Gemini client instance.
        cv_text: Raw text extracted from CV.

    Returns:
        Structured candidate profile.
    """
    # Truncate very long CVs to avoid rate limit issues
    max_cv_length = 6000
    if len(cv_text) > max_cv_length:
        cv_text = cv_text[:max_cv_length] + "\n[...CV truncated for processing...]"

    prompt = f"{PROFILER_SYSTEM_PROMPT}\n\nExtract the profile from this CV:\n\n{cv_text}"

    content = _call_gemini(client, prompt, temperature=0.3, max_tokens=1024)

    # Check for empty response
    if not content:
        raise ValueError(
            "Empty response from API. You may have hit rate limits. "
            "Please wait a minute and try again."
        )

    # Parse JSON response
    import re
    try:
        # Remove markdown code blocks if present
        clean_content = re.sub(r'^```json\s*', '', content)
        clean_content = re.sub(r'\s*```$', '', clean_content)
        data = json.loads(clean_content)
    except json.JSONDecodeError:
        # Try to extract JSON from response if wrapped in markdown
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                raise ValueError(
                    f"Failed to parse profile response (possibly truncated due to rate limits): {content[:200]}..."
                )
        else:
            raise ValueError(
                f"Failed to parse profile response (possibly truncated due to rate limits): {content[:200]}..."
            )

    return CandidateProfile(**data)


def generate_search_queries(
    client: genai.Client,
    profile: CandidateProfile,
    location: str = "Germany"
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

    prompt = f"{HEADHUNTER_SYSTEM_PROMPT}\n\n{profile_text}"

    content = _call_gemini(client, prompt, temperature=0.5, max_tokens=1024)

    # Parse JSON array response
    import re
    try:
        queries = json.loads(content)
    except json.JSONDecodeError:
        # Try to extract complete JSON array
        json_match = re.search(r'\[[\s\S]*\]', content)
        if json_match:
            try:
                queries = json.loads(json_match.group())
            except json.JSONDecodeError:
                # Try to extract individual quoted strings if array is malformed
                string_matches = re.findall(r'"([^"]+)"', content)
                if string_matches:
                    queries = string_matches[:5]
                else:
                    raise ValueError(f"Failed to parse queries response: {content}")
        else:
            # Try to extract individual quoted strings
            string_matches = re.findall(r'"([^"]+)"', content)
            if string_matches:
                queries = string_matches[:5]
            else:
                raise ValueError(f"Failed to parse queries response: {content}")

    return queries


def search_jobs(query: str, num_results: int = 10) -> list[JobListing]:
    """
    Search for jobs using SerpApi Google Jobs engine.

    Args:
        query: Search query string.
        num_results: Maximum number of results to return.

    Returns:
        List of job listings.
    """
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        raise ValueError("SERPAPI_KEY environment variable not set")

    params = {
        "engine": "google_jobs",
        "q": query,
        "gl": "de",  # Germany
        "hl": "en",  # English results
        "api_key": api_key,
    }

    search = GoogleSearch(params)
    results = search.get_dict()

    jobs: list[JobListing] = []

    for job_data in results.get("jobs_results", [])[:num_results]:
        # Extract description from highlights or extensions
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


def search_all_queries(queries: list[str], jobs_per_query: int = 5) -> list[JobListing]:
    """
    Search for jobs across multiple queries and deduplicate results.

    Args:
        queries: List of search queries.
        jobs_per_query: Number of jobs to fetch per query.

    Returns:
        Deduplicated list of job listings.
    """
    all_jobs: dict[str, JobListing] = {}  # Use title+company as key for dedup

    for query in queries:
        jobs = search_jobs(query, num_results=jobs_per_query)
        for job in jobs:
            key = f"{job.title}|{job.company_name}"
            if key not in all_jobs:
                all_jobs[key] = job

    return list(all_jobs.values())
