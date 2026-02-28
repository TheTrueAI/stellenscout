"""Tests for the Streamlit main app UI (app.py).

Uses Streamlit's AppTest framework to verify Phase A landing page renders,
the consent checkbox is present, and sidebar elements appear.
"""

from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

_FAKE_ENV = {
    "GOOGLE_API_KEY": "fake-google-key",  # pragma: allowlist secret
    "SERPAPI_KEY": "fake-serpapi-key",  # pragma: allowlist secret
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
