"""Supabase database layer for StellenScout."""

import os
from typing import Any
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

def add_subscriber(
    client: Client,
    email: str,
    token: str,
    expires_at: str,
    consent_text_version: str,
    signup_ip: str | None = None,
    signup_user_agent: str | None = None,
) -> dict | None:
    """Insert a pending subscriber with a confirmation token.

    If the email already exists and is active, returns the existing row
    (caller should treat this as a no-op).  Otherwise upserts a new
    pending row with the given token and expiry.

    Returns:
        The existing active row (dict) if already confirmed, or None
        to indicate a new/pending row was written.
    """
    # Check if already active
    existing = (
        client.table("subscribers")
        .select("*")
        .eq("email", email)
        .execute()
        .data
    )
    if existing and existing[0].get("is_active"):
        return existing[0]

    # Upsert pending subscriber with new token
    client.table("subscribers").upsert(
        {
            "email": email,
            "is_active": False,
            "confirmation_token": token,
            "token_expires_at": expires_at,
            "consent_text_version": consent_text_version,
            "signup_ip": signup_ip,
            "signup_user_agent": signup_user_agent,
            "confirmed_at": None,
            "unsubscribed_at": None,
        },
        on_conflict="email",
    ).execute()
    return None


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def confirm_subscriber(
    client: Client,
    token: str,
    confirm_ip: str | None = None,
    confirm_user_agent: str | None = None,
) -> dict | None:
    """Activate a subscriber by confirmation token.

    Checks that the token exists and has not expired.  On success sets
    ``is_active=True`` and clears the token fields.

    Returns:
        The updated subscriber dict, or None if the token is invalid/expired.
    """
    rows = (
        client.table("subscribers")
        .select("*")
        .eq("confirmation_token", token)
        .execute()
        .data
    )
    if not rows:
        return None

    sub = rows[0]
    exp_dt = _parse_iso_utc(sub.get("token_expires_at"))
    if exp_dt and datetime.now(timezone.utc) > exp_dt:
        return None

    client.table("subscribers").update(
        {
            "is_active": True,
            "confirmation_token": None,
            "token_expires_at": None,
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "confirm_ip": confirm_ip,
            "confirm_user_agent": confirm_user_agent,
            "unsubscribed_at": None,
            "unsubscribe_token": None,
            "unsubscribe_token_expires_at": None,
        }
    ).eq("id", sub["id"]).execute()

    sub["is_active"] = True
    return sub


def get_active_subscribers(client: Client) -> list[dict]:
    """Return subscribers where is_active is True."""
    return (
        client.table("subscribers")
        .select("*")
        .eq("is_active", True)
        .execute()
        .data
    )


def get_all_subscribers(client: Client) -> list[dict]:
    """Return all subscriber rows."""
    return client.table("subscribers").select("*").execute().data


def deactivate_subscriber(client: Client, subscriber_id: str) -> bool:
    """Set a subscriber's is_active to False (unsubscribe).

    Returns True if a row was updated, False otherwise.
    """
    result = (
        client.table("subscribers")
        .update(
            {
                "is_active": False,
                "unsubscribed_at": datetime.now(timezone.utc).isoformat(),
                "unsubscribe_token": None,
                "unsubscribe_token_expires_at": None,
            }
        )
        .eq("id", subscriber_id)
        .execute()
    )
    return bool(result.data)


def issue_unsubscribe_token(
    client: Client, subscriber_id: str, token: str, expires_at: str
) -> bool:
    """Store a short-lived unsubscribe token for a subscriber."""
    result = (
        client.table("subscribers")
        .update(
            {
                "unsubscribe_token": token,
                "unsubscribe_token_expires_at": expires_at,
            }
        )
        .eq("id", subscriber_id)
        .eq("is_active", True)
        .execute()
    )
    return bool(result.data)


def deactivate_subscriber_by_token(client: Client, token: str) -> bool:
    """Deactivate a subscriber via one-time unsubscribe token."""
    rows = (
        client.table("subscribers")
        .select("id, unsubscribe_token_expires_at, is_active")
        .eq("unsubscribe_token", token)
        .execute()
        .data
    )
    if not rows:
        return False

    sub = rows[0]
    if not sub.get("is_active"):
        return False

    exp_dt = _parse_iso_utc(sub.get("unsubscribe_token_expires_at"))
    if exp_dt and datetime.now(timezone.utc) > exp_dt:
        return False

    return deactivate_subscriber(client, sub["id"])


def purge_inactive_subscribers(client: Client, older_than_days: int = 30) -> int:
    """Delete inactive subscribers after a retention window.

    Returns the number of deleted rows.
    """
    rows: list[dict[str, Any]] = (
        client.table("subscribers")
        .select("id, unsubscribed_at, is_active")
        .eq("is_active", False)
        .execute()
        .data
    )
    if not rows:
        return 0

    cutoff = datetime.now(timezone.utc).timestamp() - (older_than_days * 24 * 60 * 60)
    to_delete: list[str] = []
    for row in rows:
        unsub_dt = _parse_iso_utc(row.get("unsubscribed_at"))
        if unsub_dt and unsub_dt.timestamp() <= cutoff:
            to_delete.append(row["id"])

    if not to_delete:
        return 0

    deleted = 0
    chunk_size = 200
    for start in range(0, len(to_delete), chunk_size):
        chunk = to_delete[start: start + chunk_size]
        result = (
            client.table("subscribers")
            .delete()
            .in_("id", chunk)
            .execute()
        )
        deleted += len(result.data or [])
    return deleted


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
