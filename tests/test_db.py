"""Tests for stellenscout.db — GDPR data lifecycle & subscriber management."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from stellenscout import db

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client():
    """Return a MagicMock that mimics the Supabase fluent builder pattern."""
    return MagicMock()


def _make_execute(data=None, error=None):
    """Build a fake .execute() return value with .data and optional .error."""
    result = MagicMock()
    result.data = data if data is not None else []
    if error is not None:
        result.error = error
    else:
        # Ensure getattr(result, "error", None) returns None by default
        del result.error
    return result


SUB_ID = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
TOKEN = "tok_confirm_abc123"
UNSUB_TOKEN = "tok_unsub_xyz789"


# ---------------------------------------------------------------------------
# TestDeleteSubscriberData
# ---------------------------------------------------------------------------


class TestDeleteSubscriberData:
    def test_wipes_pii_fields(self):
        client = _mock_client()
        # Make the full chain return a successful result
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{"id": SUB_ID}]
        )

        db.delete_subscriber_data(client, SUB_ID)

        payload = client.table.return_value.update.call_args[0][0]
        assert payload["profile_json"] is None
        assert payload["search_queries"] is None
        assert payload["target_location"] is None
        assert payload["min_score"] is None

    def test_targets_correct_subscriber(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{"id": SUB_ID}]
        )

        db.delete_subscriber_data(client, SUB_ID)

        client.table.return_value.update.return_value.eq.assert_called_once_with("id", SUB_ID)

    def test_returns_true_on_update(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{"id": SUB_ID}]
        )

        assert db.delete_subscriber_data(client, SUB_ID) is True

    def test_returns_false_on_no_match(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(data=[])

        assert db.delete_subscriber_data(client, SUB_ID) is False

    def test_raises_on_db_error(self):
        client = _mock_client()
        result = MagicMock()
        result.data = []
        result.error = "some db error"
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = result

        with pytest.raises(RuntimeError, match="Failed to delete subscriber data"):
            db.delete_subscriber_data(client, SUB_ID)


# ---------------------------------------------------------------------------
# TestDeactivateSubscriber
# ---------------------------------------------------------------------------


class TestDeactivateSubscriber:
    @freeze_time("2026-02-20T12:00:00Z")
    def test_sets_inactive_and_clears_tokens(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{"id": SUB_ID}]
        )

        db.deactivate_subscriber(client, SUB_ID)

        payload = client.table.return_value.update.call_args[0][0]
        assert payload["is_active"] is False
        assert payload["unsubscribed_at"] is not None
        assert payload["unsubscribe_token"] is None
        assert payload["unsubscribe_token_expires_at"] is None

    def test_returns_true_on_success(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{"id": SUB_ID}]
        )

        assert db.deactivate_subscriber(client, SUB_ID) is True

    def test_returns_false_on_no_match(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(data=[])

        assert db.deactivate_subscriber(client, SUB_ID) is False


# ---------------------------------------------------------------------------
# TestDeactivateSubscriberByToken
# ---------------------------------------------------------------------------


class TestDeactivateSubscriberByToken:
    def _setup_select(self, client, rows):
        """Wire the select→eq→execute chain for the initial token lookup."""
        client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_execute(data=rows)

    @patch("stellenscout.db.delete_subscriber_data")
    @patch("stellenscout.db.deactivate_subscriber", return_value=True)
    def test_valid_token_deactivates_and_deletes(self, mock_deactivate, mock_delete):
        client = _mock_client()
        expires = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        self._setup_select(client, [{"id": SUB_ID, "is_active": True, "unsubscribe_token_expires_at": expires}])

        assert db.deactivate_subscriber_by_token(client, UNSUB_TOKEN) is True
        mock_deactivate.assert_called_once_with(client, SUB_ID)
        mock_delete.assert_called_once_with(client, SUB_ID)

    def test_unknown_token_returns_false(self):
        client = _mock_client()
        self._setup_select(client, [])

        assert db.deactivate_subscriber_by_token(client, "nonexistent") is False

    def test_already_inactive_returns_false(self):
        client = _mock_client()
        expires = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        self._setup_select(client, [{"id": SUB_ID, "is_active": False, "unsubscribe_token_expires_at": expires}])

        assert db.deactivate_subscriber_by_token(client, UNSUB_TOKEN) is False

    @freeze_time("2026-02-20T12:00:00Z")
    def test_expired_token_returns_false(self):
        client = _mock_client()
        expired = (datetime(2026, 2, 19, tzinfo=timezone.utc)).isoformat()
        self._setup_select(client, [{"id": SUB_ID, "is_active": True, "unsubscribe_token_expires_at": expired}])

        assert db.deactivate_subscriber_by_token(client, UNSUB_TOKEN) is False

    @patch("stellenscout.db.delete_subscriber_data")
    @patch("stellenscout.db.deactivate_subscriber", return_value=True)
    def test_data_deletion_called(self, mock_deactivate, mock_delete):
        client = _mock_client()
        expires = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        self._setup_select(client, [{"id": SUB_ID, "is_active": True, "unsubscribe_token_expires_at": expires}])

        db.deactivate_subscriber_by_token(client, UNSUB_TOKEN)

        mock_delete.assert_called_once_with(client, SUB_ID)


# ---------------------------------------------------------------------------
# TestExpireSubscriptions
# ---------------------------------------------------------------------------


class TestExpireSubscriptions:
    def _setup_expired_select(self, client, rows):
        """Wire the chained select→eq→not_→lte→execute for the initial query."""
        chain = client.table.return_value.select.return_value
        chain.eq.return_value.not_.is_.return_value.lte.return_value.execute.return_value = _make_execute(data=rows)

    def _setup_recheck(self, client, data):
        """Wire the per-subscriber re-check (select→eq→maybe_single→execute)."""
        result = _make_execute(data=data)
        client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
            result
        )

    @patch("stellenscout.db.delete_subscriber_data")
    @patch("stellenscout.db.deactivate_subscriber", return_value=True)
    @freeze_time("2026-02-20T12:00:00Z")
    def test_expires_past_due_subscribers(self, mock_deactivate, mock_delete):
        client = _mock_client()
        sub1 = {"id": "sub-1"}
        sub2 = {"id": "sub-2"}
        self._setup_expired_select(client, [sub1, sub2])
        # Re-check returns active for both
        self._setup_recheck(client, {"is_active": True})

        count = db.expire_subscriptions(client)

        assert count == 2
        assert mock_deactivate.call_count == 2
        assert mock_delete.call_count == 2

    @freeze_time("2026-02-20T12:00:00Z")
    def test_no_expired_returns_zero(self):
        client = _mock_client()
        self._setup_expired_select(client, [])

        assert db.expire_subscriptions(client) == 0

    @patch("stellenscout.db.delete_subscriber_data")
    @patch("stellenscout.db.deactivate_subscriber")
    @freeze_time("2026-02-20T12:00:00Z")
    def test_skips_concurrently_deactivated(self, mock_deactivate, mock_delete):
        client = _mock_client()
        self._setup_expired_select(client, [{"id": "sub-1"}])
        # Re-check returns inactive (already deactivated by another process)
        self._setup_recheck(client, {"is_active": False})

        count = db.expire_subscriptions(client)

        assert count == 0
        mock_deactivate.assert_not_called()
        mock_delete.assert_not_called()

    @patch("stellenscout.db.delete_subscriber_data")
    @patch("stellenscout.db.deactivate_subscriber", return_value=True)
    @freeze_time("2026-02-20T12:00:00Z")
    def test_data_deleted_after_deactivation(self, mock_deactivate, mock_delete):
        client = _mock_client()
        self._setup_expired_select(client, [{"id": "sub-1"}])
        self._setup_recheck(client, {"is_active": True})

        db.expire_subscriptions(client)

        mock_delete.assert_called_once_with(client, "sub-1")

    @patch("stellenscout.db.delete_subscriber_data")
    @patch("stellenscout.db.deactivate_subscriber")
    @freeze_time("2026-02-20T12:00:00Z")
    def test_handles_missing_subscriber_on_recheck(self, mock_deactivate, mock_delete):
        client = _mock_client()
        self._setup_expired_select(client, [{"id": "sub-1"}])
        # Re-check returns None (row deleted between queries)
        self._setup_recheck(client, None)

        count = db.expire_subscriptions(client)

        assert count == 0
        mock_deactivate.assert_not_called()


# ---------------------------------------------------------------------------
# TestPurgeInactiveSubscribers
# ---------------------------------------------------------------------------


class TestPurgeInactiveSubscribers:
    def _setup_inactive_select(self, client, rows):
        """Wire select→eq→execute for inactive subscriber lookup."""
        client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_execute(data=rows)

    @freeze_time("2026-02-20T12:00:00Z")
    def test_deletes_old_inactive_subscribers(self):
        client = _mock_client()
        # Unsubscribed 10 days ago — older than the 7-day retention
        old_ts = (datetime(2026, 2, 10, tzinfo=timezone.utc)).isoformat()
        self._setup_inactive_select(client, [{"id": "sub-1", "is_active": False, "unsubscribed_at": old_ts}])
        client.table.return_value.delete.return_value.in_.return_value.execute.return_value = _make_execute(
            data=[{"id": "sub-1"}]
        )

        count = db.purge_inactive_subscribers(client)

        assert count == 1
        client.table.return_value.delete.return_value.in_.assert_called_once()

    @freeze_time("2026-02-20T12:00:00Z")
    def test_spares_recently_deactivated(self):
        client = _mock_client()
        # Unsubscribed 2 days ago — within the 7-day retention
        recent_ts = (datetime(2026, 2, 18, tzinfo=timezone.utc)).isoformat()
        self._setup_inactive_select(client, [{"id": "sub-1", "is_active": False, "unsubscribed_at": recent_ts}])

        count = db.purge_inactive_subscribers(client)

        assert count == 0

    def test_no_inactive_returns_zero(self):
        client = _mock_client()
        self._setup_inactive_select(client, [])

        assert db.purge_inactive_subscribers(client) == 0

    @freeze_time("2026-02-20T12:00:00Z")
    def test_chunked_deletion(self):
        client = _mock_client()
        old_ts = (datetime(2026, 2, 1, tzinfo=timezone.utc)).isoformat()
        rows = [{"id": f"sub-{i}", "is_active": False, "unsubscribed_at": old_ts} for i in range(250)]
        self._setup_inactive_select(client, rows)
        # Each chunk delete returns its slice
        client.table.return_value.delete.return_value.in_.return_value.execute.return_value = _make_execute(
            data=[{"id": "x"}] * 200
        )

        db.purge_inactive_subscribers(client)

        # 250 IDs → 2 chunks (200 + 50)
        assert client.table.return_value.delete.return_value.in_.call_count == 2
        # First chunk has 200 IDs, second has 50
        first_chunk = client.table.return_value.delete.return_value.in_.call_args_list[0][0][1]
        second_chunk = client.table.return_value.delete.return_value.in_.call_args_list[1][0][1]
        assert len(first_chunk) == 200
        assert len(second_chunk) == 50

    @freeze_time("2026-02-20T12:00:00Z")
    def test_skips_null_unsubscribed_at(self):
        client = _mock_client()
        # Row with no unsubscribed_at should not be purged
        self._setup_inactive_select(client, [{"id": "sub-1", "is_active": False, "unsubscribed_at": None}])

        count = db.purge_inactive_subscribers(client)

        assert count == 0


# ---------------------------------------------------------------------------
# TestConfirmSubscriber
# ---------------------------------------------------------------------------


class TestConfirmSubscriber:
    def _setup_token_lookup(self, client, rows):
        """Wire select→eq→execute for the token lookup."""
        client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_execute(data=rows)

    @freeze_time("2026-02-20T12:00:00Z")
    def test_valid_token_activates(self):
        client = _mock_client()
        expires = (datetime(2026, 2, 21, tzinfo=timezone.utc)).isoformat()
        sub = {"id": SUB_ID, "is_active": False, "token_expires_at": expires}
        self._setup_token_lookup(client, [sub])
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{**sub, "is_active": True}]
        )

        result = db.confirm_subscriber(client, TOKEN, confirm_ip="1.2.3.4", confirm_user_agent="TestAgent")

        assert result is not None
        assert result["is_active"] is True

    def test_unknown_token_returns_none(self):
        client = _mock_client()
        self._setup_token_lookup(client, [])

        assert db.confirm_subscriber(client, "bad_token") is None

    @freeze_time("2026-02-20T12:00:00Z")
    def test_expired_token_returns_none(self):
        client = _mock_client()
        expired = (datetime(2026, 2, 19, tzinfo=timezone.utc)).isoformat()
        sub = {"id": SUB_ID, "is_active": False, "token_expires_at": expired}
        self._setup_token_lookup(client, [sub])

        assert db.confirm_subscriber(client, TOKEN) is None

    @freeze_time("2026-02-20T12:00:00Z")
    def test_stores_confirm_metadata(self):
        client = _mock_client()
        expires = (datetime(2026, 2, 21, tzinfo=timezone.utc)).isoformat()
        sub = {"id": SUB_ID, "is_active": False, "token_expires_at": expires}
        self._setup_token_lookup(client, [sub])
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{**sub, "is_active": True}]
        )

        db.confirm_subscriber(client, TOKEN, confirm_ip="1.2.3.4", confirm_user_agent="TestAgent")

        payload = client.table.return_value.update.call_args[0][0]
        assert payload["confirm_ip"] == "1.2.3.4"
        assert payload["confirm_user_agent"] == "TestAgent"

    @freeze_time("2026-02-20T12:00:00Z")
    def test_clears_unsubscribe_fields(self):
        client = _mock_client()
        expires = (datetime(2026, 2, 21, tzinfo=timezone.utc)).isoformat()
        sub = {"id": SUB_ID, "is_active": False, "token_expires_at": expires}
        self._setup_token_lookup(client, [sub])
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{**sub, "is_active": True}]
        )

        db.confirm_subscriber(client, TOKEN)

        payload = client.table.return_value.update.call_args[0][0]
        assert payload["unsubscribed_at"] is None
        assert payload["unsubscribe_token"] is None
        assert payload["unsubscribe_token_expires_at"] is None


# ---------------------------------------------------------------------------
# TestSetSubscriberExpiry
# ---------------------------------------------------------------------------


class TestSetSubscriberExpiry:
    def test_sets_expiry(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{"id": SUB_ID}]
        )

        expires_at = "2026-03-22T12:00:00+00:00"
        result = db.set_subscriber_expiry(client, SUB_ID, expires_at)

        assert result is True
        payload = client.table.return_value.update.call_args[0][0]
        assert payload == {"expires_at": expires_at}

    def test_returns_false_on_no_match(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(data=[])

        assert db.set_subscriber_expiry(client, SUB_ID, "2026-03-22T12:00:00+00:00") is False


# ---------------------------------------------------------------------------
# TestAddSubscriber
# ---------------------------------------------------------------------------


class TestAddSubscriber:
    def _setup_select(self, client, rows):
        """Wire select→eq→execute for the email lookup."""
        client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_execute(data=rows)

    def test_returns_existing_active(self):
        client = _mock_client()
        existing = {"id": SUB_ID, "email": "a@b.com", "is_active": True}
        self._setup_select(client, [existing])

        result = db.add_subscriber(client, "a@b.com", TOKEN, "2026-02-21T12:00:00Z", "v1")

        assert result == existing
        # Should NOT have called upsert
        client.table.return_value.upsert.assert_not_called()

    def test_upserts_new_pending(self):
        client = _mock_client()
        self._setup_select(client, [])
        client.table.return_value.upsert.return_value.execute.return_value = _make_execute(data=[])

        result = db.add_subscriber(client, "new@b.com", TOKEN, "2026-02-21T12:00:00Z", "v1")

        assert result is None
        client.table.return_value.upsert.assert_called_once()
        payload = client.table.return_value.upsert.call_args[0][0]
        assert payload["email"] == "new@b.com"
        assert payload["is_active"] is False
        assert payload["confirmation_token"] == TOKEN

    def test_upserts_over_inactive(self):
        client = _mock_client()
        existing = {"id": SUB_ID, "email": "a@b.com", "is_active": False}
        self._setup_select(client, [existing])
        client.table.return_value.upsert.return_value.execute.return_value = _make_execute(data=[])

        result = db.add_subscriber(
            client,
            "a@b.com",
            TOKEN,
            "2026-02-21T12:00:00Z",
            "v1",
            signup_ip="1.2.3.4",
            signup_user_agent="TestAgent",
        )

        assert result is None
        client.table.return_value.upsert.assert_called_once()
        payload = client.table.return_value.upsert.call_args[0][0]
        assert payload["signup_ip"] == "1.2.3.4"
        assert payload["signup_user_agent"] == "TestAgent"


# ---------------------------------------------------------------------------
# TestSaveSubscriptionContext
# ---------------------------------------------------------------------------


class TestSaveSubscriptionContext:
    def test_stores_context(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{"id": SUB_ID}]
        )

        profile = {"skills": ["Python"], "experience_level": "Senior"}
        queries = ["Python Munich", "Backend Dev"]
        result = db.save_subscription_context(client, SUB_ID, profile, queries, "Munich, Germany", min_score=80)

        assert result is True
        payload = client.table.return_value.update.call_args[0][0]
        assert payload["profile_json"] == profile
        assert payload["search_queries"] == queries
        assert payload["target_location"] == "Munich, Germany"
        assert payload["min_score"] == 80

    def test_returns_false_on_no_match(self):
        client = _mock_client()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(data=[])

        assert db.save_subscription_context(client, SUB_ID, {}, [], "Berlin") is False


# ---------------------------------------------------------------------------
# TestGDPRLifecycle — integration-style (patches internal db functions)
# ---------------------------------------------------------------------------


class TestGDPRLifecycle:
    """End-to-end GDPR lifecycle tests combining multiple db functions."""

    @patch("stellenscout.db.delete_subscriber_data")
    @patch("stellenscout.db.deactivate_subscriber", return_value=True)
    @freeze_time("2026-02-20T12:00:00Z")
    def test_subscribe_verify_expire_purge(self, mock_deactivate, mock_delete):
        """Full lifecycle: subscribe → confirm → expire → purge."""
        client = _mock_client()

        # 1. Subscribe (new email)
        client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_execute(data=[])
        client.table.return_value.upsert.return_value.execute.return_value = _make_execute(data=[])
        result = db.add_subscriber(client, "test@example.com", TOKEN, "2026-02-21T12:00:00Z", "v1")
        assert result is None  # pending

        # 2. Confirm
        expires = (datetime(2026, 2, 21, tzinfo=timezone.utc)).isoformat()
        sub = {"id": SUB_ID, "is_active": False, "token_expires_at": expires}
        client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_execute(data=[sub])
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{**sub, "is_active": True}]
        )
        confirmed = db.confirm_subscriber(client, TOKEN)
        assert confirmed is not None
        assert confirmed["is_active"] is True

        # 3. Expire — simulate expire_subscriptions finding this subscriber
        chain = client.table.return_value.select.return_value
        chain.eq.return_value.not_.is_.return_value.lte.return_value.execute.return_value = _make_execute(
            data=[{"id": SUB_ID}]
        )
        client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
            _make_execute(data={"is_active": True})
        )
        count = db.expire_subscriptions(client)
        assert count == 1
        mock_deactivate.assert_called_with(client, SUB_ID)
        mock_delete.assert_called_with(client, SUB_ID)

    @patch("stellenscout.db.delete_subscriber_data")
    @patch("stellenscout.db.deactivate_subscriber", return_value=True)
    def test_subscribe_verify_unsubscribe(self, mock_deactivate, mock_delete):
        """Unsubscribe path: subscribe → confirm → unsubscribe (PII deleted)."""
        client = _mock_client()

        # 1. Token lookup for unsubscribe
        expires = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_execute(
            data=[{"id": SUB_ID, "is_active": True, "unsubscribe_token_expires_at": expires}]
        )

        # 2. Unsubscribe by token
        result = db.deactivate_subscriber_by_token(client, UNSUB_TOKEN)
        assert result is True
        mock_deactivate.assert_called_once_with(client, SUB_ID)
        mock_delete.assert_called_once_with(client, SUB_ID)

    @freeze_time("2026-02-20T12:00:00Z")
    def test_expired_token_cannot_confirm(self):
        """Security: an expired confirmation token must not activate a subscriber."""
        client = _mock_client()
        expired = (datetime(2026, 2, 19, tzinfo=timezone.utc)).isoformat()
        sub = {"id": SUB_ID, "is_active": False, "token_expires_at": expired}
        client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_execute(data=[sub])

        result = db.confirm_subscriber(client, TOKEN)

        assert result is None
