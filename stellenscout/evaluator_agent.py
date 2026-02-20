"""Evaluator Agent module - Scores job listings against CV using LLM."""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai.errors import ClientError, ServerError

from .llm import call_gemini, parse_json
from .models import CandidateProfile, EvaluatedJob, JobEvaluation, JobListing

# System prompt for the Screener agent
SCREENER_SYSTEM_PROMPT = """You are a strict Hiring Manager. Evaluate if the candidate is a fit for this specific job.

**Scoring Rubric (0-100):**
- **100:** Perfect match. The candidate has the exact years of experience, tech stack, and language skills required.
- **80-99:** Great match. Missing minor "nice-to-haves" or slightly different domain, but strong core skills.
- **50-79:** Potential fit. Strong skills but maybe junior/senior mismatch, or missing a key framework.
- **0-49:** Hard pass. Wrong stack (Java vs Python), wrong language (requires German C2 but candidate is A1), or wrong role entirely.

**Critical constraints:**
- If the job description requires fluency in a local language (e.g., German, French, Dutch) and the candidate lacks that proficiency (A1/A2 or not listed), the score must be capped at 30.
- Pay attention to visa/work permit requirements if mentioned.

Return ONLY a JSON object with:
- "score": (int) The match score 0-100
- "reasoning": (string) A concise 1-2 sentence explanation of the score
- "missing_skills": (list) What is the candidate missing? Empty list if nothing major.

Be critical but fair. European companies often have strict requirements."""


def evaluate_job(client: genai.Client, profile: CandidateProfile, job: JobListing) -> JobEvaluation:
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
- **Skills:** {", ".join(profile.skills)}
- **Experience:** {profile.experience_level} ({profile.years_of_experience} years)
- **Target Roles:** {", ".join(profile.roles)}
- **Languages:** {", ".join(profile.languages)}
- **Domain Expertise:** {", ".join(profile.domain_expertise)}{edu_line}{certs_line}{summary_line}

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
        return JobEvaluation(score=50, reasoning="Could not evaluate (API error after retries)", missing_skills=[])

    try:
        data = parse_json(content)
    except ValueError:
        return JobEvaluation(score=50, reasoning="Could not evaluate (failed to parse response)", missing_skills=[])

    if not isinstance(data, dict):
        return JobEvaluation(score=50, reasoning="Could not evaluate (unexpected response format)", missing_skills=[])
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


# ---------------------------------------------------------------------------
# Career advisor summary
# ---------------------------------------------------------------------------

ADVISOR_SYSTEM_PROMPT = """You are a career advisor. Given a candidate profile and their evaluated job matches, write a very brief summary. Use a friendly and encouraging tone, but be honest about the fit. Focus on actionable insights.
Use emojis to make it more engaging.

Structure your response in plain text with these sections:
1. **Market Overview** (2-3 sentences): How well does this candidate fit the current job market? How many strong matches vs weak ones?
2. **Skill Gaps** (bullet list): The most frequently missing skills across job listings. Prioritise by how often they appear.
3. **Career Advice** (2-3 sentences): Actionable next steps — certifications to pursue, skills to learn, or positioning tips.

Be concise and specific to THIS candidate. Use markdown formatting."""


def generate_summary(
    client: genai.Client,
    profile: CandidateProfile,
    evaluated_jobs: list[EvaluatedJob],
) -> str:
    """Generate a career-advice summary from the candidate profile and evaluated jobs.

    Args:
        client: Gemini client instance.
        profile: Candidate's structured profile.
        evaluated_jobs: All evaluated jobs, sorted by score descending.

    Returns:
        Markdown-formatted summary string.
    """
    # Score distribution
    bins = {"≥80": 0, "70-79": 0, "50-69": 0, "<50": 0}
    for ej in evaluated_jobs:
        s = ej.evaluation.score
        if s >= 80:
            bins["≥80"] += 1
        elif s >= 70:
            bins["70-79"] += 1
        elif s >= 50:
            bins["50-69"] += 1
        else:
            bins["<50"] += 1

    # Missing skills frequency
    skill_counts: Counter[str] = Counter()
    for ej in evaluated_jobs:
        for skill in ej.evaluation.missing_skills:
            skill_counts[skill] += 1
    top_missing = skill_counts.most_common(10)

    # Top matches (up to 10)
    top_matches = evaluated_jobs[:10]
    matches_text = "\n".join(
        f"- {ej.job.title} @ {ej.job.company_name} — score {ej.evaluation.score}/100 — "
        f"{ej.evaluation.reasoning}"
        + (f" (missing: {', '.join(ej.evaluation.missing_skills)})" if ej.evaluation.missing_skills else "")
        for ej in top_matches
    )

    missing_text = (
        "\n".join(f"- {skill} (appears in {count} listings)" for skill, count in top_missing)
        if top_missing
        else "- None identified"
    )

    dist_text = ", ".join(f"{k}: {v}" for k, v in bins.items())

    user_prompt = f"""## Candidate Profile
- **Skills:** {", ".join(profile.skills)}
- **Experience:** {profile.experience_level} ({profile.years_of_experience} years)
- **Target Roles:** {", ".join(profile.roles)}
- **Languages:** {", ".join(profile.languages)}

## Score Distribution ({len(evaluated_jobs)} jobs evaluated)
{dist_text}

## Top Matches
{matches_text}

## Most Frequently Missing Skills
{missing_text}

---
Write the career summary now."""

    prompt = f"{ADVISOR_SYSTEM_PROMPT}\n\n{user_prompt}"

    return call_gemini(client, prompt, temperature=0.5, max_tokens=2048)
