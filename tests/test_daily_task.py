"""Tests for the daily digest task (daily_task.py).

Tests the main() orchestrator by mocking all external services:
DB, SerpApi search, Gemini evaluation, and Resend emailer.
"""

from unittest.mock import MagicMock, patch

from immermatch.models import (
    ApplyOption,
    EvaluatedJob,
    JobEvaluation,
    JobListing,
)

# ---------------------------------------------------------------------------
# Helpers — build test data
# ---------------------------------------------------------------------------


def _make_subscriber(
    sub_id: str = "sub-001",
    email: str = "user@example.com",
    target_location: str = "Munich, Germany",
    min_score: int = 70,
    queries: list[str] | None = None,
    profile_json: dict | None = None,
) -> dict:
    """Build a fake subscriber dict as returned by get_active_subscribers_with_profiles."""
    if queries is None:
        queries = ["Python Developer München", "Backend Engineer Munich"]
    if profile_json is None:
        profile_json = {
            "skills": ["Python", "Go"],
            "experience_level": "Senior",
            "years_of_experience": 7,
            "roles": ["Senior Software Engineer"],
            "languages": ["English Native", "German B2"],
            "domain_expertise": ["FinTech"],
            "certifications": [],
            "education": ["MSc Computer Science"],
            "summary": "Senior engineer.",
            "work_history": [],
            "education_history": [],
        }
    return {
        "id": sub_id,
        "email": email,
        "target_location": target_location,
        "min_score": min_score,
        "search_queries": queries,
        "profile_json": profile_json,
    }


def _make_job_listing(
    title: str = "Python Dev", company: str = "Corp GmbH", url: str = "https://example.com/job/1"
) -> JobListing:
    return JobListing(
        title=title,
        company_name=company,
        location="Munich, Germany",
        description="A job description.",
        link=url,
        apply_options=[ApplyOption(source="LinkedIn", url=url)],
    )


def _make_evaluated_job(job: JobListing, score: int = 85) -> EvaluatedJob:
    return EvaluatedJob(
        job=job,
        evaluation=JobEvaluation(
            score=score,
            reasoning="Good match.",
            missing_skills=[],
        ),
    )


# ---------------------------------------------------------------------------
# Patch targets (all in the daily_task module's namespace)
# ---------------------------------------------------------------------------

_PATCH_PREFIX = "daily_task"


class TestDailyTaskExpireAndPurge:
    """Step 1-2: expire old subscriptions and purge inactive rows."""

    @patch(f"{_PATCH_PREFIX}.send_daily_digest")
    @patch(f"{_PATCH_PREFIX}.evaluate_all_jobs", return_value=[])
    @patch(f"{_PATCH_PREFIX}.search_all_queries", return_value=[])
    @patch(f"{_PATCH_PREFIX}.get_active_subscribers_with_profiles", return_value=[])
    @patch(f"{_PATCH_PREFIX}.purge_inactive_subscribers", return_value=3)
    @patch(f"{_PATCH_PREFIX}.expire_subscriptions", return_value=2)
    @patch(f"{_PATCH_PREFIX}.create_client", return_value=MagicMock())
    @patch(f"{_PATCH_PREFIX}.get_db", return_value=MagicMock())
    def test_expire_and_purge_called(
        self,
        mock_db: MagicMock,
        _mock_client: MagicMock,
        mock_expire: MagicMock,
        mock_purge: MagicMock,
        _mock_subs: MagicMock,
        _mock_search: MagicMock,
        _mock_eval: MagicMock,
        _mock_email: MagicMock,
    ) -> None:
        from daily_task import main

        result = main()

        mock_expire.assert_called_once_with(mock_db.return_value)
        mock_purge.assert_called_once_with(mock_db.return_value, older_than_days=7)
        assert result == 0


class TestDailyTaskNoSubscribers:
    """When no active subscribers exist, exit early without searching."""

    @patch(f"{_PATCH_PREFIX}.send_daily_digest")
    @patch(f"{_PATCH_PREFIX}.search_all_queries")
    @patch(f"{_PATCH_PREFIX}.get_active_subscribers_with_profiles", return_value=[])
    @patch(f"{_PATCH_PREFIX}.purge_inactive_subscribers", return_value=0)
    @patch(f"{_PATCH_PREFIX}.expire_subscriptions", return_value=0)
    @patch(f"{_PATCH_PREFIX}.create_client", return_value=MagicMock())
    @patch(f"{_PATCH_PREFIX}.get_db", return_value=MagicMock())
    def test_no_subscribers_skips_search(
        self,
        _mock_db: MagicMock,
        _mock_client: MagicMock,
        _mock_expire: MagicMock,
        _mock_purge: MagicMock,
        _mock_subs: MagicMock,
        mock_search: MagicMock,
        _mock_email: MagicMock,
    ) -> None:
        from daily_task import main

        result = main()

        mock_search.assert_not_called()
        assert result == 0


class TestDailyTaskQueryAggregation:
    """Queries from multiple subscribers for the same location are deduped."""

    @patch(f"{_PATCH_PREFIX}.send_daily_digest")
    @patch(f"{_PATCH_PREFIX}.log_sent_jobs")
    @patch(f"{_PATCH_PREFIX}.evaluate_all_jobs", return_value=[])
    @patch(f"{_PATCH_PREFIX}.get_sent_job_ids", return_value=set())
    @patch(f"{_PATCH_PREFIX}.get_job_ids_by_urls", return_value={})
    @patch(f"{_PATCH_PREFIX}.upsert_jobs")
    @patch(f"{_PATCH_PREFIX}.search_all_queries")
    @patch(f"{_PATCH_PREFIX}.get_active_subscribers_with_profiles")
    @patch(f"{_PATCH_PREFIX}.purge_inactive_subscribers", return_value=0)
    @patch(f"{_PATCH_PREFIX}.expire_subscriptions", return_value=0)
    @patch(f"{_PATCH_PREFIX}.create_client", return_value=MagicMock())
    @patch(f"{_PATCH_PREFIX}.get_db", return_value=MagicMock())
    def test_deduplicates_queries_per_location(
        self,
        _mock_db: MagicMock,
        _mock_client: MagicMock,
        _mock_expire: MagicMock,
        _mock_purge: MagicMock,
        mock_subs: MagicMock,
        mock_search: MagicMock,
        _mock_upsert: MagicMock,
        _mock_job_ids: MagicMock,
        _mock_sent_ids: MagicMock,
        _mock_eval: MagicMock,
        _mock_log: MagicMock,
        _mock_email: MagicMock,
    ) -> None:
        from daily_task import main

        # Two subscribers share the same query for the same location
        sub1 = _make_subscriber(sub_id="sub-001", queries=["Python Developer München", "Backend Engineer"])
        sub2 = _make_subscriber(sub_id="sub-002", queries=["Python Developer München", "Data Engineer"])
        mock_subs.return_value = [sub1, sub2]
        mock_search.return_value = []

        main()

        # search_all_queries should be called once per location
        # with combined unique queries
        assert mock_search.call_count == 1
        search_queries = mock_search.call_args[0][0]
        assert set(search_queries) == {"Backend Engineer", "Data Engineer", "Python Developer München"}


class TestDailyTaskFullPipeline:
    """End-to-end: subscriber with unseen jobs gets evaluated and emailed."""

    @patch.dict("os.environ", {"APP_URL": "https://app.example.com"}, clear=False)
    @patch(f"{_PATCH_PREFIX}.issue_unsubscribe_token", return_value=True)
    @patch(f"{_PATCH_PREFIX}.send_daily_digest")
    @patch(f"{_PATCH_PREFIX}.log_sent_jobs")
    @patch(f"{_PATCH_PREFIX}.get_sent_job_ids", return_value=set())
    @patch(f"{_PATCH_PREFIX}.get_job_ids_by_urls")
    @patch(f"{_PATCH_PREFIX}.upsert_jobs")
    @patch(f"{_PATCH_PREFIX}.evaluate_all_jobs")
    @patch(f"{_PATCH_PREFIX}.search_all_queries")
    @patch(f"{_PATCH_PREFIX}.get_active_subscribers_with_profiles")
    @patch(f"{_PATCH_PREFIX}.purge_inactive_subscribers", return_value=0)
    @patch(f"{_PATCH_PREFIX}.expire_subscriptions", return_value=0)
    @patch(f"{_PATCH_PREFIX}.create_client", return_value=MagicMock())
    @patch(f"{_PATCH_PREFIX}.get_db", return_value=MagicMock())
    def test_subscriber_receives_digest(
        self,
        _mock_db: MagicMock,
        _mock_client: MagicMock,
        _mock_expire: MagicMock,
        _mock_purge: MagicMock,
        mock_subs: MagicMock,
        mock_search: MagicMock,
        mock_eval: MagicMock,
        mock_upsert: MagicMock,
        mock_job_ids: MagicMock,
        mock_sent_ids: MagicMock,
        mock_log: MagicMock,
        mock_email: MagicMock,
        mock_unsub_token: MagicMock,
    ) -> None:
        from daily_task import main

        job1 = _make_job_listing("Python Dev", "Corp GmbH", "https://example.com/job/1")
        job2 = _make_job_listing("Go Dev", "StartupXYZ", "https://example.com/job/2")

        sub = _make_subscriber(sub_id="sub-001", min_score=70)
        mock_subs.return_value = [sub]
        mock_search.return_value = [job1, job2]

        ej1 = _make_evaluated_job(job1, score=85)
        ej2 = _make_evaluated_job(job2, score=45)
        mock_eval.return_value = [ej1, ej2]

        mock_job_ids.return_value = {
            "https://example.com/job/1": "db-uuid-1",
            "https://example.com/job/2": "db-uuid-2",
        }

        main()

        # Email should be sent with only the high-score job
        mock_email.assert_called_once()
        email_args = mock_email.call_args
        assert email_args[0][0] == "user@example.com"  # first positional = email
        email_jobs = email_args[0][1]  # second positional = jobs list
        assert len(email_jobs) == 1
        assert email_jobs[0]["score"] == 85

    @patch.dict("os.environ", {"APP_URL": "https://app.example.com"}, clear=False)
    @patch(f"{_PATCH_PREFIX}.issue_unsubscribe_token", return_value=True)
    @patch(f"{_PATCH_PREFIX}.send_daily_digest")
    @patch(f"{_PATCH_PREFIX}.log_sent_jobs")
    @patch(f"{_PATCH_PREFIX}.get_sent_job_ids", return_value=set())
    @patch(f"{_PATCH_PREFIX}.get_job_ids_by_urls")
    @patch(f"{_PATCH_PREFIX}.upsert_jobs")
    @patch(f"{_PATCH_PREFIX}.evaluate_all_jobs")
    @patch(f"{_PATCH_PREFIX}.search_all_queries")
    @patch(f"{_PATCH_PREFIX}.get_active_subscribers_with_profiles")
    @patch(f"{_PATCH_PREFIX}.purge_inactive_subscribers", return_value=0)
    @patch(f"{_PATCH_PREFIX}.expire_subscriptions", return_value=0)
    @patch(f"{_PATCH_PREFIX}.create_client", return_value=MagicMock())
    @patch(f"{_PATCH_PREFIX}.get_db", return_value=MagicMock())
    def test_all_evaluated_jobs_logged(
        self,
        _mock_db: MagicMock,
        _mock_client: MagicMock,
        _mock_expire: MagicMock,
        _mock_purge: MagicMock,
        mock_subs: MagicMock,
        mock_search: MagicMock,
        mock_eval: MagicMock,
        mock_upsert: MagicMock,
        mock_job_ids: MagicMock,
        mock_sent_ids: MagicMock,
        mock_log: MagicMock,
        mock_email: MagicMock,
        mock_unsub_token: MagicMock,
    ) -> None:
        """Both high and low score jobs should be logged to avoid re-evaluation."""
        from daily_task import main

        job1 = _make_job_listing("Python Dev", "Corp", "https://example.com/j1")
        job2 = _make_job_listing("Go Dev", "Startup", "https://example.com/j2")

        mock_subs.return_value = [_make_subscriber(min_score=70)]
        mock_search.return_value = [job1, job2]
        mock_eval.return_value = [
            _make_evaluated_job(job1, score=90),
            _make_evaluated_job(job2, score=30),
        ]
        mock_job_ids.return_value = {
            "https://example.com/j1": "db-1",
            "https://example.com/j2": "db-2",
        }

        main()

        # log_sent_jobs should include BOTH job IDs (even the low-score one)
        mock_log.assert_called_once()
        logged_ids = mock_log.call_args[0][2]  # third positional arg = job_ids list
        assert set(logged_ids) == {"db-1", "db-2"}


class TestDailyTaskNoNewJobs:
    """When a subscriber has no unseen jobs, skip evaluation and email."""

    @patch(f"{_PATCH_PREFIX}.send_daily_digest")
    @patch(f"{_PATCH_PREFIX}.evaluate_all_jobs")
    @patch(f"{_PATCH_PREFIX}.log_sent_jobs")
    @patch(f"{_PATCH_PREFIX}.get_sent_job_ids")
    @patch(f"{_PATCH_PREFIX}.get_job_ids_by_urls")
    @patch(f"{_PATCH_PREFIX}.upsert_jobs")
    @patch(f"{_PATCH_PREFIX}.search_all_queries")
    @patch(f"{_PATCH_PREFIX}.get_active_subscribers_with_profiles")
    @patch(f"{_PATCH_PREFIX}.purge_inactive_subscribers", return_value=0)
    @patch(f"{_PATCH_PREFIX}.expire_subscriptions", return_value=0)
    @patch(f"{_PATCH_PREFIX}.create_client", return_value=MagicMock())
    @patch(f"{_PATCH_PREFIX}.get_db", return_value=MagicMock())
    def test_no_unseen_jobs_skips_email(
        self,
        _mock_db: MagicMock,
        _mock_client: MagicMock,
        _mock_expire: MagicMock,
        _mock_purge: MagicMock,
        mock_subs: MagicMock,
        mock_search: MagicMock,
        mock_upsert: MagicMock,
        mock_job_ids: MagicMock,
        mock_sent_ids: MagicMock,
        _mock_log: MagicMock,
        mock_eval: MagicMock,
        mock_email: MagicMock,
    ) -> None:
        from daily_task import main

        job = _make_job_listing(url="https://example.com/j1")
        mock_subs.return_value = [_make_subscriber()]
        mock_search.return_value = [job]
        mock_job_ids.return_value = {"https://example.com/j1": "db-1"}
        # All jobs already sent
        mock_sent_ids.return_value = {"db-1"}

        main()

        mock_eval.assert_not_called()
        mock_email.assert_not_called()


class TestDailyTaskNoGoodMatches:
    """When all evaluated jobs score below min_score, log but don't email."""

    @patch(f"{_PATCH_PREFIX}.send_daily_digest")
    @patch(f"{_PATCH_PREFIX}.log_sent_jobs")
    @patch(f"{_PATCH_PREFIX}.get_sent_job_ids", return_value=set())
    @patch(f"{_PATCH_PREFIX}.get_job_ids_by_urls")
    @patch(f"{_PATCH_PREFIX}.upsert_jobs")
    @patch(f"{_PATCH_PREFIX}.evaluate_all_jobs")
    @patch(f"{_PATCH_PREFIX}.search_all_queries")
    @patch(f"{_PATCH_PREFIX}.get_active_subscribers_with_profiles")
    @patch(f"{_PATCH_PREFIX}.purge_inactive_subscribers", return_value=0)
    @patch(f"{_PATCH_PREFIX}.expire_subscriptions", return_value=0)
    @patch(f"{_PATCH_PREFIX}.create_client", return_value=MagicMock())
    @patch(f"{_PATCH_PREFIX}.get_db", return_value=MagicMock())
    def test_low_scores_logged_but_not_emailed(
        self,
        _mock_db: MagicMock,
        _mock_client: MagicMock,
        _mock_expire: MagicMock,
        _mock_purge: MagicMock,
        mock_subs: MagicMock,
        mock_search: MagicMock,
        mock_eval: MagicMock,
        mock_upsert: MagicMock,
        mock_job_ids: MagicMock,
        _mock_sent_ids: MagicMock,
        mock_log: MagicMock,
        mock_email: MagicMock,
    ) -> None:
        from daily_task import main

        job = _make_job_listing(url="https://example.com/j1")
        mock_subs.return_value = [_make_subscriber(min_score=80)]
        mock_search.return_value = [job]
        mock_eval.return_value = [_make_evaluated_job(job, score=50)]
        mock_job_ids.return_value = {"https://example.com/j1": "db-1"}

        main()

        mock_email.assert_not_called()
        # But the job should still be logged
        mock_log.assert_called_once()


class TestDailyTaskNoProfileJson:
    """Subscriber with no stored profile_json should be skipped."""

    @patch(f"{_PATCH_PREFIX}.send_daily_digest")
    @patch(f"{_PATCH_PREFIX}.evaluate_all_jobs")
    @patch(f"{_PATCH_PREFIX}.log_sent_jobs")
    @patch(f"{_PATCH_PREFIX}.get_sent_job_ids", return_value=set())
    @patch(f"{_PATCH_PREFIX}.get_job_ids_by_urls")
    @patch(f"{_PATCH_PREFIX}.upsert_jobs")
    @patch(f"{_PATCH_PREFIX}.search_all_queries")
    @patch(f"{_PATCH_PREFIX}.get_active_subscribers_with_profiles")
    @patch(f"{_PATCH_PREFIX}.purge_inactive_subscribers", return_value=0)
    @patch(f"{_PATCH_PREFIX}.expire_subscriptions", return_value=0)
    @patch(f"{_PATCH_PREFIX}.create_client", return_value=MagicMock())
    @patch(f"{_PATCH_PREFIX}.get_db", return_value=MagicMock())
    def test_missing_profile_skips_subscriber(
        self,
        _mock_db: MagicMock,
        _mock_client: MagicMock,
        _mock_expire: MagicMock,
        _mock_purge: MagicMock,
        mock_subs: MagicMock,
        mock_search: MagicMock,
        mock_upsert: MagicMock,
        mock_job_ids: MagicMock,
        _mock_sent_ids: MagicMock,
        _mock_log: MagicMock,
        mock_eval: MagicMock,
        mock_email: MagicMock,
    ) -> None:
        from daily_task import main

        sub = _make_subscriber()
        sub["profile_json"] = None  # no profile
        mock_subs.return_value = [sub]
        mock_search.return_value = [_make_job_listing()]
        mock_job_ids.return_value = {"https://example.com/job/1": "db-1"}

        main()

        mock_eval.assert_not_called()
        mock_email.assert_not_called()
