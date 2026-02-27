"""Tests for immermatch.cache — file-based pipeline cache."""

from pathlib import Path

import pytest
from freezegun import freeze_time

from immermatch.cache import ResultCache, _hash
from immermatch.models import CandidateProfile, EvaluatedJob, JobEvaluation, JobListing


@pytest.fixture()
def cache(tmp_path: Path) -> ResultCache:
    return ResultCache(cache_dir=tmp_path)


@pytest.fixture()
def profile() -> CandidateProfile:
    return CandidateProfile(
        skills=["Python", "Docker"],
        experience_level="Senior",
        roles=["Backend Developer"],
        languages=["English Native"],
        domain_expertise=["SaaS"],
    )


class TestHash:
    def test_deterministic(self):
        assert _hash("hello") == _hash("hello")

    def test_different_input(self):
        assert _hash("hello") != _hash("world")


class TestProfileCache:
    def test_round_trip(self, cache: ResultCache, profile: CandidateProfile):
        cv = "my cv text"
        cache.save_profile(cv, profile)
        loaded = cache.load_profile(cv)
        assert loaded == profile

    def test_miss_on_different_cv(self, cache: ResultCache, profile: CandidateProfile):
        cache.save_profile("cv version 1", profile)
        assert cache.load_profile("cv version 2") is None

    def test_miss_when_empty(self, cache: ResultCache):
        assert cache.load_profile("anything") is None


class TestQueriesCache:
    def test_round_trip(self, cache: ResultCache, profile: CandidateProfile):
        queries = ["Python Munich", "Backend Developer"]
        cache.save_queries(profile, "Munich", queries)
        loaded = cache.load_queries(profile, "Munich")
        assert loaded == queries

    def test_miss_on_different_location(self, cache: ResultCache, profile: CandidateProfile):
        cache.save_queries(profile, "Munich", ["q1"])
        assert cache.load_queries(profile, "Berlin") is None

    def test_miss_on_different_profile(self, cache: ResultCache, profile: CandidateProfile):
        cache.save_queries(profile, "Munich", ["q1"])
        other = CandidateProfile(
            skills=["Java"],
            experience_level="Junior",
            roles=["Developer"],
            languages=["English Native"],
            domain_expertise=["SaaS"],
        )
        assert cache.load_queries(other, "Munich") is None


class TestJobsCache:
    @freeze_time("2026-02-20")
    def test_round_trip_same_day(self, cache: ResultCache):
        jobs = [JobListing(title="Dev", company_name="Corp", location="Berlin")]
        cache.save_jobs(jobs, "Berlin")
        loaded = cache.load_jobs("Berlin")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0].title == "Dev"

    @freeze_time("2026-02-20")
    def test_miss_next_day(self, cache: ResultCache):
        jobs = [JobListing(title="Dev", company_name="Corp", location="Berlin")]
        cache.save_jobs(jobs, "Berlin")

        with freeze_time("2026-02-21"):
            assert cache.load_jobs("Berlin") is None

    @freeze_time("2026-02-20")
    def test_merge_dedup(self, cache: ResultCache):
        cache.save_jobs([JobListing(title="Dev", company_name="Corp", location="Berlin")], "Berlin")
        cache.save_jobs(
            [
                JobListing(title="Dev", company_name="Corp", location="Berlin"),  # duplicate
                JobListing(title="PM", company_name="Corp", location="Berlin"),  # new
            ],
            "Berlin",
        )
        loaded = cache.load_jobs("Berlin")
        assert loaded is not None
        assert len(loaded) == 2

    @freeze_time("2026-02-20")
    def test_miss_on_different_location(self, cache: ResultCache):
        jobs = [JobListing(title="Dev", company_name="Corp", location="Berlin")]
        cache.save_jobs(jobs, "Berlin")
        assert cache.load_jobs("Munich") is None

    @freeze_time("2026-02-20")
    def test_location_change_resets_cache(self, cache: ResultCache):
        cache.save_jobs([JobListing(title="Dev", company_name="Corp", location="Berlin")], "Berlin")
        cache.save_jobs([JobListing(title="PM", company_name="Corp", location="Munich")], "Munich")
        loaded = cache.load_jobs("Munich")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0].title == "PM"

    @freeze_time("2026-02-20")
    def test_backward_compat_no_location_key(self, cache: ResultCache):
        """Old cache files without a 'location' key should be treated as location=''."""
        jobs = [JobListing(title="Dev", company_name="Corp", location="Berlin")]
        cache.save_jobs(jobs)  # location defaults to ""
        loaded = cache.load_jobs()  # location defaults to ""
        assert loaded is not None
        assert len(loaded) == 1


class TestEvaluationsCache:
    def test_round_trip(self, cache: ResultCache, profile: CandidateProfile):
        job = JobListing(title="Dev", company_name="Corp", location="Berlin")
        ev = JobEvaluation(score=80, reasoning="Good match.")
        evaluated = {"Dev|Corp": EvaluatedJob(job=job, evaluation=ev)}

        cache.save_evaluations(profile, evaluated)
        loaded = cache.load_evaluations(profile)
        assert "Dev|Corp" in loaded
        assert loaded["Dev|Corp"].evaluation.score == 80

    def test_miss_on_different_profile(self, cache: ResultCache, profile: CandidateProfile):
        job = JobListing(title="Dev", company_name="Corp", location="Berlin")
        ev = JobEvaluation(score=80, reasoning="Good match.")
        cache.save_evaluations(profile, {"Dev|Corp": EvaluatedJob(job=job, evaluation=ev)})

        other = CandidateProfile(
            skills=["Java"],
            experience_level="Junior",
            roles=["Developer"],
            languages=["English Native"],
            domain_expertise=["SaaS"],
        )
        assert cache.load_evaluations(other) == {}


class TestGetUnevaluatedJobs:
    def test_filters_already_evaluated(self, cache: ResultCache, profile: CandidateProfile):
        job1 = JobListing(title="Dev", company_name="Corp", location="Berlin")
        job2 = JobListing(title="PM", company_name="Corp", location="Berlin")
        ev = JobEvaluation(score=80, reasoning="Good.")
        cache.save_evaluations(profile, {"Dev|Corp": EvaluatedJob(job=job1, evaluation=ev)})

        new_jobs, cached = cache.get_unevaluated_jobs([job1, job2], profile)
        assert len(new_jobs) == 1
        assert new_jobs[0].title == "PM"
        assert "Dev|Corp" in cached
