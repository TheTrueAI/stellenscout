"""Double Opt-In confirmation page."""

import contextlib
import logging
import os

import streamlit as st

logger = logging.getLogger(__name__)

# Inject secrets into env vars (same pattern as app.py)
for key in (
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_KEY",
    "RESEND_API_KEY",
    "RESEND_FROM",
    "APP_URL",
    "IMPRESSUM_NAME",
    "IMPRESSUM_ADDRESS",
    "IMPRESSUM_EMAIL",
):
    if key not in os.environ:
        with contextlib.suppress(KeyError, FileNotFoundError):
            os.environ[key] = st.secrets[key]

from immermatch.db import SUBSCRIPTION_DAYS, confirm_subscriber, get_admin_client, set_subscriber_expiry  # noqa: E402

st.set_page_config(page_title="Immermatch – Confirm Subscription", page_icon="✅")

token = st.query_params.get("token")


def _request_metadata() -> tuple[str | None, str | None]:
    try:
        headers = dict(st.context.headers)
    except Exception:
        return None, None

    forwarded_for = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    ip_address = None
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()

    user_agent = headers.get("user-agent") or headers.get("User-Agent")
    return ip_address, user_agent


if not token:
    st.warning("No confirmation token found. Please use the link from your email.")
    st.stop()

try:
    db = get_admin_client()
    confirm_ip, confirm_ua = _request_metadata()
    subscriber = confirm_subscriber(
        db,
        token,
        confirm_ip=confirm_ip,
        confirm_user_agent=confirm_ua,
    )
except Exception:
    logger.exception("Error during subscription confirmation")
    st.error("Something went wrong. Please try again later.")
    st.stop()

if subscriber:
    # Set auto-expiry: SUBSCRIPTION_DAYS days from confirmation
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz

    _expires = (_dt.now(_tz.utc) + _td(days=SUBSCRIPTION_DAYS)).isoformat()
    try:
        expiry_set = set_subscriber_expiry(db, subscriber["id"], _expires)
    except Exception:
        logger.exception("Failed to set subscription expiry")
        st.error("Something went wrong. Please try confirming again later.")
        st.stop()

    if not expiry_set:
        st.error("Failed to set subscription expiry. Please try confirming again later.")
        st.stop()

    st.success(
        f"Subscription confirmed! You will receive the daily Immermatch digest "
        f"for {SUBSCRIPTION_DAYS} days. You can unsubscribe at any time via the link in each email."
    )
    st.balloons()

    # Best-effort welcome email — failure doesn't affect confirmation
    try:
        import secrets as _secrets
        from datetime import timedelta as _td

        from immermatch.db import issue_unsubscribe_token
        from immermatch.emailer import send_welcome_email

        _app_url = os.environ.get("APP_URL", "").rstrip("/")

        _unsub_url = ""
        if _app_url:
            _unsub_token = _secrets.token_urlsafe(32)
            _unsub_expires = (_dt.now(_tz.utc) + _td(days=SUBSCRIPTION_DAYS)).isoformat()
            if issue_unsubscribe_token(db, subscriber["id"], token=_unsub_token, expires_at=_unsub_expires):
                _unsub_url = f"{_app_url}/unsubscribe?token={_unsub_token}"

        send_welcome_email(
            email=subscriber["email"],
            target_location=subscriber.get("target_location", ""),
            subscription_days=SUBSCRIPTION_DAYS,
            privacy_url=f"{_app_url}/privacy" if _app_url else "",
            unsubscribe_url=_unsub_url,
        )
    except Exception:
        logger.exception("Failed to send welcome email")
else:
    st.error("This confirmation link is invalid or has expired. Please subscribe again.")
