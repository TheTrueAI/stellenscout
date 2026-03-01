"""Pydantic models for Immermatch data structures."""

from typing import Literal

from pydantic import BaseModel, Field


class WorkEntry(BaseModel):
    """A single work-experience entry with temporal context."""

    title: str = Field(description="Job title held")
    company: str = Field(description="Employer / organisation name")
    start_date: str = Field(description="Start date, e.g. '2020-03' or '2020'")
    end_date: str | None = Field(default=None, description="End date, or null if this is the current role")
    duration_months: int | None = Field(
        default=None, description="Estimated duration in months (useful when dates are vague)"
    )
    skills_used: list[str] = Field(default_factory=list, description="Key skills exercised in this role")
    description: str = Field(default="", description="One-sentence summary of what was done")


class EducationEntry(BaseModel):
    """A single education entry with completion status."""

    degree: str = Field(description="Degree name, e.g. 'MSc Computer Science'")
    institution: str = Field(default="", description="University or school name")
    start_date: str | None = Field(default=None, description="Start date if available")
    end_date: str | None = Field(default=None, description="End date / graduation date, null if ongoing")
    status: Literal["completed", "in_progress", "dropped"] = Field(
        default="completed", description="Whether the degree was completed, is in progress, or was dropped"
    )


class CandidateProfile(BaseModel):
    """Structured summary of a candidate's CV."""

    skills: list[str] = Field(description="All hard skills, tools, frameworks, and methodologies from the CV")
    experience_level: Literal["Junior", "Mid", "Senior", "Lead", "CTO"] = Field(
        description="Seniority level based on experience"
    )
    years_of_experience: int = Field(default=0, description="Total years of professional experience")
    roles: list[str] = Field(description="5 job titles the candidate is suited for, from most to least specific")
    languages: list[str] = Field(description="Spoken languages with proficiency (e.g., 'German C1')")
    domain_expertise: list[str] = Field(description="Key industries (e.g., Fintech, Automotive)")
    certifications: list[str] = Field(
        default_factory=list, description="Professional certifications and accreditations"
    )
    education: list[str] = Field(
        default_factory=list, description="Degrees and fields of study (e.g., 'MSc Environmental Engineering')"
    )
    summary: str = Field(default="", description="2-3 sentence professional summary of the candidate")
    work_history: list[WorkEntry] = Field(
        default_factory=list,
        description="Chronological work experience, most recent first",
    )
    education_history: list[EducationEntry] = Field(
        default_factory=list,
        description="Education entries with completion status",
    )


class ApplyOption(BaseModel):
    """An apply option for a job (e.g., LinkedIn, company website)."""

    source: str = Field(description="Source name (e.g., 'LinkedIn', 'Company Website')")
    url: str = Field(description="Direct application URL")


class JobListing(BaseModel):
    """A job listing returned by a search provider."""

    title: str
    company_name: str
    location: str
    description: str = ""
    link: str = ""
    posted_at: str = ""
    source: str = Field(default="", description="Search provider that produced this listing (e.g. 'bundesagentur')")
    apply_options: list[ApplyOption] = Field(
        default_factory=list, description="List of direct application links (LinkedIn, company site, etc.)"
    )


class JobEvaluation(BaseModel):
    """Evaluation result for a job listing against a CV."""

    score: int = Field(ge=0, le=100, description="Match score from 0-100")
    reasoning: str = Field(description="Concise explanation of the score")
    missing_skills: list[str] = Field(default_factory=list, description="Skills the candidate is missing for this role")


class EvaluatedJob(BaseModel):
    """A job listing combined with its evaluation."""

    job: JobListing
    evaluation: JobEvaluation
