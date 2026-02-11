#!/usr/bin/env python3
"""StellenScout daily digest — designed to run in GitHub Actions.

Steps:
  1. Load CV text and build a candidate profile.
  2. Generate search queries and fetch jobs from SerpApi.
  3. Evaluate each job against the profile.
  4. Filter out jobs already in Supabase → save new ones.
  5. For each subscriber, email only unseen jobs and update job_sent_log.

Required env vars:
    GOOGLE_API_KEY, SERPAPI_KEY          — existing search/LLM keys
    SUPABASE_URL, SUPABASE_KEY          — Supabase credentials
    RESEND_API_KEY                       — Resend email key
    CV_PATH                             — path to the CV file (default: cv.pdf)
    TARGET_LOCATION                     — job search location (default: "")
    MIN_SCORE                           — minimum score to include (default: 70)
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from stellenscout.cv_parser import extract_text
from stellenscout.llm import create_client
from stellenscout.search_agent import (
    profile_candidate,
    generate_search_queries,
    search_all_queries,
)
from stellenscout.evaluator_agent import evaluate_all_jobs
from stellenscout.models import EvaluatedJob
from stellenscout.db import (
    get_admin_client as get_db,
    get_existing_urls,
    upsert_jobs,
    get_active_subscribers,
    get_sent_job_ids,
    log_sent_jobs,
)
from stellenscout.emailer import send_daily_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("daily_task")


def main() -> int:
    cv_path = Path(os.environ.get("CV_PATH", "cv.pdf"))
    location = os.environ.get("TARGET_LOCATION", "")
    min_score = int(os.environ.get("MIN_SCORE", "70"))

    # ── 1. Parse CV & build profile ──────────────────────────────────────
    log.info("Parsing CV: %s", cv_path)
    cv_text = extract_text(cv_path)

    gemini = create_client()
    profile = profile_candidate(gemini, cv_text)
    log.info("Profile: %s (%s)", profile.roles[0], profile.experience_level)

    # ── 2. Generate queries & search ─────────────────────────────────────
    queries = generate_search_queries(gemini, profile, location)
    log.info("Generated %d search queries", len(queries))

    jobs = search_all_queries(queries, jobs_per_query=10, location=location)
    log.info("Found %d unique jobs from SerpApi", len(jobs))

    if not jobs:
        log.warning("No jobs found — exiting.")
        return 0

    # ── 3. Evaluate jobs ─────────────────────────────────────────────────
    evaluated = evaluate_all_jobs(gemini, profile, jobs)
    log.info("Evaluated %d jobs", len(evaluated))

    # ── 4. Filter against DB & save new ones ─────────────────────────────
    db = get_db()

    # Build a URL for each evaluated job (prefer first apply option, fall back to link)
    def _job_url(ej: EvaluatedJob) -> str:
        if ej.job.apply_options:
            return ej.job.apply_options[0].url
        return ej.job.link or ""

    url_to_ej: dict[str, EvaluatedJob] = {}
    for ej in evaluated:
        url = _job_url(ej)
        if url and ej.evaluation.score >= min_score:
            url_to_ej[url] = ej

    existing_urls = get_existing_urls(db, list(url_to_ej.keys()))
    new_ejs = {u: ej for u, ej in url_to_ej.items() if u not in existing_urls}

    if not new_ejs:
        log.info("No new jobs above score %d — nothing to email.", min_score)
        return 0

    log.info("Saving %d new jobs to Supabase", len(new_ejs))
    saved_rows = upsert_jobs(
        db,
        [
            {
                "title": ej.job.title,
                "company": ej.job.company_name,
                "url": url,
                "location": ej.job.location,
            }
            for url, ej in new_ejs.items()
        ],
    )

    # Map URL → DB id (UUID) for sent-log tracking
    url_to_db_id: dict[str, str] = {r["url"]: r["id"] for r in saved_rows}

    # Also fetch IDs of jobs that already existed (they may be new to some subscribers)
    all_urls = list(url_to_ej.keys())
    all_rows = (
        db.table("jobs").select("id, url").in_("url", all_urls).execute().data
    )
    url_to_db_id.update({r["url"]: r["id"] for r in all_rows})

    # ── 5. Email each active subscriber with unseen jobs ──────────────────
    app_url = os.environ.get("APP_URL", "").rstrip("/")
    subscribers = get_active_subscribers(db)
    log.info("Processing %d active subscribers", len(subscribers))

    for sub in subscribers:
        sent_ids = get_sent_job_ids(db, sub["id"])
        unseen = [
            {
                "title": ej.job.title,
                "company": ej.job.company_name,
                "url": url,
                "score": ej.evaluation.score,
            }
            for url, ej in url_to_ej.items()
            if url_to_db_id.get(url) and url_to_db_id[url] not in sent_ids
        ]

        if not unseen:
            log.info("  %s — no unseen jobs, skipping", sub["email"])
            continue

        unsubscribe_url = f"{app_url}/unsubscribe?id={sub['id']}" if app_url else ""
        log.info("  %s — sending %d jobs", sub["email"], len(unseen))
        send_daily_digest(sub["email"], unseen, unsubscribe_url=unsubscribe_url)

        new_sent_ids = [url_to_db_id[j["url"]] for j in unseen]
        log_sent_jobs(db, sub["id"], new_sent_ids)

    log.info("Daily digest complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
