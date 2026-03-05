"""Lightweight link validation for job apply URLs.

Fires concurrent HEAD requests against apply_option URLs to detect dead links
(404/410/403) and redirect-to-homepage patterns.  Only checks non-verified
listings — Bundesagentur links are trusted by default.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from ..models import ApplyOption, JobListing
from ._constants import USER_AGENT

logger = logging.getLogger(__name__)

_TIMEOUT = 8  # seconds per request
_MAX_WORKERS = 15
_DEAD_CODES = {404, 410, 403, 401}
_REDIRECT_CODES = {301, 302, 303, 307, 308}


def _path_depth(url: str) -> int:
    """Count non-empty path segments in a URL."""
    path = urlparse(url).path.rstrip("/")
    return len([s for s in path.split("/") if s])


def _is_redirect_to_homepage(original_url: str, redirect_url: str) -> bool:
    """Return True if the redirect lost significant path depth (job → generic page)."""
    orig_depth = _path_depth(original_url)
    redir_depth = _path_depth(redirect_url)
    # A redirect from /jobs/req-1234 (depth 2) to /careers (depth 1) or / (depth 0)
    # is suspicious.  We flag when depth drops by >= 2 or lands at root.
    return orig_depth >= 2 and (redir_depth <= 1 or orig_depth - redir_depth >= 2)


def _check_url(client: httpx.Client, url: str) -> bool:
    """Return True if the URL appears to be alive and pointing to a real job.

    Returns False for dead links, hard errors, and redirect-to-homepage patterns.
    """
    try:
        resp = client.head(url, follow_redirects=False)
    except httpx.HTTPError:
        # Network errors — don't penalise, might be transient
        return True

    if resp.status_code in _DEAD_CODES:
        return False

    if resp.status_code in _REDIRECT_CODES:
        location = resp.headers.get("location", "")
        if location and _is_redirect_to_homepage(url, location):
            return False

    return True


def _validate_one(job: JobListing, client: httpx.Client) -> JobListing | None:
    """Validate a job's apply_options, removing dead links.

    Returns None if all apply_options are dead (job should be dropped).
    Returns the job with surviving apply_options otherwise.
    """
    if job.reliability == "verified":
        return job

    live_options: list[ApplyOption] = []
    for opt in job.apply_options:
        if _check_url(client, opt.url):
            live_options.append(opt)
        else:
            logger.debug("Dead link dropped: %s (%s)", opt.url, opt.source)

    if not live_options:
        logger.info("All apply links dead, dropping: %s @ %s", job.title, job.company_name)
        return None

    if len(live_options) == len(job.apply_options):
        return job

    return job.model_copy(update={"apply_options": live_options})


def validate_jobs(jobs: list[JobListing]) -> list[JobListing]:
    """Validate apply URLs for all non-verified jobs.

    Fires HEAD requests concurrently to check for dead links and
    redirect-to-homepage patterns.  Returns only jobs with at least
    one live apply link.
    """
    needs_check = [j for j in jobs if j.reliability != "verified"]
    if not needs_check:
        return jobs

    validated: list[JobListing] = []
    dropped = 0

    with (
        httpx.Client(
            timeout=_TIMEOUT,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client,
        ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(jobs))) as pool,
    ):
        futures = {pool.submit(_validate_one, job, client): job for job in jobs}
        for future in futures:
            result = future.result()
            if result is not None:
                validated.append(result)
            else:
                dropped += 1

    if dropped:
        logger.info("Link validation dropped %d/%d jobs", dropped, len(jobs))

    return validated
