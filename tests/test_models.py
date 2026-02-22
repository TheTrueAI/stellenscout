"""Tests for stellenscout.models — Pydantic model validation."""

import pytest
from pydantic import ValidationError

from stellenscout.models import (
    CandidateProfile,
    EducationEntry,
    JobEvaluation,
    JobListing,
    WorkEntry,
)


class TestWorkEntry:
    def test_valid_current_role(self):
        w = WorkEntry(
            title="Senior Dev",
            company="Corp",
            start_date="2022-01",
            end_date=None,
            duration_months=36,
            skills_used=["Python", "AWS"],
            description="Leading backend team.",
        )
        assert w.end_date is None
        assert w.duration_months == 36

    def test_valid_past_role(self):
        w = WorkEntry(
            title="Intern",
            company="Startup",
            start_date="2018",
            end_date="2018-06",
            duration_months=6,
            skills_used=["Java"],
        )
        assert w.end_date == "2018-06"
        assert w.description == ""

    def test_minimal(self):
        w = WorkEntry(title="Dev", company="Co", start_date="2020")
        assert w.skills_used == []
        assert w.duration_months is None

    def test_round_trip(self):
        w = WorkEntry(
            title="Dev",
            company="Co",
            start_date="2020",
            end_date="2022",
            duration_months=24,
            skills_used=["Python"],
            description="Stuff.",
        )
        assert WorkEntry(**w.model_dump()) == w


class TestEducationEntry:
    def test_completed(self):
        e = EducationEntry(
            degree="MSc CS",
            institution="TU Munich",
            start_date="2015-10",
            end_date="2018-02",
            status="completed",
        )
        assert e.status == "completed"

    def test_in_progress(self):
        e = EducationEntry(
            degree="MBA",
            institution="WHU",
            start_date="2024-09",
            end_date=None,
            status="in_progress",
        )
        assert e.end_date is None
        assert e.status == "in_progress"

    def test_dropped(self):
        e = EducationEntry(degree="BSc Physics", institution="LMU", status="dropped")
        assert e.status == "dropped"

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            EducationEntry(degree="BSc", institution="X", status="expelled")

    def test_defaults(self):
        e = EducationEntry(degree="BSc CS", institution="Uni")
        assert e.status == "completed"
        assert e.start_date is None
        assert e.end_date is None

    def test_round_trip(self):
        e = EducationEntry(
            degree="MSc CS",
            institution="TU Munich",
            start_date="2015",
            end_date="2018",
            status="completed",
        )
        assert EducationEntry(**e.model_dump()) == e


class TestCandidateProfile:
    def test_valid_full(self, sample_profile):
        assert sample_profile.experience_level == "Senior"
        assert len(sample_profile.skills) == 7
        assert len(sample_profile.work_history) == 3
        assert len(sample_profile.education_history) == 2

    def test_work_history_ordering(self, sample_profile):
        """Most recent role should be first."""
        assert sample_profile.work_history[0].end_date is None  # current role
        assert sample_profile.work_history[-1].title == "Software Engineering Intern"

    def test_education_history_status(self, sample_profile):
        for entry in sample_profile.education_history:
            assert entry.status == "completed"

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
        assert p.work_history == []
        assert p.education_history == []

    def test_backward_compat_no_history(self):
        """Old profiles without work_history/education_history still parse."""
        data = {
            "skills": ["Python"],
            "experience_level": "Mid",
            "years_of_experience": 3,
            "roles": ["Developer"],
            "languages": ["English Native"],
            "domain_expertise": ["SaaS"],
        }
        p = CandidateProfile(**data)
        assert p.work_history == []
        assert p.education_history == []

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
