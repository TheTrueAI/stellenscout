#!/usr/bin/env python3
"""Immermatch daily digest — designed to run in GitHub Actions.

Per-subscriber pipeline:
  1. Expire subscriptions past their 30-day window.
  2. Load all active subscribers with saved profiles.
  3. Aggregate & deduplicate search queries across subscribers.
  4. Search once per unique (query, location) pair.
  5. Upsert all found jobs into the DB (with descriptions).
  6. For each subscriber: evaluate unseen jobs, filter, email, log.

Required env vars:
    GOOGLE_API_KEY                      — Gemini LLM key
    SUPABASE_URL, SUPABASE_KEY          — Supabase credentials (anon)
    SUPABASE_SERVICE_KEY                — Supabase service-role key
    RESEND_API_KEY, RESEND_FROM         — Resend email credentials
    APP_URL                             — base URL of the Streamlit app
"""

import logging
import os
import secrets
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from immermatch.db import (
    expire_subscriptions,
    get_active_subscribers_with_profiles,
    get_job_ids_by_urls,
    get_sent_job_ids,
    issue_unsubscribe_token,
    log_sent_jobs,
    purge_inactive_subscribers,
    upsert_jobs,
)
from immermatch.db import (
    get_admin_client as get_db,
)
from immermatch.emailer import send_daily_digest
from immermatch.evaluator_agent import evaluate_all_jobs
from immermatch.llm import create_client
from immermatch.models import CandidateProfile, EvaluatedJob, JobListing
from immermatch.search_agent import search_all_queries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("daily_task")


def _listing_url(job: JobListing) -> str:
    """Get the best URL for a JobListing (prefer first apply option, fall back to link)."""
    if job.apply_options:
        url = getattr(job.apply_options[0], "url", None)
        if url:
            return url
    return job.link or ""


def _job_url(ej: EvaluatedJob) -> str:
    """Get the best URL for an EvaluatedJob (prefer first apply option, fall back to link)."""
    if ej.job.apply_options:
        url = getattr(ej.job.apply_options[0], "url", None)
        if url:
            return url
    return ej.job.link or ""


def main() -> int:
    db = get_db()

    # ── 1. Expire old subscriptions ──────────────────────────────────────
    expired_count = expire_subscriptions(db)
    if expired_count:
        log.info("Auto-expired %d subscriptions past 30-day window", expired_count)

    # ── 2. Purge inactive subscribers (data already deleted on deactivation) ─
    purged_count = purge_inactive_subscribers(db, older_than_days=7)
    if purged_count:
        log.info("Purged %d inactive subscriber rows", purged_count)

    # ── 3. Load active subscribers with profiles ─────────────────────────
    subscribers = get_active_subscribers_with_profiles(db)
    if not subscribers:
        log.info("No active subscribers with profiles — nothing to do.")
        return 0
    log.info("Found %d active subscribers with profiles", len(subscribers))

    # ── 4. Aggregate & deduplicate search queries ────────────────────────
    # Group queries by location so we search each (query, location) only once
    location_queries: dict[str, set[str]] = defaultdict(set)
    for sub in subscribers:
        loc = sub.get("target_location") or ""
        queries = sub.get("search_queries") or []
        for q in queries:
            location_queries[loc].add(q)

    total_unique = sum(len(qs) for qs in location_queries.values())
    log.info(
        "Aggregated %d unique queries across %d location(s)",
        total_unique,
        len(location_queries),
    )

    # ── 5. Search once per unique (query-set, location) ──────────────────
    # Collect all jobs keyed by title|company to avoid duplication
    all_jobs: dict[str, JobListing] = {}

    for loc, queries in location_queries.items():
        query_list = sorted(queries)  # deterministic order
        log.info("Searching %d queries for location '%s'", len(query_list), loc or "(none)")
        found = search_all_queries(
            query_list,
            jobs_per_query=10,
            location=loc,
        )
        for job in found:
            key = f"{job.title}|{job.company_name}|{job.location}"
            if key not in all_jobs:
                all_jobs[key] = job

    log.info("Found %d unique jobs total", len(all_jobs))
    if not all_jobs:
        log.info("No jobs found — exiting.")
        return 0

    # ── 6. Upsert all jobs into DB (with descriptions) ───────────────────
    jobs_list = list(all_jobs.values())
    job_dicts = []
    for job in jobs_list:
        url = _listing_url(job)
        if url:
            job_dicts.append(
                {
                    "title": job.title,
                    "company": job.company_name,
                    "url": url,
                    "location": job.location,
                    "description": job.description,
                }
            )

    if job_dicts:
        upsert_jobs(db, job_dicts)
        log.info("Upserted %d jobs into DB", len(job_dicts))

    # Build URL → JobListing lookup
    url_to_job: dict[str, JobListing] = {}
    for job in jobs_list:
        url = _listing_url(job)
        if url:
            url_to_job[url] = job

    # Get DB IDs for all job URLs
    all_urls = list(url_to_job.keys())
    url_to_db_id = get_job_ids_by_urls(db, all_urls)

    # ── 7. Per-subscriber: evaluate, filter, email ───────────────────────
    gemini = create_client()
    app_url = os.environ.get("APP_URL", "").rstrip("/")

    for sub in subscribers:
        sub_email = sub["email"]
        sub_id = sub["id"]
        sub_min_score = sub.get("min_score") or 70

        # Reconstruct profile from stored JSON
        profile_data = sub.get("profile_json")
        if not profile_data:
            log.warning("  sub=%s — no profile_json, skipping", sub_id)
            continue
        try:
            profile = CandidateProfile(**profile_data)
        except Exception:
            log.exception("  sub=%s — invalid profile_json, skipping", sub_id)
            continue

        # Find unseen jobs for this subscriber
        sent_ids = get_sent_job_ids(db, sub_id)
        unseen_urls = [url for url in all_urls if url_to_db_id.get(url) and url_to_db_id[url] not in sent_ids]

        if not unseen_urls:
            log.info("  sub=%s — no unseen jobs, skipping", sub_id)
            continue

        # Build JobListing objects for unseen jobs
        unseen_jobs = [url_to_job[url] for url in unseen_urls if url in url_to_job]
        log.info("  sub=%s — evaluating %d unseen jobs", sub_id, len(unseen_jobs))

        # Evaluate unseen jobs against this subscriber's profile
        evaluated = evaluate_all_jobs(gemini, profile, unseen_jobs)

        # Filter by subscriber's min score
        good_matches = [ej for ej in evaluated if ej.evaluation.score >= sub_min_score]

        if not good_matches:
            log.info("  sub=%s — no jobs above score %d", sub_id, sub_min_score)
            # Still log all evaluated jobs as "sent" to avoid re-evaluating
            all_eval_ids = [url_to_db_id[_job_url(ej)] for ej in evaluated if _job_url(ej) in url_to_db_id]
            if all_eval_ids:
                log_sent_jobs(db, sub_id, all_eval_ids)
            continue

        # Send email
        email_jobs = [
            {
                "title": ej.job.title,
                "company": ej.job.company_name,
                "url": _job_url(ej),
                "score": ej.evaluation.score,
                "location": ej.job.location,
            }
            for ej in good_matches
        ]

        unsubscribe_url = ""
        if app_url:
            unsub_token = secrets.token_urlsafe(32)
            unsub_expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            token_written = issue_unsubscribe_token(
                db,
                sub_id,
                token=unsub_token,
                expires_at=unsub_expires,
            )
            if token_written:
                unsubscribe_url = f"{app_url}/unsubscribe?token={unsub_token}"

        log.info("  sub=%s — sending %d matches (score >= %d)", sub_id, len(email_jobs), sub_min_score)
        try:
            send_daily_digest(
                sub_email,
                email_jobs,
                unsubscribe_url=unsubscribe_url,
                target_location=sub.get("target_location", ""),
            )
        except Exception:
            log.exception("  sub=%s — failed to send daily digest, continuing", sub_id)

        # Log ALL evaluated jobs (not just good matches) to avoid re-evaluation
        all_eval_ids = [url_to_db_id[_job_url(ej)] for ej in evaluated if _job_url(ej) in url_to_db_id]
        if all_eval_ids:
            log_sent_jobs(db, sub_id, all_eval_ids)

    log.info("Daily digest complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
