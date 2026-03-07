"""Tests for the Streamlit main app UI (app.py).

Uses Streamlit's AppTest framework to verify Phase A landing page renders,
the consent checkbox is present, and sidebar elements appear.
"""

from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

_FAKE_ENV = {
    "GOOGLE_API_KEY": "fake-google-key",  # pragma: allowlist secret
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_KEY": "fake-anon-key",  # pragma: allowlist secret
    "SUPABASE_SERVICE_KEY": "fake-service-key",  # pragma: allowlist secret
    "RESEND_API_KEY": "fake-resend-key",  # pragma: allowlist secret
    "RESEND_FROM": "test@example.com",
    "APP_URL": "https://app.example.com",
}

APP_FILE = "immermatch/app.py"


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
