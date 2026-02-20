"""Tests for stellenscout.search_agent — pure helper functions."""

import pytest

from stellenscout.search_agent import _infer_gl, _localise_query, _parse_job_results


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
