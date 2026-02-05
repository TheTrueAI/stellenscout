"""Evaluator Agent module - Scores job listings against CV using LLM."""

import json
import time
import random
from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError

from .models import CandidateProfile, JobListing, JobEvaluation, EvaluatedJob

# Retry configuration
MAX_RETRIES = 5
BASE_DELAY = 2  # seconds

# System prompt for the Screener agent
SCREENER_SYSTEM_PROMPT = """You are a strict Hiring Manager. Evaluate if the candidate is a fit for this specific job.

**Scoring Rubric (0-100):**
- **100:** Perfect match. The candidate has the exact years of experience, tech stack, and language skills required.
- **80-99:** Great match. Missing minor "nice-to-haves" or slightly different domain, but strong core skills.
- **50-79:** Potential fit. Strong skills but maybe junior/senior mismatch, or missing a key framework.
- **0-49:** Hard pass. Wrong stack (Java vs Python), wrong language (requires German C2 but candidate is A1), or wrong role entirely.

**Critical constraints for Germany:**
- If the job description is in German and requires "Fließend Deutsch" or similar German fluency requirements, and the candidate only speaks English or has low German proficiency (A1/A2), the score must be capped at 30.
- Pay attention to visa/work permit requirements if mentioned.

Return ONLY a JSON object with:
- "score": (int) The match score 0-100
- "reasoning": (string) A concise 1-2 sentence explanation of the score
- "missing_skills": (list) What is the candidate missing? Empty list if nothing major.

Be critical but fair. German companies often have strict requirements."""


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


@retry_with_backoff
def _call_gemini(client: genai.Client, prompt: str, temperature: float = 0.2, max_tokens: int = 512) -> str:
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


def evaluate_job(
    client: genai.Client,
    profile: CandidateProfile,
    job: JobListing
) -> JobEvaluation:
    """
    Evaluate how well a job matches the candidate's profile.

    Args:
        client: Gemini client instance.
        profile: Candidate's structured profile.
        job: Job listing to evaluate.

    Returns:
        Evaluation with score and reasoning.
    """
    user_prompt = f"""## Candidate Profile
- **Skills:** {', '.join(profile.skills)}
- **Experience Level:** {profile.experience_level}
- **Target Roles:** {', '.join(profile.roles)}
- **Languages:** {', '.join(profile.languages)}
- **Domain Expertise:** {', '.join(profile.domain_expertise)}

## Job Listing
- **Title:** {job.title}
- **Company:** {job.company_name}
- **Location:** {job.location}

**Job Description:**
{job.description[:2000] if job.description else "No detailed description available."}

---
Evaluate this job match and return JSON."""

    prompt = f"{SCREENER_SYSTEM_PROMPT}\n\n{user_prompt}"

    try:
        content = _call_gemini(client, prompt, temperature=0.2, max_tokens=512)
    except (ServerError, ClientError) as e:
        # If all retries failed, return a fallback evaluation
        return JobEvaluation(
            score=50,
            reasoning=f"Could not evaluate (API error after retries)",
            missing_skills=[]
        )

    # Handle empty/None response (safety filters or rate limits)
    if not content:
        return JobEvaluation(
            score=50,
            reasoning="Could not evaluate (API returned empty response)",
            missing_skills=[]
        )

    # Parse JSON response
    import re
    try:
        # Remove markdown code blocks if present
        clean_content = re.sub(r'^```json\s*', '', content)
        clean_content = re.sub(r'\s*```$', '', clean_content)
        data = json.loads(clean_content)
    except json.JSONDecodeError:
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                return JobEvaluation(
                    score=0,
                    reasoning=f"Failed to parse evaluation: {content[:100]}",
                    missing_skills=[]
                )
        else:
            # Fallback for unparseable response
            return JobEvaluation(
                score=0,
                reasoning=f"Failed to parse evaluation: {content[:100]}",
                missing_skills=[]
            )

    return JobEvaluation(**data)


def evaluate_all_jobs(
    client: genai.Client,
    profile: CandidateProfile,
    jobs: list[JobListing],
    progress_callback=None
) -> list[EvaluatedJob]:
    """
    Evaluate multiple jobs against the candidate profile.

    Args:
        client: Gemini client instance.
        profile: Candidate's structured profile.
        jobs: List of job listings to evaluate.
        progress_callback: Optional callback(current, total) for progress updates.

    Returns:
        List of evaluated jobs, sorted by score descending.
    """
    evaluated: list[EvaluatedJob] = []

    for i, job in enumerate(jobs):
        if progress_callback:
            progress_callback(i + 1, len(jobs))

        evaluation = evaluate_job(client, profile, job)
        evaluated.append(EvaluatedJob(job=job, evaluation=evaluation))

    # Sort by score descending
    evaluated.sort(key=lambda x: x.evaluation.score, reverse=True)

    return evaluated


def filter_good_matches(
    evaluated_jobs: list[EvaluatedJob],
    min_score: int = 70
) -> list[EvaluatedJob]:
    """
    Filter evaluated jobs to only include good matches.

    Args:
        evaluated_jobs: List of evaluated jobs.
        min_score: Minimum score threshold.

    Returns:
        Filtered list of jobs with score >= min_score.
    """
    return [ej for ej in evaluated_jobs if ej.evaluation.score >= min_score]
