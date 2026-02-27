"""Tests for immermatch.evaluator_agent — evaluate_job, evaluate_all_jobs, generate_summary."""

from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import ServerError

from immermatch.evaluator_agent import evaluate_all_jobs, evaluate_job, generate_summary
from immermatch.models import (
    CandidateProfile,
    EvaluatedJob,
    JobEvaluation,
    JobListing,
)


@pytest.fixture()
def mock_client() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def simple_profile() -> CandidateProfile:
    return CandidateProfile(
        skills=["Python", "Docker"],
        experience_level="Mid",
        years_of_experience=3,
        roles=["Backend Developer"],
        languages=["English Native"],
        domain_expertise=["SaaS"],
    )


@pytest.fixture()
def simple_job() -> JobListing:
    return JobListing(
        title="Python Dev",
        company_name="Acme",
        location="Berlin",
        description="Build stuff.",
    )


class TestEvaluateJob:
    """Tests for evaluate_job() — mock call_gemini + parse_json."""

    @patch("immermatch.evaluator_agent.parse_json")
    @patch("immermatch.evaluator_agent.call_gemini")
    def test_happy_path(self, mock_call: MagicMock, mock_parse: MagicMock, mock_client, simple_profile, simple_job):
        mock_call.return_value = '{"score": 82, "reasoning": "Good fit", "missing_skills": ["Go"]}'
        mock_parse.return_value = {"score": 82, "reasoning": "Good fit", "missing_skills": ["Go"]}

        result = evaluate_job(mock_client, simple_profile, simple_job)

        assert isinstance(result, JobEvaluation)
        assert result.score == 82
        assert result.reasoning == "Good fit"
        assert result.missing_skills == ["Go"]
        mock_call.assert_called_once()

    @patch("immermatch.evaluator_agent.call_gemini")
    def test_api_error_returns_fallback(self, mock_call: MagicMock, mock_client, simple_profile, simple_job):
        mock_call.side_effect = ServerError(503, {"error": "Service Unavailable"})

        result = evaluate_job(mock_client, simple_profile, simple_job)

        assert result.score == 50
        assert "API error" in result.reasoning

    @patch("immermatch.evaluator_agent.parse_json")
    @patch("immermatch.evaluator_agent.call_gemini")
    def test_parse_error_returns_fallback(
        self, mock_call: MagicMock, mock_parse: MagicMock, mock_client, simple_profile, simple_job
    ):
        mock_call.return_value = "not json"
        mock_parse.side_effect = ValueError("Could not parse")

        result = evaluate_job(mock_client, simple_profile, simple_job)

        assert result.score == 50
        assert "parse" in result.reasoning

    @patch("immermatch.evaluator_agent.parse_json")
    @patch("immermatch.evaluator_agent.call_gemini")
    def test_non_dict_response_returns_fallback(
        self, mock_call: MagicMock, mock_parse: MagicMock, mock_client, simple_profile, simple_job
    ):
        mock_call.return_value = "[1, 2, 3]"
        mock_parse.return_value = [1, 2, 3]

        result = evaluate_job(mock_client, simple_profile, simple_job)

        assert result.score == 50
        assert "unexpected" in result.reasoning


class TestEvaluateAllJobs:
    """Tests for evaluate_all_jobs() — mock evaluate_job."""

    @patch("immermatch.evaluator_agent.evaluate_job")
    def test_results_sorted_by_score_descending(self, mock_eval: MagicMock, mock_client, simple_profile):
        jobs = [
            JobListing(title="Job A", company_name="Co", location="Berlin"),
            JobListing(title="Job B", company_name="Co", location="Berlin"),
            JobListing(title="Job C", company_name="Co", location="Berlin"),
        ]
        mock_eval.side_effect = [
            JobEvaluation(score=40, reasoning="Low", missing_skills=[]),
            JobEvaluation(score=90, reasoning="High", missing_skills=[]),
            JobEvaluation(score=70, reasoning="Mid", missing_skills=[]),
        ]

        results = evaluate_all_jobs(mock_client, simple_profile, jobs, max_workers=1)

        scores = [r.evaluation.score for r in results]
        assert scores == [90, 70, 40]

    @patch("immermatch.evaluator_agent.evaluate_job")
    def test_progress_callback_called(self, mock_eval: MagicMock, mock_client, simple_profile):
        jobs = [
            JobListing(title="Job A", company_name="Co", location="Berlin"),
            JobListing(title="Job B", company_name="Co", location="Berlin"),
        ]
        mock_eval.return_value = JobEvaluation(score=75, reasoning="OK", missing_skills=[])
        progress_calls: list[tuple[int, int]] = []

        evaluate_all_jobs(
            mock_client,
            simple_profile,
            jobs,
            progress_callback=lambda current, total: progress_calls.append((current, total)),
            max_workers=1,
        )

        assert len(progress_calls) == 2
        assert all(total == 2 for _, total in progress_calls)
        assert sorted(c for c, _ in progress_calls) == [1, 2]

    @patch("immermatch.evaluator_agent.evaluate_job")
    def test_empty_job_list(self, mock_eval: MagicMock, mock_client, simple_profile):
        results = evaluate_all_jobs(mock_client, simple_profile, [])

        assert results == []
        mock_eval.assert_not_called()


class TestGenerateSummary:
    """Tests for generate_summary() — mock call_gemini, assert prompt content."""

    @patch("immermatch.evaluator_agent.call_gemini")
    def test_prompt_contains_score_distribution(self, mock_call: MagicMock, mock_client, simple_profile):
        evaluated_jobs = [
            EvaluatedJob(
                job=JobListing(title="Job A", company_name="Co", location="Berlin"),
                evaluation=JobEvaluation(score=85, reasoning="Great", missing_skills=[]),
            ),
            EvaluatedJob(
                job=JobListing(title="Job B", company_name="Co", location="Berlin"),
                evaluation=JobEvaluation(score=30, reasoning="Poor", missing_skills=["Java"]),
            ),
        ]
        mock_call.return_value = "Summary text"

        generate_summary(mock_client, simple_profile, evaluated_jobs)

        prompt = mock_call.call_args[0][1]
        # The bins format is "≥80: 1, 70-79: 0, 50-69: 0, <50: 1"
        assert "≥80: 1" in prompt
        assert "<50: 1" in prompt

    @patch("immermatch.evaluator_agent.call_gemini")
    def test_prompt_contains_missing_skills(self, mock_call: MagicMock, mock_client, simple_profile):
        evaluated_jobs = [
            EvaluatedJob(
                job=JobListing(title="Job A", company_name="Co", location="Berlin"),
                evaluation=JobEvaluation(score=70, reasoning="OK", missing_skills=["Kafka", "Go"]),
            ),
            EvaluatedJob(
                job=JobListing(title="Job B", company_name="Co", location="Berlin"),
                evaluation=JobEvaluation(score=60, reasoning="OK", missing_skills=["Kafka"]),
            ),
        ]
        mock_call.return_value = "Summary text"

        generate_summary(mock_client, simple_profile, evaluated_jobs)

        prompt = mock_call.call_args[0][1]
        assert "Kafka" in prompt
        assert "2 listings" in prompt
