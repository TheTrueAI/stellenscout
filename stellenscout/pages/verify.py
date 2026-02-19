"""Double Opt-In confirmation page."""

import os
import streamlit as st

# Inject secrets into env vars (same pattern as app.py)
for key in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_KEY"):
    if key not in os.environ:
        try:
            os.environ[key] = st.secrets[key]
        except (KeyError, FileNotFoundError):
            pass

from stellenscout.db import get_admin_client, confirm_subscriber, set_subscriber_expiry, SUBSCRIPTION_DAYS  # noqa: E402

st.set_page_config(page_title="StellenScout – Confirm Subscription", page_icon="✅")

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
except Exception as e:
    st.error(f"An error occurred: {e}")
    st.stop()

if subscriber:
    # Set auto-expiry: SUBSCRIPTION_DAYS days from confirmation
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _expires = (_dt.now(_tz.utc) + _td(days=SUBSCRIPTION_DAYS)).isoformat()
    try:
        expiry_set = set_subscriber_expiry(db, subscriber["id"], _expires)
    except Exception as e:
        st.error(f"Failed to set subscription expiry: {e}")
        st.stop()

    if not expiry_set:
        st.error("Failed to set subscription expiry. Please try confirming again later.")
        st.stop()

    st.success(
        f"Subscription confirmed! You will receive the daily StellenScout digest "
        f"for {SUBSCRIPTION_DAYS} days. You can unsubscribe at any time via the link in each email."
    )
    st.balloons()
else:
    st.error(
        "This confirmation link is invalid or has expired. "
        "Please subscribe again."
    )
