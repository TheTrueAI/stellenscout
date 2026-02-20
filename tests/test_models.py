"""Tests for stellenscout.models — Pydantic model validation."""

import pytest
from pydantic import ValidationError

from stellenscout.models import (
    CandidateProfile,
    JobEvaluation,
    JobListing,
)


class TestCandidateProfile:
    def test_valid_full(self, sample_profile):
        assert sample_profile.experience_level == "Senior"
        assert len(sample_profile.skills) == 7

    def test_defaults(self):
        p = CandidateProfile(
            skills=["Python"],
            experience_level="Junior",
            roles=["Developer"],
            languages=["English Native"],
            domain_expertise=["SaaS"],
        )
        assert p.years_of_experience == 0
        assert p.certifications == []
        assert p.education == []
        assert p.summary == ""

    def test_invalid_experience_level(self):
        with pytest.raises(ValidationError):
            CandidateProfile(
                skills=["Python"],
                experience_level="Wizard",
                roles=["Developer"],
                languages=["English"],
                domain_expertise=["SaaS"],
            )

    def test_round_trip(self, sample_profile):
        dumped = sample_profile.model_dump()
        restored = CandidateProfile(**dumped)
        assert restored == sample_profile


class TestJobEvaluation:
    def test_valid_boundaries(self):
        assert JobEvaluation(score=0, reasoning="No match.").score == 0
        assert JobEvaluation(score=100, reasoning="Perfect.").score == 100

    def test_score_too_low(self):
        with pytest.raises(ValidationError):
            JobEvaluation(score=-1, reasoning="Bad.")

    def test_score_too_high(self):
        with pytest.raises(ValidationError):
            JobEvaluation(score=101, reasoning="Too good.")

    def test_missing_skills_default(self):
        e = JobEvaluation(score=50, reasoning="OK.")
        assert e.missing_skills == []


class TestJobListing:
    def test_defaults(self):
        j = JobListing(title="Dev", company_name="Corp", location="Berlin")
        assert j.description == ""
        assert j.link == ""
        assert j.posted_at == ""
        assert j.apply_options == []


class TestEvaluatedJob:
    def test_nesting(self, sample_evaluated_job):
        assert sample_evaluated_job.job.title == "Senior Python Developer"
        assert sample_evaluated_job.evaluation.score == 85
