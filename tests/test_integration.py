"""Integration tests for the full Immermatch pipeline.

Tests the end-to-end flow: CV text → profile_candidate → generate_search_queries
→ search_all_queries → evaluate_all_jobs → generate_summary, with all external
services (Gemini API, SerpApi) mocked.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from immermatch.cv_parser import extract_text
from immermatch.evaluator_agent import evaluate_all_jobs, generate_summary
from immermatch.models import (
    ApplyOption,
    CandidateProfile,
    EvaluatedJob,
    JobEvaluation,
    JobListing,
)
from immermatch.search_agent import (
    generate_search_queries,
    profile_candidate,
    search_all_queries,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Mock response data
# ---------------------------------------------------------------------------

TECH_PROFILE_JSON = json.dumps(
    {
        "skills": ["Python", "Go", "React", "Node.js", "Docker", "Kubernetes", "PostgreSQL", "AWS"],
        "experience_level": "Senior",
        "years_of_experience": 7,
        "roles": [
            "Senior Software Engineer",
            "Backend Developer",
            "Platform Engineer",
            "Tech Lead",
            "Softwareentwickler",
        ],
        "languages": ["English Native", "German B2"],
        "domain_expertise": ["FinTech", "SaaS", "Cloud Infrastructure"],
        "certifications": [],
        "education": ["MSc Computer Science, TU Munich"],
        "summary": "Senior engineer with 7 years in Python/Go microservices and cloud infrastructure.",
        "work_history": [
            {
                "title": "Senior Developer",
                "company": "TechCorp GmbH",
                "start_date": "2019",
                "end_date": None,
                "duration_months": 60,
                "skills_used": ["Python", "Go", "Kubernetes", "AWS"],
                "description": "Led backend platform team building microservices.",
            },
            {
                "title": "Junior Developer",
                "company": "StartupXYZ",
                "start_date": "2017",
                "end_date": "2019",
                "duration_months": 24,
                "skills_used": ["React", "Node.js"],
                "description": "Full-stack development for SaaS analytics.",
            },
        ],
        "education_history": [
            {
                "degree": "MSc Computer Science",
                "institution": "TU Munich",
                "start_date": "2015",
                "end_date": "2017",
                "status": "completed",
            }
        ],
    }
)

SUSTAINABILITY_PROFILE_JSON = json.dumps(
    {
        "skills": [
            "CSRD",
            "ESRS",
            "GRI",
            "TCFD",
            "SBTi",
            "GHG Protocol",
            "ISO 14001",
            "ISO 14064",
            "LCA",
            "Carbon Accounting",
            "MATLAB",
            "Python",
            "Power BI",
            "AutoCAD",
            "ArcGIS",
            "HubSpot",
            "Agile Project Management",
            "Stakeholder Management",
        ],
        "experience_level": "Mid",
        "years_of_experience": 3,
        "roles": [
            "Sustainability Consultant",
            "ESG Analyst",
            "Environmental Engineer",
            "Climate Strategy Manager",
            "Nachhaltigkeitsberater",
        ],
        "languages": ["Urdu Native", "English C1/C2", "German B1/B2", "Hindi Spoken"],
        "domain_expertise": ["Sustainability", "Environmental Engineering", "Manufacturing", "Energy"],
        "certifications": [],
        "education": [
            "MSc Environmental Engineering, TU Munich",
            "BEng Urban and Infrastructure Planning, NED University",
        ],
        "summary": "Environmental engineer and sustainability strategist with 3+ years guiding corporations toward Net Zero.",
        "work_history": [
            {
                "title": "Sustainability Consultant",
                "company": "Global Climate GmbH",
                "start_date": "2023-05",
                "end_date": None,
                "duration_months": 33,
                "skills_used": ["CSRD", "ESRS", "GRI", "GHG Protocol", "SBTi", "ISO 14001"],
                "description": "Key account management and sustainability reporting for global corporations.",
            },
            {
                "title": "Research Assistant",
                "company": "Technical University of Munich",
                "start_date": "2021-05",
                "end_date": "2023-04",
                "duration_months": 23,
                "skills_used": ["MATLAB", "Python", "LCA"],
                "description": "Environmental modeling and circular economy research.",
            },
        ],
        "education_history": [
            {
                "degree": "MSc Environmental Engineering",
                "institution": "Technical University of Munich",
                "start_date": "2019",
                "end_date": "2023",
                "status": "completed",
            },
            {
                "degree": "BEng Urban and Infrastructure Planning",
                "institution": "NED University",
                "start_date": "2014",
                "end_date": "2018",
                "status": "completed",
            },
        ],
    }
)

QUERIES_JSON = json.dumps(
    [
        "Senior Software Engineer München",
        "Backend Developer München",
        "Platform Engineer München",
        "Python Developer München",
        "Go Developer München",
        "Softwareentwickler München",
        "DevOps Engineer München",
        "Cloud Engineer München",
        "Tech Lead München",
        "Kubernetes Engineer München",
        "Software Architect München",
        "Backend Developer remote",
        "Python Developer Deutschland",
        "Microservices Engineer",
        "SaaS Developer",
        "FinTech Developer",
        "Full Stack Developer",
        "Infrastructure Engineer",
        "Site Reliability Engineer",
        "Engineering Manager",
    ]
)

SUSTAINABILITY_QUERIES_JSON = json.dumps(
    [
        "Sustainability Consultant München",
        "ESG Analyst München",
        "Nachhaltigkeitsberater München",
        "Environmental Engineer München",
        "Climate Strategy München",
        "Carbon Accounting München",
        "CSRD Berater München",
        "LCA Consultant München",
        "Sustainability Manager München",
        "ESG Reporting München",
        "Sustainability Consultant remote",
        "Environmental Engineer Deutschland",
        "GHG Analyst",
        "Circular Economy Consultant",
        "Climate Risk Analyst",
        "Net Zero Strategist",
        "Sustainability Reporting",
        "Environmental Consultant",
        "Green Energy Analyst",
        "ISO 14001 Auditor",
    ]
)

# Realistic job listings used across tests
MOCK_JOBS: list[JobListing] = [
    JobListing(
        title="Senior Python Developer",
        company_name="FinCorp GmbH",
        location="Munich, Germany",
        description="We need a Senior Python Developer with 5+ years experience in microservices, Docker, and AWS.",
        link="https://example.com/job/1",
        posted_at="2 days ago",
        apply_options=[ApplyOption(source="LinkedIn", url="https://linkedin.com/jobs/1")],
    ),
    JobListing(
        title="Backend Engineer (Go/Python)",
        company_name="CloudScale AG",
        location="Munich, Germany",
        description="Join our platform team. Must know Go, Python, Kubernetes. German B2 required.",
        link="https://example.com/job/2",
        posted_at="1 week ago",
        apply_options=[ApplyOption(source="Company Website", url="https://cloudscale.de/jobs/2")],
    ),
    JobListing(
        title="DevOps Engineer",
        company_name="DataFlow GmbH",
        location="Berlin, Germany",
        description="Looking for a DevOps engineer with strong Kubernetes, Terraform, and CI/CD experience.",
        link="https://example.com/job/3",
        posted_at="3 days ago",
        apply_options=[ApplyOption(source="LinkedIn", url="https://linkedin.com/jobs/3")],
    ),
    JobListing(
        title="Full Stack Developer",
        company_name="StartupHub",
        location="Remote, Germany",
        description="React + Node.js full-stack role. Junior-friendly, 2+ years experience.",
        link="https://example.com/job/4",
        posted_at="5 days ago",
        apply_options=[ApplyOption(source="Indeed", url="https://indeed.com/jobs/4")],
    ),
    JobListing(
        title="Platform Engineer",
        company_name="MegaTech Corp",
        location="Munich, Germany",
        description="Design and maintain cloud platform on AWS/GCP. Python, Go, Terraform required. German C1.",
        link="https://example.com/job/5",
        posted_at="1 day ago",
        apply_options=[ApplyOption(source="Company Website", url="https://megatech.com/careers/5")],
    ),
]

# Pre-defined evaluation responses with varied scores
EVAL_RESPONSES: list[dict] = [
    {
        "score": 90,
        "reasoning": "Strong Python/Go match, microservices and AWS experience aligns well.",
        "missing_skills": ["Terraform"],
    },
    {
        "score": 85,
        "reasoning": "Good Go/Python fit, Kubernetes experience matches. German B2 meets requirement.",
        "missing_skills": [],
    },
    {
        "score": 60,
        "reasoning": "DevOps skills present but candidate is more backend-focused. Missing Terraform.",
        "missing_skills": ["Terraform", "CI/CD pipelines"],
    },
    {
        "score": 40,
        "reasoning": "Junior role mismatch for senior candidate. React/Node are secondary skills.",
        "missing_skills": [],
    },
    {
        "score": 75,
        "reasoning": "Platform skills match well but German C1 requirement not met (candidate B2).",
        "missing_skills": ["German C1", "Terraform"],
    },
]

SUMMARY_RESPONSE = """## 🎯 Market Overview
You're in a strong position! Out of 5 evaluated jobs, 2 are excellent matches (≥80) and 1 is a good fit. The Munich tech market has solid demand for your Python/Go backend skills.

## 📊 Skill Gaps
- Terraform (appears in 2 listings)
- CI/CD pipelines (appears in 1 listing)
- German C1 (appears in 1 listing)

## 💡 Career Advice
Consider getting Terraform certified — it appears in 40% of your matches. Your German B2 is close to C1; a language course could unlock more senior platform roles."""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tech_cv_text() -> str:
    """Load the tech CV fixture."""
    return extract_text(str(FIXTURES_DIR / "sample.md"))


@pytest.fixture()
def sustainability_cv_text() -> str:
    """Load the sustainability/climate CV fixture."""
    return extract_text(str(FIXTURES_DIR / "sustainability_cv.md"))


@pytest.fixture()
def mock_client() -> MagicMock:
    """A mock Gemini client (never actually called — we patch call_gemini)."""
    return MagicMock()


def _query_provider() -> MagicMock:
    provider = MagicMock()
    provider.name = "Bundesagentur für Arbeit"
    return provider


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullPipelineTechCV:
    """End-to-end pipeline with the tech CV (sample.md)."""

    @patch("immermatch.evaluator_agent.call_gemini")
    @patch("immermatch.search_agent.call_gemini")
    def test_full_pipeline_happy_path(
        self,
        mock_search_gemini: MagicMock,
        mock_eval_gemini: MagicMock,
        mock_client: MagicMock,
        tech_cv_text: str,
    ) -> None:
        """Run the entire pipeline and verify outputs at each stage."""
        # --- Arrange ---
        # search_agent.call_gemini: 1st call → profile, 2nd call → queries
        mock_search_gemini.side_effect = [TECH_PROFILE_JSON, QUERIES_JSON]

        # Build a mock provider whose search() returns jobs in batches
        mock_provider = MagicMock()
        mock_provider.name = "test"
        mock_provider.search.side_effect = (
            [
                MOCK_JOBS[:2],  # query 1 → 2 jobs
                MOCK_JOBS[2:4],  # query 2 → 2 jobs
                MOCK_JOBS[4:],  # query 3 → 1 job
            ]
            + [[] for _ in range(17)]
        )  # remaining queries → empty

        # evaluator_agent.call_gemini: 5 eval calls + 1 summary call
        mock_eval_gemini.side_effect = [json.dumps(resp) for resp in EVAL_RESPONSES] + [SUMMARY_RESPONSE]

        # --- Act: Stage 1 — Profile ---
        profile = profile_candidate(mock_client, tech_cv_text)
        assert isinstance(profile, CandidateProfile)
        assert profile.experience_level == "Senior"
        assert "Python" in profile.skills
        assert len(profile.work_history) == 2

        # --- Act: Stage 2 — Queries ---
        queries = generate_search_queries(mock_client, profile, "Munich, Germany", provider=_query_provider())
        assert isinstance(queries, list)
        assert len(queries) == 20

        # --- Act: Stage 3 — Search ---
        jobs = search_all_queries(
            queries,
            jobs_per_query=10,
            location="Munich, Germany",
            min_unique_jobs=0,
            provider=mock_provider,
        )
        assert len(jobs) == 5
        assert all(isinstance(j, JobListing) for j in jobs)

        # --- Act: Stage 4 — Evaluate ---
        evaluated = evaluate_all_jobs(mock_client, profile, jobs, max_workers=2)
        assert len(evaluated) == 5
        assert all(isinstance(e, EvaluatedJob) for e in evaluated)
        # Sorted descending by score
        scores = [e.evaluation.score for e in evaluated]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] == 90  # highest
        assert scores[-1] == 40  # lowest

        # --- Act: Stage 5 — Summary ---
        summary = generate_summary(mock_client, profile, evaluated)
        assert isinstance(summary, str)
        assert len(summary) > 50


@pytest.mark.integration
class TestFullPipelineSustainabilityCV:
    """End-to-end pipeline with the non-tech sustainability CV."""

    @patch("immermatch.evaluator_agent.call_gemini")
    @patch("immermatch.search_agent.call_gemini")
    def test_full_pipeline_non_tech_cv(
        self,
        mock_search_gemini: MagicMock,
        mock_eval_gemini: MagicMock,
        mock_client: MagicMock,
        sustainability_cv_text: str,
    ) -> None:
        """Non-tech CV produces a valid profile with environmental skills."""
        mock_search_gemini.side_effect = [SUSTAINABILITY_PROFILE_JSON, SUSTAINABILITY_QUERIES_JSON]

        sustainability_jobs = [
            JobListing(
                title="Sustainability Consultant",
                company_name="GreenTech GmbH",
                location="Munich, Germany",
                description="CSRD reporting, GHG accounting, SBTi targets. German B2 required.",
                link="https://example.com/green/1",
                posted_at="1 day ago",
                apply_options=[ApplyOption(source="LinkedIn", url="https://linkedin.com/jobs/g1")],
            ),
            JobListing(
                title="ESG Analyst",
                company_name="SustainCorp",
                location="Munich, Germany",
                description="ESG data analysis, Power BI dashboards, GRI reporting.",
                link="https://example.com/green/2",
                posted_at="3 days ago",
                apply_options=[ApplyOption(source="Company Website", url="https://sustaincorp.de/jobs/2")],
            ),
        ]
        mock_provider = MagicMock()
        mock_provider.name = "test"
        mock_provider.search.side_effect = [sustainability_jobs] + [[] for _ in range(19)]

        eval_responses = [
            json.dumps({"score": 88, "reasoning": "Excellent CSRD/GHG match.", "missing_skills": []}),
            json.dumps({"score": 72, "reasoning": "Good ESG fit, Power BI match.", "missing_skills": ["SQL"]}),
        ]
        mock_eval_gemini.side_effect = eval_responses + ["Great market fit for sustainability roles."]

        # Run full pipeline
        profile = profile_candidate(mock_client, sustainability_cv_text)
        assert "CSRD" in profile.skills
        assert "GHG Protocol" in profile.skills
        assert profile.experience_level == "Mid"
        assert any("Sustainability" in r for r in profile.roles)

        queries = generate_search_queries(mock_client, profile, "Munich, Germany", provider=_query_provider())
        assert len(queries) == 20

        jobs = search_all_queries(
            queries,
            jobs_per_query=10,
            location="Munich, Germany",
            min_unique_jobs=0,
            provider=mock_provider,
        )
        assert len(jobs) == 2

        evaluated = evaluate_all_jobs(mock_client, profile, jobs, max_workers=2)
        assert len(evaluated) == 2
        assert evaluated[0].evaluation.score == 88

        summary = generate_summary(mock_client, profile, evaluated)
        assert isinstance(summary, str)


@pytest.mark.integration
class TestProfileOutputStructure:
    """Verify the profile output structure for different CV types."""

    @patch("immermatch.search_agent.call_gemini")
    def test_tech_profile_has_all_fields(
        self,
        mock_gemini: MagicMock,
        mock_client: MagicMock,
        tech_cv_text: str,
    ) -> None:
        """Profile extracted from tech CV has all required fields populated."""
        mock_gemini.return_value = TECH_PROFILE_JSON

        profile = profile_candidate(mock_client, tech_cv_text)

        assert len(profile.skills) >= 5
        assert profile.experience_level in ("Junior", "Mid", "Senior", "Lead", "CTO")
        assert profile.years_of_experience > 0
        assert len(profile.roles) >= 3
        assert len(profile.languages) >= 1
        assert len(profile.domain_expertise) >= 1
        assert profile.summary != ""
        assert len(profile.work_history) >= 1
        assert all(w.title for w in profile.work_history)
        assert all(w.company for w in profile.work_history)
        assert len(profile.education_history) >= 1

    @patch("immermatch.search_agent.call_gemini")
    def test_sustainability_profile_has_all_fields(
        self,
        mock_gemini: MagicMock,
        mock_client: MagicMock,
        sustainability_cv_text: str,
    ) -> None:
        """Profile from non-tech CV also has all required fields populated."""
        mock_gemini.return_value = SUSTAINABILITY_PROFILE_JSON

        profile = profile_candidate(mock_client, sustainability_cv_text)

        assert len(profile.skills) >= 10
        assert profile.experience_level == "Mid"
        assert len(profile.work_history) >= 2
        assert len(profile.education_history) >= 2
        assert any("Environmental" in e.degree for e in profile.education_history)


@pytest.mark.integration
class TestQueryGeneration:
    """Verify query generation integrates with the profile stage."""

    @patch("immermatch.search_agent.call_gemini")
    def test_queries_are_strings_and_correct_count(
        self,
        mock_gemini: MagicMock,
        mock_client: MagicMock,
        tech_cv_text: str,
    ) -> None:
        """generate_search_queries returns the expected number of string queries."""
        mock_gemini.side_effect = [TECH_PROFILE_JSON, QUERIES_JSON]

        profile = profile_candidate(mock_client, tech_cv_text)
        queries = generate_search_queries(mock_client, profile, "Munich, Germany", provider=_query_provider())

        assert len(queries) == 20
        assert all(isinstance(q, str) for q in queries)
        assert all(len(q) > 0 for q in queries)


@pytest.mark.integration
class TestSearchDeduplication:
    """Verify search_all_queries deduplicates overlapping results."""

    def test_duplicate_jobs_across_queries_are_merged(self) -> None:
        """Jobs with the same title+company from different queries appear only once."""
        duplicate_job = JobListing(
            title="Senior Python Developer",
            company_name="FinCorp GmbH",
            location="Munich, Germany",
            description="Duplicate listing.",
            link="https://example.com/job/dup",
            apply_options=[ApplyOption(source="LinkedIn", url="https://linkedin.com/dup")],
        )
        unique_job = JobListing(
            title="Go Developer",
            company_name="UniqueCo",
            location="Munich, Germany",
            description="Unique listing.",
            link="https://example.com/job/unique",
            apply_options=[ApplyOption(source="LinkedIn", url="https://linkedin.com/unique")],
        )

        # Three queries all return the same duplicate + one unique in the second
        mock_provider = MagicMock()
        mock_provider.name = "test"
        mock_provider.search.side_effect = [
            [duplicate_job],
            [duplicate_job, unique_job],
            [duplicate_job],
        ]

        jobs = search_all_queries(
            ["query1", "query2", "query3"],
            jobs_per_query=10,
            location="Munich, Germany",
            min_unique_jobs=0,
            provider=mock_provider,
        )

        assert len(jobs) == 2
        titles = {j.title for j in jobs}
        assert "Senior Python Developer" in titles
        assert "Go Developer" in titles


@pytest.mark.integration
class TestEvaluationScoring:
    """Verify evaluation scoring and sorting across multiple jobs."""

    @patch("immermatch.evaluator_agent.call_gemini")
    def test_evaluation_sorted_descending(
        self,
        mock_gemini: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        """evaluate_all_jobs returns results sorted by score descending."""
        shuffled_scores = [60, 90, 75, 40, 85]
        mock_gemini.side_effect = [
            json.dumps({"score": s, "reasoning": f"Score {s}.", "missing_skills": []}) for s in shuffled_scores
        ]

        profile = CandidateProfile(**json.loads(TECH_PROFILE_JSON))
        evaluated = evaluate_all_jobs(mock_client, profile, MOCK_JOBS, max_workers=1)

        scores = [e.evaluation.score for e in evaluated]
        assert scores == [90, 85, 75, 60, 40]

    @patch("immermatch.evaluator_agent.call_gemini")
    def test_evaluation_fallback_on_api_error(
        self,
        mock_gemini: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        """A failing evaluation gets fallback score=50; others complete normally."""
        from google.genai.errors import ServerError

        mock_gemini.side_effect = [
            json.dumps({"score": 90, "reasoning": "Great match.", "missing_skills": []}),
            ServerError(503, {"error": "Service unavailable"}),  # This one fails
            json.dumps({"score": 70, "reasoning": "Good match.", "missing_skills": ["Docker"]}),
        ]

        profile = CandidateProfile(**json.loads(TECH_PROFILE_JSON))
        evaluated = evaluate_all_jobs(mock_client, profile, MOCK_JOBS[:3], max_workers=1)

        assert len(evaluated) == 3
        scores = [e.evaluation.score for e in evaluated]
        assert 50 in scores  # fallback score
        assert 90 in scores
        assert 70 in scores


@pytest.mark.integration
class TestSummaryGeneration:
    """Verify generate_summary receives correctly pre-processed data."""

    @patch("immermatch.evaluator_agent.call_gemini")
    def test_summary_prompt_contains_score_distribution(
        self,
        mock_gemini: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        """The summary prompt includes score distribution and missing skills."""
        mock_gemini.return_value = SUMMARY_RESPONSE

        profile = CandidateProfile(**json.loads(TECH_PROFILE_JSON))
        evaluated = [EvaluatedJob(job=MOCK_JOBS[i], evaluation=JobEvaluation(**EVAL_RESPONSES[i])) for i in range(5)]
        evaluated.sort(key=lambda x: x.evaluation.score, reverse=True)

        summary = generate_summary(mock_client, profile, evaluated)

        assert isinstance(summary, str)
        assert len(summary) > 20

        # Verify the prompt sent to Gemini contains expected elements
        call_args = mock_gemini.call_args
        prompt = call_args[0][1]  # second positional arg is prompt
        assert "Score Distribution" in prompt
        assert "≥80" in prompt
        assert "Terraform" in prompt  # most common missing skill
        assert "FinCorp GmbH" in prompt  # top match company


@pytest.mark.integration
class TestEmptySearchResults:
    """Verify the pipeline handles empty search results gracefully."""

    @patch("immermatch.evaluator_agent.call_gemini")
    @patch("immermatch.search_agent.call_gemini")
    def test_empty_search_produces_empty_evaluations(
        self,
        mock_search_gemini: MagicMock,
        mock_eval_gemini: MagicMock,
        mock_client: MagicMock,
        tech_cv_text: str,
    ) -> None:
        """When search returns no jobs, evaluate and summary still work."""
        mock_search_gemini.side_effect = [TECH_PROFILE_JSON, QUERIES_JSON]
        # Summary for empty results
        mock_eval_gemini.return_value = "No strong matches found. Consider broadening your search."

        # All searches return empty
        mock_provider = MagicMock()
        mock_provider.name = "test"
        mock_provider.search.return_value = []

        profile = profile_candidate(mock_client, tech_cv_text)
        queries = generate_search_queries(mock_client, profile, "Munich, Germany", provider=_query_provider())
        jobs = search_all_queries(
            queries,
            jobs_per_query=10,
            location="Munich, Germany",
            min_unique_jobs=0,
            provider=mock_provider,
        )

        assert jobs == []

        evaluated = evaluate_all_jobs(mock_client, profile, jobs, max_workers=1)
        assert evaluated == []

        summary = generate_summary(mock_client, profile, evaluated)
        assert isinstance(summary, str)
        assert len(summary) > 0


@pytest.mark.integration
class TestDataFlowBetweenStages:
    """Verify that data produced by earlier stages reaches later stages."""

    @patch("immermatch.evaluator_agent.call_gemini")
    @patch("immermatch.search_agent.call_gemini")
    def test_cv_data_flows_through_all_stages(
        self,
        mock_search_gemini: MagicMock,
        mock_eval_gemini: MagicMock,
        mock_client: MagicMock,
        tech_cv_text: str,
    ) -> None:
        """Data from the CV reaches the profile, queries, and evaluation prompts."""
        mock_search_gemini.side_effect = [TECH_PROFILE_JSON, QUERIES_JSON]
        mock_eval_gemini.side_effect = [
            json.dumps(EVAL_RESPONSES[0]),
            SUMMARY_RESPONSE,
        ]

        mock_provider = MagicMock()
        mock_provider.name = "test"
        mock_provider.search.side_effect = [MOCK_JOBS[:1]] + [[] for _ in range(19)]

        # Stage 1: Profile — verify CV text was sent to Gemini
        profile = profile_candidate(mock_client, tech_cv_text)
        profile_prompt = mock_search_gemini.call_args_list[0][0][1]  # 2nd positional arg
        assert "Python" in profile_prompt  # CV contains Python
        assert "TechCorp" in profile_prompt or "John Doe" in profile_prompt

        # Stage 2: Queries — verify profile data was sent to Gemini
        queries = generate_search_queries(mock_client, profile, "Munich, Germany", provider=_query_provider())
        query_prompt = mock_search_gemini.call_args_list[1][0][1]
        assert "Senior Software Engineer" in query_prompt  # from profile.roles
        assert "Python" in query_prompt  # from profile.skills
        assert "Munich" in query_prompt  # location passed through

        # Stage 3: Search
        jobs = search_all_queries(
            queries,
            jobs_per_query=10,
            location="Munich, Germany",
            min_unique_jobs=0,
            provider=mock_provider,
        )
        assert len(jobs) == 1

        # Stage 4: Evaluate — verify profile data is in the evaluation prompt
        evaluated = evaluate_all_jobs(mock_client, profile, jobs, max_workers=1)
        eval_prompt = mock_eval_gemini.call_args_list[0][0][1]
        assert "Python" in eval_prompt  # profile skills
        assert "Senior" in eval_prompt  # experience level
        assert "Senior Python Developer" in eval_prompt  # job title from MOCK_JOBS[0]
        assert "FinCorp GmbH" in eval_prompt  # job company from MOCK_JOBS[0]

        # Stage 5: Summary — verify evaluated data is in the summary prompt
        generate_summary(mock_client, profile, evaluated)
        summary_prompt = mock_eval_gemini.call_args_list[1][0][1]
        assert "Score Distribution" in summary_prompt
        assert "90" in summary_prompt  # the score from our eval
