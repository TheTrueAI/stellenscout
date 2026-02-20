"""Shared pytest fixtures for StellenScout tests."""

from pathlib import Path

import pytest

from stellenscout.models import (
    ApplyOption,
    CandidateProfile,
    EvaluatedJob,
    JobEvaluation,
    JobListing,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture()
def sample_profile() -> CandidateProfile:
    return CandidateProfile(
        skills=["Python", "Go", "React", "Docker", "Kubernetes", "PostgreSQL", "AWS"],
        experience_level="Senior",
        years_of_experience=7,
        roles=["Senior Software Engineer", "Backend Developer", "Platform Engineer", "Tech Lead", "Softwareentwickler"],
        languages=["English Native", "German B2"],
        domain_expertise=["FinTech", "SaaS"],
        certifications=["AWS Solutions Architect"],
        education=["MSc Computer Science, TU Munich"],
        summary="Senior engineer with 7 years of experience in Python and Go microservices.",
    )


@pytest.fixture()
def sample_job() -> JobListing:
    return JobListing(
        title="Senior Python Developer",
        company_name="FinCorp GmbH",
        location="Munich, Germany",
        description="We are looking for a Senior Python Developer...",
        link="https://example.com/job/123",
        posted_at="2 days ago",
        apply_options=[
            ApplyOption(source="LinkedIn", url="https://linkedin.com/jobs/123"),
            ApplyOption(source="Company Website", url="https://fincorp.de/careers/123"),
        ],
    )


@pytest.fixture()
def sample_evaluation() -> JobEvaluation:
    return JobEvaluation(
        score=85,
        reasoning="Strong match for Python and microservices experience.",
        missing_skills=["Kafka"],
    )


@pytest.fixture()
def sample_evaluated_job(sample_job: JobListing, sample_evaluation: JobEvaluation) -> EvaluatedJob:
    return EvaluatedJob(job=sample_job, evaluation=sample_evaluation)
