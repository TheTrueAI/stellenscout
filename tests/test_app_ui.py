"""Tests for the Streamlit main app UI (app.py).

Uses Streamlit's AppTest framework to verify Phase A landing page renders,
the consent checkbox is present, and sidebar elements appear.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

from immermatch.cache import ResultCache
from immermatch.models import CandidateProfile
from immermatch.search_api.search_provider import get_provider, get_provider_fingerprint

_FAKE_ENV = {
    "GOOGLE_API_KEY": "fake-google-key",  # pragma: allowlist secret
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_KEY": "fake-anon-key",  # pragma: allowlist secret
    "SUPABASE_SERVICE_KEY": "fake-service-key",  # pragma: allowlist secret
    "RESEND_API_KEY": "fake-resend-key",  # pragma: allowlist secret
    "RESEND_FROM": "test@example.com",
    "APP_URL": "https://app.example.com",
}

APP_FILE = str(Path(__file__).resolve().parents[1] / "immermatch" / "app.py")


class TestPhaseALanding:
    """Phase A: no CV uploaded — landing page should render."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    @patch("immermatch.db.purge_inactive_subscribers", return_value=0)
    def test_app_loads_without_errors(self, _mock_purge: MagicMock, _mock_db: MagicMock) -> None:
        at = AppTest.from_file(APP_FILE)
        at.run()

        # The app should not raise any uncaught exceptions
        assert not at.exception, f"App raised exception: {at.exception}"

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    @patch("immermatch.db.purge_inactive_subscribers", return_value=0)
    def test_consent_checkbox_present(self, _mock_purge: MagicMock, _mock_db: MagicMock) -> None:
        at = AppTest.from_file(APP_FILE)
        at.run()

        # GDPR consent checkbox should be on the page
        checkboxes = at.checkbox
        consent_found = any(
            "consent" in (cb.label or "").lower() or "agree" in (cb.label or "").lower() for cb in checkboxes
        )
        assert consent_found, f"No consent checkbox found. Checkboxes: {[cb.label for cb in checkboxes]}"

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    @patch("immermatch.db.purge_inactive_subscribers", return_value=0)
    def test_sidebar_renders(self, _mock_purge: MagicMock, _mock_db: MagicMock) -> None:
        at = AppTest.from_file(APP_FILE)
        at.run()

        # Sidebar should have a slider (min score)
        assert len(at.slider) >= 1, "Expected at least one slider (min score) in sidebar"


def _simulate_pipeline_active(at: AppTest) -> None:
    """Set session state to Phase B with pipeline running (run_requested=True)."""
    at.session_state["cv_file_hash"] = "fakehash"
    at.session_state["cv_file_name"] = "test.pdf"
    at.session_state["cv_text"] = None
    at.session_state["profile"] = None
    at.session_state["run_requested"] = True
    at.session_state["location"] = "Munich"
    at.session_state["_cv_consent_given"] = True


def _sample_profile_for_pipeline() -> CandidateProfile:
    return CandidateProfile(
        skills=["Python"],
        experience_level="Mid",
        years_of_experience=3,
        roles=["Data Engineer"],
        languages=["English C1"],
        domain_expertise=["SaaS"],
        first_name="Test",
    )


class TestPhaseBTransitionClarity:
    """Phase B: after submit, location input and CTA should be disabled."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    @patch("immermatch.db.purge_inactive_subscribers", return_value=0)
    def test_form_disabled_when_run_requested(self, _mock_purge: MagicMock, _mock_db: MagicMock) -> None:
        """When run_requested is True, location input and submit button are disabled."""
        at = AppTest.from_file(APP_FILE)
        _simulate_pipeline_active(at)
        at.run()

        location_inputs = [ti for ti in at.text_input if "work" in (ti.label or "").lower()]
        assert location_inputs, "Location input not found"
        assert location_inputs[0].disabled, "Location input should be disabled when pipeline is active"

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    @patch("immermatch.db.purge_inactive_subscribers", return_value=0)
    def test_submit_label_changes_when_pipeline_active(self, _mock_purge: MagicMock, _mock_db: MagicMock) -> None:
        """Submit button shows phase-aware label when pipeline is active."""
        at = AppTest.from_file(APP_FILE)
        _simulate_pipeline_active(at)
        at.run()

        buttons = at.button
        finding_label_found = any("Finding jobs" in (b.label or "") for b in buttons)
        assert finding_label_found, (
            f"Expected 'Finding jobs' label on submit button. Button labels: {[b.label for b in buttons]}"
        )

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    @patch("immermatch.db.purge_inactive_subscribers", return_value=0)
    def test_sidebar_shows_location_when_run_requested(self, _mock_purge: MagicMock, _mock_db: MagicMock) -> None:
        """Sidebar displays location immediately after submit."""
        at = AppTest.from_file(APP_FILE)
        _simulate_pipeline_active(at)
        at.run()

        sidebar_text = " ".join(str(el.value) for el in at.sidebar.markdown)
        assert "Munich" in sidebar_text, f"Expected 'Munich' in sidebar. Sidebar text: {sidebar_text}"

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    @patch("immermatch.db.purge_inactive_subscribers", return_value=0)
    def test_sidebar_shows_pipeline_activity(self, _mock_purge: MagicMock, _mock_db: MagicMock) -> None:
        """Sidebar shows pipeline activity indicator when run_requested."""
        at = AppTest.from_file(APP_FILE)
        _simulate_pipeline_active(at)
        at.run()

        sidebar_text = " ".join(str(el.value) for el in at.sidebar.markdown)
        assert "Finding jobs" in sidebar_text, f"Expected pipeline activity in sidebar. Sidebar text: {sidebar_text}"

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("streamlit.rerun", return_value=None)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    @patch("immermatch.db.purge_inactive_subscribers", return_value=0)
    def test_queries_render_in_status_during_active_run(
        self,
        _mock_purge: MagicMock,
        _mock_db: MagicMock,
        _mock_rerun: MagicMock,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """Generated queries are persisted and rendered during active pipeline run."""
        monkeypatch.chdir(tmp_path)

        profile = _sample_profile_for_pipeline()
        queries = ["provider=Bundesagentur für Arbeit::Data Engineer"]
        cache = ResultCache(cache_dir=tmp_path / ".immermatch_cache" / "fakehash")
        provider_fingerprint = get_provider_fingerprint(get_provider("Munich"))
        cache.save_queries(profile, "Munich", queries, provider_fingerprint)
        cache.save_jobs([], "Munich")

        at = AppTest.from_file(APP_FILE)
        at.session_state["cv_file_hash"] = "fakehash"
        at.session_state["cv_file_name"] = "test.pdf"
        at.session_state["cv_text"] = "fake-cv-text"
        at.session_state["profile"] = profile
        at.session_state["run_requested"] = True
        at.session_state["location"] = "Munich"
        at.session_state["_cv_consent_given"] = True
        at.run()

        assert at.session_state["queries"] == queries
        markdown_text = " ".join(str(el.value) for el in at.markdown)
        assert "Data Engineer" in markdown_text, f"Expected query text in markdown output. Output: {markdown_text}"
