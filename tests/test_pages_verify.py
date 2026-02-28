"""Tests for the verify page (Double Opt-In confirmation).

Tests the page logic by mocking all DB and emailer calls.
Uses Streamlit's AppTest framework to run the page script.
"""

from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

# Environment variables needed by the page (injected before st.secrets fallback)
_FAKE_ENV = {
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_KEY": "fake-anon-key",  # pragma: allowlist secret
    "SUPABASE_SERVICE_KEY": "fake-service-key",  # pragma: allowlist secret
    "RESEND_API_KEY": "fake-resend-key",  # pragma: allowlist secret
    "RESEND_FROM": "test@example.com",
    "APP_URL": "https://app.example.com",
    "IMPRESSUM_NAME": "Test GmbH",
    "IMPRESSUM_ADDRESS": "Test Str. 1, 12345 Berlin",
    "IMPRESSUM_EMAIL": "info@test.de",
}

PAGE_FILE = "immermatch/pages/verify.py"


def _build_app(token: str | None = None) -> AppTest:
    """Create an AppTest for the verify page with optional query token."""
    at = AppTest.from_file(PAGE_FILE)
    if token:
        at.query_params["token"] = token
    return at


class TestVerifyNoToken:
    """When no token is provided, the page should show a warning."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_missing_token_shows_warning(self, _mock_db: MagicMock) -> None:
        at = _build_app(token=None)
        at.run()

        assert len(at.warning) >= 1
        assert any("confirmation token" in w.value.lower() for w in at.warning)
        # No success or error messages
        assert len(at.success) == 0


class TestVerifyValidToken:
    """When a valid token is provided and confirm_subscriber returns a subscriber."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.emailer.send_welcome_email")
    @patch("immermatch.db.issue_unsubscribe_token", return_value=True)
    @patch("immermatch.db.set_subscriber_expiry", return_value=True)
    @patch(
        "immermatch.db.confirm_subscriber",
        return_value={
            "id": "sub-uuid-123",
            "email": "user@example.com",
            "target_location": "Munich, Germany",
        },
    )
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_valid_token_shows_success(
        self,
        _mock_db: MagicMock,
        _mock_confirm: MagicMock,
        _mock_expiry: MagicMock,
        _mock_unsub_token: MagicMock,
        _mock_welcome: MagicMock,
    ) -> None:
        at = _build_app(token="valid-token-abc")
        at.run()

        assert len(at.success) >= 1
        assert any("confirmed" in s.value.lower() for s in at.success)
        assert len(at.error) == 0

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.emailer.send_welcome_email")
    @patch("immermatch.db.issue_unsubscribe_token", return_value=True)
    @patch("immermatch.db.set_subscriber_expiry", return_value=True)
    @patch(
        "immermatch.db.confirm_subscriber",
        return_value={
            "id": "sub-uuid-123",
            "email": "user@example.com",
            "target_location": "Munich, Germany",
        },
    )
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_set_expiry_called(
        self,
        _mock_db: MagicMock,
        _mock_confirm: MagicMock,
        mock_expiry: MagicMock,
        _mock_unsub_token: MagicMock,
        _mock_welcome: MagicMock,
    ) -> None:
        at = _build_app(token="valid-token-abc")
        at.run()

        mock_expiry.assert_called_once()
        args = mock_expiry.call_args
        assert args[0][1] == "sub-uuid-123"  # subscriber id

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.emailer.send_welcome_email")
    @patch("immermatch.db.issue_unsubscribe_token", return_value=True)
    @patch("immermatch.db.set_subscriber_expiry", return_value=True)
    @patch(
        "immermatch.db.confirm_subscriber",
        return_value={
            "id": "sub-uuid-123",
            "email": "user@example.com",
            "target_location": "Munich, Germany",
        },
    )
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_welcome_email_sent(
        self,
        _mock_db: MagicMock,
        _mock_confirm: MagicMock,
        _mock_expiry: MagicMock,
        _mock_unsub_token: MagicMock,
        mock_welcome: MagicMock,
    ) -> None:
        at = _build_app(token="valid-token-abc")
        at.run()

        mock_welcome.assert_called_once()
        kwargs = mock_welcome.call_args[1]
        assert kwargs["email"] == "user@example.com"
        assert kwargs["target_location"] == "Munich, Germany"


class TestVerifyInvalidToken:
    """When confirm_subscriber returns None (expired/invalid token)."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.confirm_subscriber", return_value=None)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_invalid_token_shows_error(
        self,
        _mock_db: MagicMock,
        _mock_confirm: MagicMock,
    ) -> None:
        at = _build_app(token="expired-token")
        at.run()

        assert len(at.error) >= 1
        assert any("invalid" in e.value.lower() or "expired" in e.value.lower() for e in at.error)
        assert len(at.success) == 0


class TestVerifyDBError:
    """When confirm_subscriber raises an exception, show generic error."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.confirm_subscriber", side_effect=RuntimeError("DB down"))
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_db_error_shows_generic_message(
        self,
        _mock_db: MagicMock,
        _mock_confirm: MagicMock,
    ) -> None:
        at = _build_app(token="some-token")
        at.run()

        assert len(at.error) >= 1
        # Error should be generic, not leak exception details
        assert any("something went wrong" in e.value.lower() for e in at.error)

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.set_subscriber_expiry", return_value=False)
    @patch(
        "immermatch.db.confirm_subscriber",
        return_value={
            "id": "sub-uuid-123",
            "email": "user@example.com",
            "target_location": "Munich, Germany",
        },
    )
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_expiry_failure_shows_error(
        self,
        _mock_db: MagicMock,
        _mock_confirm: MagicMock,
        _mock_expiry: MagicMock,
    ) -> None:
        at = _build_app(token="some-token")
        at.run()

        assert len(at.error) >= 1
        assert len(at.success) == 0
