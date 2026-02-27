"""Shared pytest fixtures for Immermatch tests."""

from pathlib import Path

import pytest

from immermatch.models import (
    ApplyOption,
    CandidateProfile,
    EducationEntry,
    EvaluatedJob,
    JobEvaluation,
    JobListing,
    WorkEntry,
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
        work_history=[
            WorkEntry(
                title="Senior Software Engineer",
                company="FinPayments GmbH",
                start_date="2021-06",
                end_date=None,
                duration_months=56,
                skills_used=["Python", "Go", "Kubernetes", "AWS", "PostgreSQL"],
                description="Leading backend platform team, designing microservices architecture.",
            ),
            WorkEntry(
                title="Software Engineer",
                company="CloudCorp AG",
                start_date="2018-03",
                end_date="2021-05",
                duration_months=38,
                skills_used=["Python", "Docker", "React", "PostgreSQL"],
                description="Full-stack development of SaaS analytics platform.",
            ),
            WorkEntry(
                title="Software Engineering Intern",
                company="StartupXYZ",
                start_date="2017-06",
                end_date="2017-12",
                duration_months=6,
                skills_used=["Java", "Spring Boot"],
                description="Built REST APIs for internal tooling.",
            ),
        ],
        education_history=[
            EducationEntry(
                degree="MSc Computer Science",
                institution="TU Munich",
                start_date="2015-10",
                end_date="2018-02",
                status="completed",
            ),
            EducationEntry(
                degree="BSc Computer Science",
                institution="University of Stuttgart",
                start_date="2012-10",
                end_date="2015-09",
                status="completed",
            ),
        ],
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
