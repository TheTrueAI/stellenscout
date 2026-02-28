"""Tests for the unsubscribe page.

Tests the page logic by mocking all DB calls.
Uses Streamlit's AppTest framework to run the page script.
"""

from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

_FAKE_ENV = {
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_KEY": "fake-anon-key",  # pragma: allowlist secret
    "SUPABASE_SERVICE_KEY": "fake-service-key",  # pragma: allowlist secret
}

PAGE_FILE = "immermatch/pages/unsubscribe.py"


def _build_app(token: str | None = None) -> AppTest:
    """Create an AppTest for the unsubscribe page with optional query token."""
    at = AppTest.from_file(PAGE_FILE)
    if token:
        at.query_params["token"] = token
    return at


class TestUnsubscribeNoToken:
    """When no unsubscribe token is provided."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_missing_token_shows_warning(self, _mock_db: MagicMock) -> None:
        at = _build_app(token=None)
        at.run()

        assert len(at.warning) >= 1
        assert any("unsubscribe" in w.value.lower() for w in at.warning)
        assert len(at.success) == 0


class TestUnsubscribeValidToken:
    """When a valid unsubscribe token is provided."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.deactivate_subscriber_by_token", return_value=True)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_valid_token_shows_success(
        self,
        _mock_db: MagicMock,
        _mock_deactivate: MagicMock,
    ) -> None:
        at = _build_app(token="valid-unsub-token")
        at.run()

        assert len(at.success) >= 1
        assert any("unsubscribed" in s.value.lower() for s in at.success)
        assert len(at.error) == 0

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.deactivate_subscriber_by_token", return_value=True)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_deactivate_called_with_token(
        self,
        _mock_db: MagicMock,
        mock_deactivate: MagicMock,
    ) -> None:
        at = _build_app(token="my-unsubscribe-token")
        at.run()

        mock_deactivate.assert_called_once()
        args = mock_deactivate.call_args[0]
        assert args[1] == "my-unsubscribe-token"

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.deactivate_subscriber_by_token", return_value=True)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_success_mentions_data_deletion(
        self,
        _mock_db: MagicMock,
        _mock_deactivate: MagicMock,
    ) -> None:
        at = _build_app(token="valid-token")
        at.run()

        assert any("deleted" in s.value.lower() for s in at.success)


class TestUnsubscribeInvalidToken:
    """When deactivate_subscriber_by_token returns False (already cancelled / not found)."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.deactivate_subscriber_by_token", return_value=False)
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_invalid_token_shows_info(
        self,
        _mock_db: MagicMock,
        _mock_deactivate: MagicMock,
    ) -> None:
        at = _build_app(token="old-token")
        at.run()

        assert len(at.info) >= 1
        assert any("cancelled" in i.value.lower() or "does not exist" in i.value.lower() for i in at.info)
        assert len(at.success) == 0


class TestUnsubscribeDBError:
    """When the DB call raises an exception, show generic error."""

    @patch.dict("os.environ", _FAKE_ENV, clear=False)
    @patch("immermatch.db.deactivate_subscriber_by_token", side_effect=RuntimeError("DB down"))
    @patch("immermatch.db.get_admin_client", return_value=MagicMock())
    def test_db_error_shows_generic_message(
        self,
        _mock_db: MagicMock,
        _mock_deactivate: MagicMock,
    ) -> None:
        at = _build_app(token="some-token")
        at.run()

        assert len(at.error) >= 1
        assert any("something went wrong" in e.value.lower() for e in at.error)
