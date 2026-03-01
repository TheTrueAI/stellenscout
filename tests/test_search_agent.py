"""Tests for immermatch.search_agent — pure helper functions and search_all_queries orchestration."""

import json
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from immermatch.models import ApplyOption, CandidateProfile, JobListing
from immermatch.search_agent import (
    _infer_gl,
    _is_remote_only,
    _localise_query,
    _parse_job_results,
    _provider_quota_source_key,
    generate_search_queries,
    profile_candidate,
    search_all_queries,
)
from immermatch.search_provider import CombinedSearchProvider


class TestIsRemoteOnly:
    @pytest.mark.parametrize(
        "location",
        ["remote", "Remote", "REMOTE", "worldwide", "global", "anywhere", "weltweit"],
    )
    def test_remote_tokens(self, location: str):
        assert _is_remote_only(location) is True

    @pytest.mark.parametrize(
        "location",
        ["Munich, Germany", "remote Germany", "Berlin", "Germany", ""],
    )
    def test_non_remote(self, location: str):
        assert _is_remote_only(location) is False


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

    def test_remote_returns_none(self):
        assert _infer_gl("remote") is None

    def test_worldwide_returns_none(self):
        assert _infer_gl("worldwide") is None

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

    def test_country_germany_to_deutschland(self):
        assert _localise_query("Jobs in Germany") == "Jobs in Deutschland"

    def test_country_austria_to_oesterreich(self):
        assert _localise_query("Jobs Austria") == "Jobs Österreich"

    def test_country_case_insensitive(self):
        assert "Deutschland" in _localise_query("jobs GERMANY")


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
    """Tests for search_all_queries() — mock provider to test orchestration logic."""

    def _make_job(self, title: str, company: str = "Co", location: str = "Berlin") -> JobListing:
        return JobListing(
            title=title,
            company_name=company,
            location=location,
            apply_options=[ApplyOption(source="LinkedIn", url="https://linkedin.com/1")],
        )

    def _make_provider(self, jobs: list[JobListing] | None = None) -> MagicMock:
        provider = MagicMock()
        provider.name = "test"
        provider.search.return_value = jobs if jobs is not None else []
        return provider

    def test_passes_query_and_location_to_provider(self):
        provider = self._make_provider([self._make_job("Dev")])

        search_all_queries(
            queries=["Python Developer"],
            location="Munich, Germany",
            min_unique_jobs=0,
            provider=provider,
        )

        provider.search.assert_called_once_with(
            "Python Developer",
            "Munich, Germany",
            max_results=10,
        )

    def test_deduplicates_by_title_company_and_location(self):
        provider = self._make_provider(
            [
                self._make_job("Dev", location="Berlin"),
                self._make_job("Dev", location="Berlin"),
                self._make_job("Dev", location="Munich"),
            ]
        )

        results = search_all_queries(
            queries=["query1", "query2"],
            location="Berlin",
            min_unique_jobs=0,
            provider=provider,
        )

        assert len(results) == 2

    def test_stops_early_when_min_unique_jobs_reached(self):
        provider = self._make_provider([self._make_job("Unique Job")])

        results = search_all_queries(
            queries=["query1", "query2", "query3"],
            location="Berlin, Germany",
            min_unique_jobs=1,
            provider=provider,
        )

        # Parallel dispatch: all futures may fire before early_stop takes effect
        # (mocks return instantly). The guarantee is correct dedup + results.
        assert len(results) == 1
        assert provider.search.call_count <= 3

    def test_on_progress_callback(self):
        provider = self._make_provider([self._make_job("Dev")])
        progress_calls: list[tuple] = []

        search_all_queries(
            queries=["query1"],
            location="Berlin",
            min_unique_jobs=0,
            provider=provider,
            on_progress=lambda *args: progress_calls.append(args),
        )

        assert len(progress_calls) == 1
        assert progress_calls[0] == (1, 1, 1)

    def test_on_jobs_found_callback(self):
        provider = self._make_provider([self._make_job("Dev")])
        found_batches: list[list[JobListing]] = []

        search_all_queries(
            queries=["query1"],
            location="Berlin",
            min_unique_jobs=0,
            provider=provider,
            on_jobs_found=lambda batch: found_batches.append(batch),
        )

        assert len(found_batches) == 1
        assert found_batches[0][0].title == "Dev"

    @patch("immermatch.search_agent.get_provider")
    def test_defaults_to_get_provider(self, mock_gp: MagicMock):
        """When no provider given, get_provider(location) is called."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = []
        mock_gp.return_value = mock_provider

        search_all_queries(queries=["test"], location="Berlin")

        mock_gp.assert_called_once_with("Berlin")

    def test_combined_provider_hard_quota_requires_30_each_before_stop(self):
        ba_provider = MagicMock()
        ba_provider.name = "Bundesagentur für Arbeit"
        ba_jobs = [self._make_job(f"BA {i}", company=f"BA Co {i}", location="Berlin") for i in range(30)]
        for job in ba_jobs:
            job.source = "bundesagentur"
        ba_provider.search.return_value = ba_jobs

        serp_provider = MagicMock()
        serp_provider.name = "SerpApi (Google Jobs)"
        serp_jobs = [self._make_job(f"SERP {i}", company=f"SERP Co {i}", location="Berlin") for i in range(30)]
        for job in serp_jobs:
            job.source = "serpapi"
        serp_provider.search.return_value = serp_jobs

        combined = CombinedSearchProvider([ba_provider, serp_provider])
        results = search_all_queries(
            queries=[
                "provider=Bundesagentur für Arbeit::Softwareentwickler",
                "provider=SerpApi (Google Jobs)::Python Developer Berlin",
            ],
            jobs_per_query=30,
            location="Berlin",
            min_unique_jobs=50,
            provider=combined,
        )

        assert len(results) == 60
        ba_count = len([job for job in results if job.source == "bundesagentur"])
        serp_count = len([job for job in results if job.source == "serpapi"])
        assert ba_count >= 30
        assert serp_count >= 30

    @patch("immermatch.search_agent.logger")
    def test_logs_source_counts(self, mock_logger: MagicMock):
        provider = self._make_provider(
            [
                self._make_job("BA Job", location="Berlin"),
                self._make_job("SERP Job", location="Munich"),
            ]
        )
        provider.search.return_value[0].source = "bundesagentur"
        provider.search.return_value[1].source = "serpapi"

        search_all_queries(
            queries=["query1"],
            location="Berlin",
            min_unique_jobs=0,
            provider=provider,
        )

        assert mock_logger.info.called
        logged_texts = " ".join(str(call.args) for call in mock_logger.info.call_args_list)
        assert "bundesagentur" in logged_texts
        assert "serpapi" in logged_texts

    def test_combined_provider_routes_query_to_target_provider(self):
        ba_provider = MagicMock()
        ba_provider.name = "Bundesagentur für Arbeit"
        ba_provider.search.return_value = []

        serp_provider = MagicMock()
        serp_provider.name = "SerpApi (Google Jobs)"
        serp_provider.search.return_value = [self._make_job("Dev", location="Berlin")]

        combined = CombinedSearchProvider([ba_provider, serp_provider])
        search_all_queries(
            queries=["provider=SerpApi (Google Jobs)::Python Developer Berlin"],
            location="Berlin",
            min_unique_jobs=0,
            provider=combined,
        )

        ba_provider.search.assert_not_called()
        serp_provider.search.assert_called_once_with("Python Developer Berlin", "Berlin", max_results=10)

    def test_provider_quota_source_key_prefers_source_id(self):
        class ThirdProvider:
            name: ClassVar[str] = "Third Provider"
            source_id: ClassVar[str] = "third-source"

        ba_provider = MagicMock()
        ba_provider.name = "Bundesagentur für Arbeit"

        serp_provider = MagicMock()
        serp_provider.name = "SerpApi (Google Jobs)"
        serp_provider.source_id = "serpapi"

        third_provider = ThirdProvider()

        assert _provider_quota_source_key(ba_provider) == "bundesagentur"
        assert _provider_quota_source_key(serp_provider) == "serpapi"
        assert _provider_quota_source_key(third_provider) == "third-source"

    def test_min_unique_zero_does_not_enable_combined_quota(self):
        ba_provider = MagicMock()
        ba_provider.name = "Bundesagentur für Arbeit"
        ba_provider.source_id = "bundesagentur"
        ba_jobs = [self._make_job(f"BA {i}", company=f"BA Co {i}", location="Berlin") for i in range(10)]
        for job in ba_jobs:
            job.source = "bundesagentur"
        ba_provider.search.return_value = ba_jobs

        serp_provider = MagicMock()
        serp_provider.name = "SerpApi (Google Jobs)"
        serp_provider.source_id = "serpapi"
        serp_jobs = [self._make_job(f"SERP {i}", company=f"SERP Co {i}", location="Berlin") for i in range(10)]
        for job in serp_jobs:
            job.source = "serpapi"
        serp_provider.search.return_value = serp_jobs

        combined = CombinedSearchProvider([ba_provider, serp_provider])
        results = search_all_queries(
            queries=["q1", "q2"],
            jobs_per_query=10,
            location="Berlin",
            min_unique_jobs=0,
            provider=combined,
        )

        assert len(results) == 10


class TestLlmJsonRecovery:
    @patch("immermatch.search_agent.call_gemini")
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

    @patch("immermatch.search_agent.call_gemini")
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
        provider = MagicMock()
        provider.name = "SerpApi (Google Jobs)"

        queries = generate_search_queries(
            MagicMock(),
            profile,
            location="Berlin, Germany",
            num_queries=2,
            provider=provider,
        )

        assert queries == ["python developer berlin", "backend berlin"]
        assert mock_call_gemini.call_count == 2

    @patch("immermatch.search_agent.call_gemini")
    def test_profile_candidate_raises_after_all_retries_exhausted(self, mock_call_gemini: MagicMock):
        mock_call_gemini.side_effect = ["not json", "still not json", "also not json"]

        with pytest.raises(ValueError, match="Failed to generate a valid candidate profile JSON"):
            profile_candidate(MagicMock(), "Sample CV")

        assert mock_call_gemini.call_count == 3

    @patch("immermatch.search_agent.call_gemini")
    def test_generate_search_queries_returns_empty_list_after_all_retries_fail(self, mock_call_gemini: MagicMock):
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
        provider = MagicMock()
        provider.name = "SerpApi (Google Jobs)"

        queries = generate_search_queries(
            MagicMock(),
            profile,
            location="Berlin, Germany",
            num_queries=2,
            provider=provider,
        )

        assert queries == []
        assert mock_call_gemini.call_count == 2

    @patch("immermatch.search_agent.call_gemini")
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

    @patch("immermatch.search_agent.call_gemini")
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


class TestGenerateSearchQueriesProviderPrompt:
    """Verify that generate_search_queries picks the right prompt per provider."""

    _PROFILE = CandidateProfile(
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

    @patch("immermatch.search_agent.call_gemini")
    def test_ba_provider_uses_ba_prompt(self, mock_call_gemini: MagicMock):
        mock_call_gemini.return_value = '["Softwareentwickler", "Python Developer"]'
        ba_provider = MagicMock()
        ba_provider.name = "Bundesagentur für Arbeit"

        generate_search_queries(
            MagicMock(),
            self._PROFILE,
            location="Berlin",
            num_queries=2,
            provider=ba_provider,
        )

        prompt_sent = mock_call_gemini.call_args[0][1]
        assert "Bundesagentur" in prompt_sent
        assert "Do NOT include any city" in prompt_sent

    @patch("immermatch.search_agent.call_gemini")
    def test_other_provider_uses_default_prompt(self, mock_call_gemini: MagicMock):
        mock_call_gemini.return_value = '["Python Developer Berlin"]'
        other_provider = MagicMock()
        other_provider.name = "SerpApi (Google Jobs)"

        generate_search_queries(
            MagicMock(),
            self._PROFILE,
            location="Berlin",
            num_queries=2,
            provider=other_provider,
        )

        prompt_sent = mock_call_gemini.call_args[0][1]
        assert "Google Jobs" in prompt_sent
        assert "LOCAL names" in prompt_sent

    @patch("immermatch.search_agent.call_gemini")
    def test_combined_provider_generates_queries_per_child_provider(self, mock_call_gemini: MagicMock):
        mock_call_gemini.side_effect = [
            '["Softwareentwickler", "Datenanalyst"]',
            '["Python Developer Berlin", "Data Engineer Berlin"]',
        ]

        ba_provider = MagicMock()
        ba_provider.name = "Bundesagentur für Arbeit"
        serp_provider = MagicMock()
        serp_provider.name = "SerpApi (Google Jobs)"
        combined = CombinedSearchProvider([ba_provider, serp_provider])

        queries = generate_search_queries(
            MagicMock(),
            self._PROFILE,
            location="Berlin",
            num_queries=4,
            provider=combined,
        )

        assert len(queries) == 4
        assert all(query.startswith("provider=") for query in queries)
        prompts_sent = [call.args[1] for call in mock_call_gemini.call_args_list]
        assert any("Bundesagentur" in prompt for prompt in prompts_sent)
        assert any("Google Jobs" in prompt for prompt in prompts_sent)
