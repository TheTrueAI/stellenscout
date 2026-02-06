"""Pydantic models for StellenScout data structures."""

from typing import Literal
from pydantic import BaseModel, Field


class CandidateProfile(BaseModel):
    """Structured summary of a candidate's CV."""

    skills: list[str] = Field(
        description="All hard skills, tools, frameworks, and methodologies from the CV"
    )
    experience_level: Literal["Junior", "Mid", "Senior", "Lead", "CTO"] = Field(
        description="Seniority level based on experience"
    )
    years_of_experience: int = Field(
        default=0,
        description="Total years of professional experience"
    )
    roles: list[str] = Field(
        description="5 job titles the candidate is suited for, from most to least specific"
    )
    languages: list[str] = Field(
        description="Spoken languages with proficiency (e.g., 'German C1')"
    )
    domain_expertise: list[str] = Field(
        description="Key industries (e.g., Fintech, Automotive)"
    )
    certifications: list[str] = Field(
        default_factory=list,
        description="Professional certifications and accreditations"
    )
    education: list[str] = Field(
        default_factory=list,
        description="Degrees and fields of study (e.g., 'MSc Environmental Engineering')"
    )
    summary: str = Field(
        default="",
        description="2-3 sentence professional summary of the candidate"
    )


class JobListing(BaseModel):
    """A job listing from SerpApi."""

    title: str
    company_name: str
    location: str
    description: str = ""
    link: str = ""
    posted_at: str = ""


class JobEvaluation(BaseModel):
    """Evaluation result for a job listing against a CV."""

    score: int = Field(
        ge=0, le=100,
        description="Match score from 0-100"
    )
    reasoning: str = Field(
        description="Concise explanation of the score"
    )
    missing_skills: list[str] = Field(
        default_factory=list,
        description="Skills the candidate is missing for this role"
    )


class EvaluatedJob(BaseModel):
    """A job listing combined with its evaluation."""

    job: JobListing
    evaluation: JobEvaluation
