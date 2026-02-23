"""Tests for stellenscout.search_agent — pure helper functions and search_all_queries orchestration."""

import json
from unittest.mock import MagicMock, patch

import pytest

from stellenscout.models import ApplyOption, CandidateProfile, JobListing
from stellenscout.search_agent import (
    _infer_gl,
    _localise_query,
    _parse_job_results,
    generate_search_queries,
    profile_candidate,
    search_all_queries,
)


class TestInferGl:
    @pytest.mark.parametrize(
        "location, expected",
        [
            ("Munich, Germany", "de"),
            ("münchen", "de"),
            ("Vienna, Austria", "at"),
            ("Zurich, Switzerland", "ch"),
            ("London, UK", "uk"),
            ("Paris, France", "fr"),
            ("Amsterdam, Netherlands", "nl"),
            ("Warsaw, Poland", "pl"),
        ],
    )
    def test_known_locations(self, location: str, expected: str):
        assert _infer_gl(location) == expected

    def test_unknown_defaults_to_de(self):
        assert _infer_gl("Narnia") == "de"

    def test_case_insensitive(self):
        assert _infer_gl("BERLIN") == "de"


class TestLocaliseQuery:
    def test_munich_to_muenchen(self):
        assert _localise_query("Developer Munich") == "Developer München"

    def test_cologne_to_koeln(self):
        assert _localise_query("jobs Cologne") == "jobs Köln"

    def test_vienna_to_wien(self):
        assert _localise_query("Data Analyst Vienna") == "Data Analyst Wien"

    def test_no_match_unchanged(self):
        assert _localise_query("Python Developer Berlin") == "Python Developer Berlin"

    def test_case_insensitive(self):
        assert _localise_query("engineer MUNICH") == "engineer München"

    def test_multiple_cities(self):
        result = _localise_query("Munich or Vienna")
        assert "München" in result
        assert "Wien" in result


class TestParseJobResults:
    def test_valid_results(self):
        results = {
            "jobs_results": [
                {
                    "title": "Python Developer",
                    "company_name": "TechCo",
                    "location": "Berlin",
                    "description": "Great job.",
                    "apply_options": [
                        {"title": "LinkedIn", "link": "https://linkedin.com/jobs/1"},
                    ],
                },
            ]
        }
        jobs = _parse_job_results(results)
        assert len(jobs) == 1
        assert jobs[0].title == "Python Developer"
        assert jobs[0].company_name == "TechCo"
        assert len(jobs[0].apply_options) == 1

    def test_blocked_portal_filtered(self):
        results = {
            "jobs_results": [
                {
                    "title": "Dev",
                    "company_name": "Co",
                    "location": "Berlin",
                    "apply_options": [
                        {"title": "BeBee", "link": "https://bebee.com/jobs/1"},
                    ],
                },
            ]
        }
        jobs = _parse_job_results(results)
        # Job has no valid apply links after filtering → skipped
        assert len(jobs) == 0

    def test_mixed_portals_keeps_valid(self):
        results = {
            "jobs_results": [
                {
                    "title": "Dev",
                    "company_name": "Co",
                    "location": "Berlin",
                    "apply_options": [
                        {"title": "Jooble", "link": "https://jooble.org/jobs/1"},
                        {"title": "LinkedIn", "link": "https://linkedin.com/jobs/1"},
                    ],
                },
            ]
        }
        jobs = _parse_job_results(results)
        assert len(jobs) == 1
        assert len(jobs[0].apply_options) == 1
        assert jobs[0].apply_options[0].source == "LinkedIn"

    def test_empty_results(self):
        assert _parse_job_results({}) == []
        assert _parse_job_results({"jobs_results": []}) == []

    def test_highlights_in_description(self):
        results = {
            "jobs_results": [
                {
                    "title": "Dev",
                    "company_name": "Co",
                    "location": "Berlin",
                    "description": "Main desc.",
                    "highlights": [{"items": ["Skill: Python", "Skill: Docker"]}],
                    "apply_options": [
                        {"title": "Company", "link": "https://company.com/apply"},
                    ],
                },
            ]
        }
        jobs = _parse_job_results(results)
        assert "Main desc." in jobs[0].description
        assert "Skill: Python" in jobs[0].description


class TestSearchAllQueries:
    """Tests for search_all_queries() — mock search_jobs to test orchestration logic."""

    def _make_job(self, title: str, company: str = "Co") -> JobListing:
        return JobListing(
            title=title,
            company_name=company,
            location="Berlin",
            apply_options=[ApplyOption(source="LinkedIn", url="https://linkedin.com/1")],
        )

    @patch("stellenscout.search_agent.search_jobs")
    def test_appends_localised_location_to_query_without_one(self, mock_search: MagicMock):
        mock_search.return_value = [self._make_job("Dev")]

        search_all_queries(
            queries=["Python Developer"],
            location="Munich, Germany",
            min_unique_jobs=0,
        )

        # The query should have "München" appended (localised) and then localised again (no-op)
        actual_query = mock_search.call_args[0][0]
        assert "München" in actual_query

    @patch("stellenscout.search_agent.search_jobs")
    def test_does_not_double_append_location(self, mock_search: MagicMock):
        mock_search.return_value = [self._make_job("Dev")]

        search_all_queries(
            queries=["Python Developer München"],
            location="Munich, Germany",
            min_unique_jobs=0,
        )

        # Query already contains "münchen" (location keyword) so location should NOT be appended
        actual_query = mock_search.call_args[0][0]
        assert actual_query.count("München") == 1

    @patch("stellenscout.search_agent.search_jobs")
    def test_stops_early_when_min_unique_jobs_reached(self, mock_search: MagicMock):
        mock_search.return_value = [self._make_job("Unique Job")]

        results = search_all_queries(
            queries=["query1", "query2", "query3"],
            location="Berlin, Germany",
            min_unique_jobs=1,
        )

        # Should stop after first query yields 1 unique job
        assert mock_search.call_count == 1
        assert len(results) == 1


class TestLlmJsonRecovery:
    @patch("stellenscout.search_agent.call_gemini")
    def test_profile_candidate_retries_after_invalid_json(self, mock_call_gemini: MagicMock):
        valid_profile = {
            "skills": ["Python", "SQL"],
            "experience_level": "Mid",
            "years_of_experience": 4,
            "roles": [
                "Python Developer",
                "Backend Developer",
                "Software Engineer",
                "Entwickler",
                "Data Engineer",
            ],
            "languages": ["English C1"],
            "domain_expertise": ["SaaS"],
            "certifications": [],
            "education": ["BSc Computer Science"],
            "summary": "Backend-focused engineer with API and data experience.",
            "work_history": [],
            "education_history": [],
        }
        mock_call_gemini.side_effect = [
            '{"skills": ["Python"',
            json.dumps(valid_profile),
        ]

        result = profile_candidate(MagicMock(), "Sample CV")

        assert result.experience_level == "Mid"
        assert mock_call_gemini.call_count == 2

    @patch("stellenscout.search_agent.call_gemini")
    def test_generate_search_queries_retries_after_invalid_json(self, mock_call_gemini: MagicMock):
        profile = CandidateProfile(
            skills=["Python"],
            experience_level="Mid",
            years_of_experience=3,
            roles=["Backend Developer", "Python Developer", "Software Engineer", "Entwickler", "Engineer"],
            languages=["English C1"],
            domain_expertise=["SaaS"],
            certifications=[],
            education=[],
            summary="",
            work_history=[],
            education_history=[],
        )
        mock_call_gemini.side_effect = ["not json", '["python developer berlin", "backend berlin"]']

        queries = generate_search_queries(MagicMock(), profile, location="Berlin, Germany", num_queries=2)

        assert queries == ["python developer berlin", "backend berlin"]
        assert mock_call_gemini.call_count == 2

    @patch("stellenscout.search_agent.call_gemini")
    def test_profile_candidate_raises_after_all_retries_exhausted(self, mock_call_gemini: MagicMock):
        mock_call_gemini.side_effect = ["not json", "still not json", "also not json"]

        with pytest.raises(ValueError, match="Failed to generate a valid candidate profile JSON"):
            profile_candidate(MagicMock(), "Sample CV")

        assert mock_call_gemini.call_count == 3

    @patch("stellenscout.search_agent.call_gemini")
    def test_generate_search_queries_returns_empty_list_after_all_retries_fail(
        self, mock_call_gemini: MagicMock
    ):
        profile = CandidateProfile(
            skills=["Python"],
            experience_level="Mid",
            years_of_experience=3,
            roles=["Backend Developer", "Python Developer", "Software Engineer", "Entwickler", "Engineer"],
            languages=["English C1"],
            domain_expertise=["SaaS"],
            certifications=[],
            education=[],
            summary="",
            work_history=[],
            education_history=[],
        )
        mock_call_gemini.side_effect = ["not json", "still not json"]

        queries = generate_search_queries(MagicMock(), profile, location="Berlin, Germany", num_queries=2)

        assert queries == []
        assert mock_call_gemini.call_count == 2

    @patch("stellenscout.search_agent.call_gemini")
    def test_profile_candidate_retries_after_validation_error(self, mock_call_gemini: MagicMock):
        base_profile = {
            "skills": ["Python", "SQL"],
            "experience_level": "Mid",
            "years_of_experience": 4,
            "roles": [
                "Python Developer",
                "Backend Developer",
                "Software Engineer",
                "Entwickler",
                "Data Engineer",
            ],
            "languages": ["English C1"],
            "domain_expertise": ["SaaS"],
            "certifications": [],
            "education": ["BSc Computer Science"],
            "summary": "Backend-focused engineer with API and data experience.",
            "work_history": [],
            "education_history": [],
        }
        invalid_profile = dict(base_profile)
        invalid_profile["experience_level"] = "UltraSenior"

        mock_call_gemini.side_effect = [
            json.dumps(invalid_profile),
            json.dumps(base_profile),
        ]

        result = profile_candidate(MagicMock(), "Sample CV")

        assert result.experience_level == "Mid"
        assert mock_call_gemini.call_count == 2

    @patch("stellenscout.search_agent.call_gemini")
    def test_profile_candidate_retries_when_json_is_not_dict(self, mock_call_gemini: MagicMock):
        valid_profile = {
            "skills": ["Python", "SQL"],
            "experience_level": "Mid",
            "years_of_experience": 4,
            "roles": [
                "Python Developer",
                "Backend Developer",
                "Software Engineer",
                "Entwickler",
                "Data Engineer",
            ],
            "languages": ["English C1"],
            "domain_expertise": ["SaaS"],
            "certifications": [],
            "education": ["BSc Computer Science"],
            "summary": "Backend-focused engineer with API and data experience.",
            "work_history": [],
            "education_history": [],
        }
        mock_call_gemini.side_effect = [
            "[]",  # JSON array, not a dict -> raises ValueError("Expected a JSON object for profile")
            json.dumps(valid_profile),
        ]

        result = profile_candidate(MagicMock(), "Sample CV")

        assert result.experience_level == "Mid"
        assert mock_call_gemini.call_count == 2
