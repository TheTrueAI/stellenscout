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

from stellenscout.db import get_admin_client, confirm_subscriber  # noqa: E402

st.set_page_config(page_title="StellenScout – Confirm Subscription", page_icon="✅")

token = st.query_params.get("token")

if not token:
    st.warning("No confirmation token found. Please use the link from your email.")
    st.stop()

try:
    db = get_admin_client()
    subscriber = confirm_subscriber(db, token)
except Exception as e:
    st.error(f"An error occurred: {e}")
    st.stop()

if subscriber:
    st.success("Subscription confirmed! You will now receive the daily StellenScout digest.")
    st.balloons()
else:
    st.error(
        "This confirmation link is invalid or has expired. "
        "Please subscribe again."
    )
