"""Evaluator Agent module - Scores job listings against CV using LLM."""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai.errors import ServerError, ClientError

from .models import CandidateProfile, JobListing, JobEvaluation, EvaluatedJob
from .llm import call_gemini, parse_json

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
    certs_line = f"\n- **Certifications:** {', '.join(profile.certifications)}" if profile.certifications else ""
    edu_line = f"\n- **Education:** {', '.join(profile.education)}" if profile.education else ""
    summary_line = f"\n- **Summary:** {profile.summary}" if profile.summary else ""

    user_prompt = f"""## Candidate Profile
- **Skills:** {', '.join(profile.skills)}
- **Experience:** {profile.experience_level} ({profile.years_of_experience} years)
- **Target Roles:** {', '.join(profile.roles)}
- **Languages:** {', '.join(profile.languages)}
- **Domain Expertise:** {', '.join(profile.domain_expertise)}{edu_line}{certs_line}{summary_line}

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
        content = call_gemini(client, prompt, temperature=0.2, max_tokens=8192)
    except (ServerError, ClientError):
        return JobEvaluation(
            score=50,
            reasoning="Could not evaluate (API error after retries)",
            missing_skills=[]
        )

    try:
        data = parse_json(content)
    except ValueError:
        return JobEvaluation(
            score=50,
            reasoning="Could not evaluate (failed to parse response)",
            missing_skills=[]
        )

    return JobEvaluation(**data)


def evaluate_all_jobs(
    client: genai.Client,
    profile: CandidateProfile,
    jobs: list[JobListing],
    progress_callback=None,
    max_workers: int = 10,
) -> list[EvaluatedJob]:
    """
    Evaluate multiple jobs against the candidate profile in parallel.

    Args:
        client: Gemini client instance.
        profile: Candidate's structured profile.
        jobs: List of job listings to evaluate.
        progress_callback: Optional callback(current, total) for progress updates.
        max_workers: Number of concurrent API calls.

    Returns:
        List of evaluated jobs, sorted by score descending.
    """
    evaluated: list[EvaluatedJob] = []
    counter_lock = threading.Lock()
    completed_count = 0

    def _evaluate_one(job: JobListing) -> EvaluatedJob:
        nonlocal completed_count
        evaluation = evaluate_job(client, profile, job)
        result = EvaluatedJob(job=job, evaluation=evaluation)
        if progress_callback:
            with counter_lock:
                completed_count += 1
                progress_callback(completed_count, len(jobs))
        return result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_evaluate_one, job): job for job in jobs}
        for future in as_completed(futures):
            evaluated.append(future.result())

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
