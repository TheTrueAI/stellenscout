"""One-click unsubscribe page."""

import os

import streamlit as st

# Inject secrets into env vars
for key in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_KEY"):
    if key not in os.environ:
        try:
            os.environ[key] = st.secrets[key]
        except (KeyError, FileNotFoundError):
            pass

from stellenscout.db import deactivate_subscriber_by_token, get_admin_client  # noqa: E402

st.set_page_config(page_title="StellenScout – Unsubscribe", page_icon="📭")

unsubscribe_token = st.query_params.get("token")

if not unsubscribe_token:
    st.warning("No unsubscribe link detected. Please use the link from your email.")
    st.stop()

try:
    db = get_admin_client()
    success = deactivate_subscriber_by_token(db, unsubscribe_token)
except Exception as e:
    st.error(f"An error occurred: {e}")
    st.stop()

if success:
    st.success(
        "You have been successfully unsubscribed. "
        "Your profile data has been deleted. "
        "You will no longer receive emails from StellenScout."
    )
else:
    st.info("This subscription has already been cancelled or does not exist.")
