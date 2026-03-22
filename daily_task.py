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
    mark_subscriber_last_sent,
    purge_inactive_subscribers,
    upsert_jobs,
)
from immermatch.db import (
    get_admin_client as get_db,
)
from immermatch.emailer import send_daily_digest
from immermatch.evaluator_agent import evaluate_all_jobs
from immermatch.llm import create_client
from immermatch.location import normalize_location
from immermatch.models import CandidateProfile, EvaluatedJob, JobListing
from immermatch.search_api.search_agent import search_all_queries

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
        loc = normalize_location(sub.get("target_location") or "")
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
    # Collect all jobs keyed by title|company_name|location to avoid duplication
    all_jobs: dict[str, JobListing] = {}
    # Track which URLs belong to which normalized location
    location_urls: dict[str, set[str]] = defaultdict(set)

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
            url = _listing_url(job)
            if url:
                location_urls[loc].add(url)

    log.info("Found %d unique jobs total", len(all_jobs))
    if not all_jobs:
        log.info("No jobs found — exiting.")
        return 0

    # ── 6. Upsert all jobs into DB (with descriptions) ───────────────────
    jobs_list = list(all_jobs.values())
    job_dicts = []
    url_to_job: dict[str, JobListing] = {}
    for job in jobs_list:
        url = _listing_url(job)
        if url:
            url_to_job[url] = job
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

    # Get DB IDs for all job URLs
    url_to_db_id = get_job_ids_by_urls(db, list(url_to_job.keys()))

    # ── 7. Per-subscriber: evaluate, filter, email ───────────────────────
    gemini = create_client()
    app_url = os.environ.get("APP_URL", "").rstrip("/")

    for sub in subscribers:
        sub_email = sub["email"]
        sub_id = sub["id"]
        sub_min_score = sub.get("min_score") or 70
        sub_cadence = sub.get("cadence") or "daily"

        # Skip weekly subscribers whose last send was less than 7 days ago
        if sub_cadence == "weekly":
            last_sent = sub.get("last_sent_at")
            if last_sent:
                last_sent_dt = datetime.fromisoformat(last_sent.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) - last_sent_dt < timedelta(days=7):
                    log.info("  sub=%s — weekly cadence, last sent %s, skipping", sub_id, last_sent)
                    continue

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

        # Find unseen jobs for this subscriber — only from their location bucket
        sent_ids = get_sent_job_ids(db, sub_id)
        sub_loc = normalize_location(sub.get("target_location") or "")
        sub_urls = location_urls.get(sub_loc, set())
        unseen_urls = sorted(url for url in sub_urls if url_to_db_id.get(url) and url_to_db_id[url] not in sent_ids)

        if not unseen_urls:
            log.info("  sub=%s — no unseen jobs, skipping", sub_id)
            continue

        # Build JobListing objects for unseen jobs
        unseen_jobs = [url_to_job[url] for url in unseen_urls if url in url_to_job]
        log.info("  sub=%s — evaluating %d unseen jobs", sub_id, len(unseen_jobs))

        # Evaluate unseen jobs against this subscriber's profile
        evaluated = evaluate_all_jobs(gemini, profile, unseen_jobs)

        # Split evaluated jobs by score threshold.
        # Low-score IDs are always safe to log (we never want to re-evaluate them).
        # Good-match IDs are only logged after a successful send so they retry
        # on the next run if the email fails.
        evaluated_with_urls = [(ej, _job_url(ej)) for ej in evaluated]
        good_matches = [ej for ej, _ in evaluated_with_urls if ej.evaluation.score >= sub_min_score]
        low_score_ids = [
            url_to_db_id[url]
            for ej, url in evaluated_with_urls
            if 0 <= ej.evaluation.score < sub_min_score and url in url_to_db_id
        ]
        good_match_ids = [
            url_to_db_id[url]
            for ej, url in evaluated_with_urls
            if ej.evaluation.score >= sub_min_score and url in url_to_db_id
        ]

        if not good_matches:
            log.info("  sub=%s — no jobs above score %d", sub_id, sub_min_score)
            # Log all evaluated (all are low-score) to avoid re-evaluating
            if low_score_ids:
                log_sent_jobs(db, sub_id, low_score_ids)
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
            # Only log low-score IDs; good matches will retry on the next run.
            # Idempotency: the sent_ids check (get_sent_job_ids) prevents
            # double-sending across runs. After a failed send, good-match IDs
            # stay out of job_sent_logs and reappear as unseen on the next run.
            if low_score_ids:
                log_sent_jobs(db, sub_id, low_score_ids)
            continue

        # Send succeeded — first mark subscriber as sent, then best-effort log ALL evaluated jobs
        try:
            mark_subscriber_last_sent(db, sub_id)
        except Exception:
            log.exception(
                "  sub=%s — failed to mark last_sent_at; subscriber may receive duplicate digests",
                sub_id,
            )

        all_eval_ids = low_score_ids + good_match_ids
        if all_eval_ids:
            try:
                log_sent_jobs(db, sub_id, all_eval_ids)
            except Exception:
                log.exception(
                    "  sub=%s — failed to log sent jobs; will retry evaluation next run",
                    sub_id,
                )

    log.info("Daily digest complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
