"""Supabase database layer for StellenScout."""

import os
from datetime import datetime, timezone

from supabase import create_client, Client


def get_client() -> Client:
    """Create a read-only Supabase client (anon / publishable key).

    Uses SUPABASE_URL + SUPABASE_KEY.
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def get_admin_client() -> Client:
    """Create a Supabase client with the service-role key (bypasses RLS).

    Uses SUPABASE_URL + SUPABASE_SERVICE_KEY.
    Required for all INSERT / UPDATE / UPSERT operations.
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------

def add_subscriber(client: Client, email: str) -> dict:
    """Insert a subscriber (no-op if email already exists)."""
    return (
        client.table("subscribers")
        .upsert({"email": email}, on_conflict="email")
        .execute()
        .data
    )


def get_all_subscribers(client: Client) -> list[dict]:
    """Return all subscriber rows."""
    return client.table("subscribers").select("*").execute().data


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def upsert_jobs(client: Client, jobs: list[dict]) -> list[dict]:
    """Insert jobs, skipping duplicates by URL.

    Each dict must have: title, company, url.
    Optional: location.
    Returns the upserted rows.
    """
    if not jobs:
        return []
    rows = [
        {
            "title": j["title"],
            "company": j["company"],
            "url": j["url"],
            **({"location": j["location"]} if j.get("location") else {}),
        }
        for j in jobs
    ]
    return (
        client.table("jobs")
        .upsert(rows, on_conflict="url")
        .execute()
        .data
    )


def get_all_jobs(client: Client) -> list[dict]:
    """Return all jobs ordered by id descending (newest first)."""
    return (
        client.table("jobs")
        .select("*")
        .order("id", desc=True)
        .execute()
        .data
    )


def get_existing_urls(client: Client, urls: list[str]) -> set[str]:
    """Return the subset of *urls* that already exist in the jobs table."""
    if not urls:
        return set()
    rows = (
        client.table("jobs")
        .select("url")
        .in_("url", urls)
        .execute()
        .data
    )
    return {r["url"] for r in rows}


# ---------------------------------------------------------------------------
# Job sent log (prevents duplicate emails)
# ---------------------------------------------------------------------------

def get_sent_job_ids(client: Client, subscriber_id: str) -> set[str]:
    """Return job IDs (UUIDs) already sent to this subscriber."""
    rows = (
        client.table("job_sent_logs")
        .select("job_id")
        .eq("subscriber_id", subscriber_id)
        .execute()
        .data
    )
    return {r["job_id"] for r in rows}


def log_sent_jobs(
    client: Client, subscriber_id: str, job_ids: list[str]
) -> None:
    """Record that these jobs were emailed to the subscriber."""
    if not job_ids:
        return
    rows = [
        {
            "subscriber_id": subscriber_id,
            "job_id": jid,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        for jid in job_ids
    ]
    client.table("job_sent_logs").insert(rows).execute()
