"""Streamlit web UI for Immermatch."""

import contextlib
import hashlib
import html
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

jobs_per_query = 20  # default value

# ---------------------------------------------------------------------------
# Inject API keys from Streamlit secrets into env vars
# (must happen before any immermatch imports that read env vars)
# ---------------------------------------------------------------------------
for key in (
    "GOOGLE_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_KEY",
    "RESEND_API_KEY",
    "RESEND_FROM",
    "APP_URL",
):
    if key not in os.environ:
        with contextlib.suppress(KeyError, FileNotFoundError):
            os.environ[key] = st.secrets[key]

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from immermatch.cache import ResultCache  # noqa: E402
from immermatch.cv_parser import SUPPORTED_EXTENSIONS, extract_text  # noqa: E402
from immermatch.db import SUBSCRIPTION_DAYS  # noqa: E402
from immermatch.evaluator_agent import evaluate_job, generate_summary  # noqa: E402
from immermatch.llm import create_client  # noqa: E402
from immermatch.models import CandidateProfile, EvaluatedJob, JobListing  # noqa: E402
from immermatch.search_api.link_validator import validate_jobs  # noqa: E402
from immermatch.search_api.search_agent import (  # noqa: E402
    generate_search_queries,
    profile_candidate,
    search_all_queries,
)
from immermatch.search_api.search_provider import (  # noqa: E402
    get_provider,
    get_provider_fingerprint,
    parse_provider_query,  # noqa: E402
)

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Immermatch",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
def _inject_custom_css() -> None:
    st.markdown(
        """
    <style>
    /* Hero section */
    .hero-section {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 16px;
        padding: 3rem 2rem;
        text-align: center;
        color: white;
        margin-bottom: 2rem;
    }
    .hero-section h1 {
        color: white !important;
        font-size: 2.4rem;
        margin-bottom: 0.5rem;
    }
    .hero-section p {
        color: rgba(255,255,255,0.9);
        font-size: 1.15rem;
        margin-top: 0;
    }

    /* Step indicator */
    .step-indicator {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 0.75rem;
        margin: 1.5rem 0;
    }
    .step-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.4rem 1rem;
        border-radius: 999px;
        font-size: 0.9rem;
        font-weight: 500;
    }
    .step-done {
        background: #dcfce7;
        color: #166534;
        border: 2px solid #86efac;
    }
    .step-active {
        background: #dbeafe;
        color: #1e40af;
        border: 2px solid #667eea;
        animation: pulse-border 2s ease-in-out infinite;
    }
    .step-pending {
        background: #f1f5f9;
        color: #64748b;
        border: 2px solid #e2e8f0;
    }
    @keyframes pulse-border {
        0%, 100% { box-shadow: 0 0 0 0 rgba(102,126,234,0.4); }
        50% { box-shadow: 0 0 0 6px rgba(102,126,234,0); }
    }

    /* Newsletter CTA */
    .newsletter-cta {
        background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
        border-radius: 16px;
        padding: 2rem;
        text-align: center;
        color: white;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }
    .newsletter-cta h3 {
        color: white !important;
        margin-bottom: 0.5rem;
    }
    .newsletter-cta p {
        color: rgba(255,255,255,0.9);
        margin-top: 0;
    }

    /* Sidebar */
    [data-testid="stSidebar"] > div:first-child {
        background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 0.75rem 1rem;
    }

    /* Score badge */
    .score-badge {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.95rem;
    }
    .score-green  { background: #dcfce7; color: #166534; }
    .score-yellow { background: #fef9c3; color: #854d0e; }
    .score-orange { background: #ffedd5; color: #9a3412; }
    .score-red    { background: #fee2e2; color: #991b1b; }

    /* Reliability badges */
    .reliability-badge {
        display: inline-block;
        padding: 0.1rem 0.5rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .reliability-verified   { background: #dcfce7; color: #166534; }
    .reliability-aggregator { background: #dcfce7; color: #166534; }
    .reliability-unverified { background: #fee2e2; color: #991b1b; }

    /* General spacing */
    .block-container { padding-top: 2rem; }
    </style>
    """,
        unsafe_allow_html=True,
    )


_inject_custom_css()

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


@st.cache_resource
def _get_summary_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=2)


_SUMMARY_EXECUTOR = _get_summary_executor()

_DEFAULTS = {
    "profile": None,
    "queries": None,
    "evaluated_jobs": None,
    "summary": None,
    "summary_future": None,
    "summary_error": None,
    "cv_text": None,
    "cv_file_hash": None,
    "cv_file_name": None,
    "last_run_time": 0.0,
    "run_requested": False,
    "location": "",
    "profile_edit_enabled": False,
    "_cv_consent_given": False,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------------------------
# Cache scoped to this browser session
# ---------------------------------------------------------------------------
CACHE_ROOT = Path(".immermatch_cache")


def _cv_file_hash(data: bytes) -> str:
    """Return a stable SHA-256 hex digest for CV file content."""
    return hashlib.sha256(data).hexdigest()[:16]


def _get_cache() -> ResultCache:
    cv_hash = st.session_state.cv_file_hash
    if not cv_hash:
        cv_hash = "default"
    return ResultCache(cache_dir=CACHE_ROOT / cv_hash)


def _cleanup_old_sessions(max_age_hours: int = 24, max_sessions: int = 50) -> None:
    """Delete session cache dirs older than *max_age_hours* and cap total count."""
    if not CACHE_ROOT.exists():
        return
    current = st.session_state.cv_file_hash or ""
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    dirs: list[tuple[float, Path]] = []
    for child in CACHE_ROOT.iterdir():
        if child.is_dir() and child.name != current:
            try:
                mtime_ts = child.stat().st_mtime
                mtime = datetime.fromtimestamp(mtime_ts)
                if mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    dirs.append((mtime_ts, child))
            except OSError:
                pass
    # Cap total number of session directories
    if len(dirs) >= max_sessions:
        dirs.sort()  # oldest first
        for _, d in dirs[: len(dirs) - max_sessions + 1]:
            shutil.rmtree(d, ignore_errors=True)


# Housekeeping — runs once per session on first load
if "cleanup_done" not in st.session_state:
    _cleanup_old_sessions()
    try:
        from immermatch.db import get_admin_client as _get_admin_db
        from immermatch.db import purge_inactive_subscribers

        _db = _get_admin_db()
        purge_inactive_subscribers(_db, older_than_days=30)
    except Exception:
        logger.debug("Session cache cleanup skipped", exc_info=True)
    st.session_state.cleanup_done = True

_MAX_CV_CHARS = 50_000
_CONSENT_TEXT_VERSION = "v2026-02-12"


def _request_metadata() -> tuple[str | None, str | None]:
    """Best-effort client metadata capture for DOI evidence logging."""
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


# ---------------------------------------------------------------------------
# Helper: write uploaded file to a temp path and extract text
# ---------------------------------------------------------------------------
def _extract_uploaded_cv(uploaded_file) -> str:
    """Write the uploaded file to a temp path, then use the existing parser."""
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = Path(tmp.name)
    try:
        text = extract_text(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    if len(text) > _MAX_CV_CHARS:
        st.warning("CV text was very long and has been truncated.")
        text = text[:_MAX_CV_CHARS]
    return text


# ---------------------------------------------------------------------------
# Helper: display profile (for inside expander — no subheader)
# ---------------------------------------------------------------------------
def _render_profile(profile: CandidateProfile) -> None:
    if profile.summary:
        st.markdown(f"*{profile.summary}*")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Experience:** {profile.experience_level} ({profile.years_of_experience} yrs)")
        st.markdown(f"**Roles:** {', '.join(profile.roles)}")
        if profile.education:
            st.markdown(f"**Education:** {', '.join(profile.education)}")
    with col2:
        st.markdown(f"**Languages:** {', '.join(profile.languages)}")
        st.markdown(f"**Domain:** {', '.join(profile.domain_expertise)}")
        if profile.certifications:
            st.markdown(f"**Certifications:** {', '.join(profile.certifications)}")

    st.markdown("**Skills:** " + " · ".join(f"`{s}`" for s in profile.skills))


def _render_profile_editable(profile: CandidateProfile) -> tuple[str, str, str]:
    """Render editable profile fields and return (skills, roles, prefs) text."""
    st.markdown("**Enter further details** (optional)")
    edit_skills = st.text_area(
        "Skills (comma-separated)",
        value=", ".join(profile.skills),
        height=68,
    )
    edit_roles = st.text_area(
        "Target roles (comma-separated)",
        placeholder=f"e.g. {', '.join(profile.roles)}",
        height=68,
    )
    edit_prefs = st.text_area(
        "Preferences",
        placeholder="e.g. remote only, no startups, prefer 4-day week...",
        height=68,
    )
    return edit_skills, edit_roles, edit_prefs


# ---------------------------------------------------------------------------
# Helper: score helpers
# ---------------------------------------------------------------------------

_RELIABILITY_INFO: dict[str, tuple[str, str, str]] = {
    "verified": (
        "Verified",
        "reliability-verified",
        "Listed on Bundesagentur für Arbeit, a government-regulated job database",
    ),
    "aggregator": (
        "Job Board",
        "reliability-aggregator",
        "Found via a known job board (LinkedIn, StepStone, etc.)",
    ),
    "unverified": (
        "Unverified",
        "reliability-unverified",
        "Source could not be verified — apply with caution",
    ),
}


def _parse_relative_date(posted_at: str) -> datetime | None:
    """Parse relative date strings like '2 days ago' into a datetime.

    Returns None if the string cannot be parsed.
    """
    if not posted_at:
        return None
    posted_lower = posted_at.strip().lower()
    now = datetime.now(timezone.utc)
    if posted_lower in ("just now", "today", "just posted"):
        return now
    match = re.match(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", posted_lower)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    unit_map = {
        "second": timedelta(seconds=1),
        "minute": timedelta(minutes=1),
        "hour": timedelta(hours=1),
        "day": timedelta(days=1),
        "week": timedelta(weeks=1),
        "month": timedelta(days=30),
        "year": timedelta(days=365),
    }
    return now - unit_map[unit] * value


def _score_emoji(score: int) -> str:
    if score >= 85:
        return "🟢"
    if score >= 70:
        return "🟡"
    if score >= 50:
        return "🟠"
    return "🔴"


def _score_css_class(score: int) -> str:
    if score >= 85:
        return "score-green"
    if score >= 70:
        return "score-yellow"
    if score >= 50:
        return "score-orange"
    return "score-red"


# ---------------------------------------------------------------------------
# Helper: render a single job card
# ---------------------------------------------------------------------------
def _render_job_card(ej: EvaluatedJob) -> None:
    score = ej.evaluation.score
    emoji = _score_emoji(score)
    css_class = _score_css_class(score)
    missing = ", ".join(ej.evaluation.missing_skills) if ej.evaluation.missing_skills else None

    with st.container(border=True):
        left, center, right = st.columns([0.6, 4, 1])

        with left:
            st.markdown(
                f'<span class="score-badge {css_class}">{emoji} {score}</span>',
                unsafe_allow_html=True,
            )

        with center:
            label, css, tooltip = _RELIABILITY_INFO.get(ej.job.reliability, ("", "", ""))
            safe_title = html.escape(ej.job.title, quote=True)
            safe_company = html.escape(ej.job.company_name, quote=True)
            safe_label = html.escape(label, quote=True)
            safe_tooltip = html.escape(tooltip, quote=True)
            badge_html = (
                f' <span class="reliability-badge {css}" title="{safe_tooltip}" tabindex="0" aria-label="{safe_tooltip}">{safe_label}</span>'
                if label
                else ""
            )
            st.markdown(f"<strong>{safe_title}</strong> @ {safe_company}{badge_html}", unsafe_allow_html=True)
            st.caption(f"📍 {ej.job.location}" + (f"  •  🕐 {ej.job.posted_at}" if ej.job.posted_at else ""))
            st.markdown(ej.evaluation.reasoning)
            if missing:
                st.markdown(f"**Missing:** {missing}")

        with right:
            if ej.job.apply_options:
                for option in ej.job.apply_options:
                    label = option.source
                    if "linkedin" in option.source.lower():
                        label = "🔗 LinkedIn"
                    elif "company" in option.source.lower() or "career" in option.source.lower():
                        label = "🏢 Career Page"
                    st.link_button(label, option.url, use_container_width=True)
            elif ej.job.link:
                st.link_button("Apply ↗", ej.job.link, use_container_width=True)


def _generate_summary_background(
    profile: CandidateProfile,
    evaluated_jobs: list[EvaluatedJob],
) -> str:
    client = create_client()
    return generate_summary(client, profile, evaluated_jobs)


def _render_career_summary(evaluated_jobs: list[EvaluatedJob]) -> bool:
    """Render summary area and return True while summary generation is pending."""
    pending = False

    if st.session_state.summary is None and st.session_state.profile is not None:
        future = st.session_state.get("summary_future")

        if not isinstance(future, Future):
            st.session_state.summary_error = None
            st.session_state.summary_future = _SUMMARY_EXECUTOR.submit(
                _generate_summary_background,
                st.session_state.profile,
                evaluated_jobs,
            )
            pending = True
            st.info("📊 Generating career summary in the background while you browse offers...")
        elif future.done():
            try:
                st.session_state.summary = future.result()
            except Exception:
                logger.exception("Summary generation error")
                st.session_state.summary_error = "Could not generate the career summary right now."
            finally:
                st.session_state.summary_future = None
        else:
            pending = True
            st.info("📊 Career summary is still generating in the background.")

    if st.session_state.summary_error:
        st.warning(st.session_state.summary_error)

    if st.session_state.summary is not None:
        with st.expander("📊 Market Summary & Career Advice", expanded=True):
            st.markdown(st.session_state.summary)

    return pending


# ---------------------------------------------------------------------------
# Helper: step indicator
# ---------------------------------------------------------------------------
def _render_step_indicator(step: int) -> None:
    """Render a 3-step indicator. *step* is the current active step (1, 2, or 3).
    Steps < step are 'done', step == step is 'active', step > step are 'pending'.
    If step > 3, all are done.
    """
    labels = ["1. Upload CV", "2. Choose Location", "3. Get Matches"]
    icons_done = ["✅", "✅", "✅"]
    icons_active = ["📄", "📍", "🚀"]
    icons_pending = ["📄", "📍", "🚀"]

    badges = []
    for i, label in enumerate(labels, 1):
        if i < step:
            badges.append(f'<span class="step-badge step-done">{icons_done[i - 1]} {label}</span>')
        elif i == step:
            badges.append(f'<span class="step-badge step-active">{icons_active[i - 1]} {label}</span>')
        else:
            badges.append(f'<span class="step-badge step-pending">{icons_pending[i - 1]} {label}</span>')

    st.markdown(
        f'<div class="step-indicator">{"".join(badges)}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Validate keys before running
# ---------------------------------------------------------------------------
def _keys_ok() -> bool:
    missing = []
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")
    if missing:
        st.error(
            f"Missing API key(s): **{', '.join(missing)}**. "
            "Add them to `.streamlit/secrets.toml` or set them as environment variables."
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Sidebar — status & settings panel
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🔍 Immermatch")
    st.caption("AI-powered job matching")
    st.divider()

    # -- Status section ----------------------------------------------------
    st.markdown("**Status**")
    if st.session_state.cv_file_name:
        st.markdown(f"📄 **CV:** {st.session_state.cv_file_name}")
    else:
        st.markdown("📄 **CV:** Not uploaded")

    if st.session_state.location:
        st.markdown(f"📍 **Location:** {st.session_state.location}")
    else:
        st.markdown("📍 **Location:** Not set")

    if st.session_state.evaluated_jobs is not None:
        st.markdown(f"🎯 **Matches:** {len(st.session_state.evaluated_jobs)}")
    elif st.session_state.run_requested:
        st.markdown("⏳ **Pipeline:** Finding jobs...")

    st.divider()

    # -- Settings ----------------------------------------------------------
    st.markdown("**Settings**")
    min_score = st.slider(
        "Minimum match score",
        min_value=0,
        max_value=100,
        value=70,
        step=5,
        help="Only show jobs scoring at or above this threshold",
    )

    # -- Change CV re-uploader (secondary) ---------------------------------
    sidebar_uploaded_file = st.file_uploader(
        "Change CV",
        type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
        help="Upload a different CV",
        key="sidebar_cv_upload",
        disabled=not st.session_state._cv_consent_given,
    )

    st.divider()
    st.caption(
        "Built with [Streamlit](https://streamlit.io) • "
        "Powered by Gemini & Bundesagentur für Arbeit  \n"
        "[GitHub](https://github.com/TheTrueAI/immermatch) · "
        "[Legal Notice / Impressum](/impressum) · [Privacy Policy](/privacy)"
    )

# ---------------------------------------------------------------------------
# Main area — merge uploaders & process CV
# ---------------------------------------------------------------------------

# Phase A hero uploader (rendered below) — we need a placeholder for it
# We'll use a two-pass approach: first collect the file, then render phases.

# Determine current phase
has_cv = st.session_state.cv_file_hash is not None
has_results = st.session_state.evaluated_jobs is not None

# Defaults for variables set conditionally in phase branches
run_button = False
location = st.session_state.location

# Render the appropriate phase
if not has_cv:
    # ===== Phase A: Landing — no CV uploaded =============================
    st.markdown(
        '<div class="hero-section">'
        "<h1>Find Your Dream Job</h1>"
        "<p>Upload your CV and let AI match you with the best openings</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    _render_step_indicator(1)

    # Centered file uploader
    col_pad_l, col_center, col_pad_r = st.columns([1, 2, 1])
    with col_center:
        st.checkbox(
            "I consent to processing my CV data for AI matching as described in the [Privacy Policy](/privacy).",
            key="cv_consent_checkbox",
            value=st.session_state._cv_consent_given,
            on_change=lambda: setattr(
                st.session_state,
                "_cv_consent_given",
                st.session_state.cv_consent_checkbox,
            ),
        )
        hero_uploaded_file = st.file_uploader(
            "Upload your CV to get started",
            type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
            help="Supported formats: PDF, DOCX, Markdown, plain text. Your file stays private.",
            key="hero_cv_upload",
            disabled=not st.session_state._cv_consent_given,
        )
        st.caption("Your CV is processed securely via AI. See our [Privacy Policy](/privacy) for details.")

    # How it works section
    st.divider()
    st.subheader("How it works")
    _hw1, _hw2, _hw3 = st.columns(3)
    with _hw1:
        st.markdown("**1. Upload your CV**")
        st.caption(
            "Upload your CV in PDF, DOCX, or text format. Our AI extracts your skills, experience, and preferences."
        )
    with _hw2:
        st.markdown("**2. Choose your location**")
        st.caption("Tell us where you want to work. We search multiple job sources for openings in your area.")
    with _hw3:
        st.markdown("**3. Get matched jobs**")
        st.caption("AI scores every job against your profile and shows the best matches with apply links.")
else:
    hero_uploaded_file = None

    if not has_results:
        # ===== Phase B: CV uploaded, no results yet ==========================
        _pipeline_active = st.session_state.run_requested
        _render_step_indicator(3 if _pipeline_active else 2)

        col_pad_l, col_center, col_pad_r = st.columns([1, 2, 1])
        with col_center:
            _profile = st.session_state.profile
            _edit_skills = ""
            _edit_roles = ""
            _edit_prefs = ""

            with st.form("search_form"):
                location = st.text_input(
                    "Where do you want to work?",
                    max_chars=100,
                    placeholder="e.g. Munich, Berlin, Hamburg...",
                    help="Currently searches German job listings via Bundesagentur für Arbeit.",
                    disabled=_pipeline_active,
                )

                _submit_label = "⏳ Finding jobs..." if _pipeline_active else "🚀 Find Jobs"
                run_button = st.form_submit_button(
                    _submit_label,
                    use_container_width=True,
                    type="primary",
                    disabled=_pipeline_active,
                )

            location = location.strip()[:100]

        if _profile is not None:
            with st.expander("Your AI Profile", expanded=True, icon="📋"):
                if not st.session_state.profile_edit_enabled:
                    _render_profile(_profile)

                    if st.button(
                        "✏️ Edit profile",
                        key="enable_profile_edit_btn",
                        type="secondary",
                    ):
                        st.session_state.profile_edit_enabled = True
                        st.rerun()

                else:
                    _edit_skills, _edit_roles, _edit_prefs = _render_profile_editable(_profile)

                    if st.button(
                        "💾 Save profile changes",
                        key="save_profile_btn",
                        type="primary",
                    ):
                        _new_skills = [s.strip() for s in (_edit_skills or "").split(",") if s.strip()]
                        _new_roles = [r.strip() for r in (_edit_roles or "").split(",") if r.strip()]
                        _prefs_str = (_edit_prefs or "").strip()
                        _changed = (
                            _new_skills != _profile.skills
                            or _new_roles != _profile.roles
                            or _prefs_str != _profile.preferences
                        )
                        st.session_state.profile = _profile.model_copy(
                            update={
                                "skills": _new_skills or _profile.skills,
                                "roles": _new_roles or _profile.roles,
                                "preferences": _prefs_str,
                            }
                        )
                        if _changed:
                            st.session_state.queries = None
                        st.session_state.profile_edit_enabled = False
                        st.rerun()

        if run_button and _profile is not None and st.session_state.profile_edit_enabled:
            _new_skills = [s.strip() for s in (_edit_skills or "").split(",") if s.strip()]
            _new_roles = [r.strip() for r in (_edit_roles or "").split(",") if r.strip()]
            _prefs_str = (_edit_prefs or "").strip()
            _changed = (
                _new_skills != _profile.skills or _new_roles != _profile.roles or _prefs_str != _profile.preferences
            )
            st.session_state.profile = _profile.model_copy(
                update={
                    "skills": _new_skills or _profile.skills,
                    "roles": _new_roles or _profile.roles,
                    "preferences": _prefs_str,
                }
            )
            if _changed:
                st.session_state.queries = None  # invalidate cached queries
    else:
        # ===== Phase C: Results ready ========================================
        _render_step_indicator(4)  # all done
        location = st.session_state.location
        run_button = False

# ---------------------------------------------------------------------------
# Merge uploaders — hero or sidebar
# ---------------------------------------------------------------------------
uploaded_file = None
if not has_cv:
    uploaded_file = hero_uploaded_file
if sidebar_uploaded_file is not None:
    uploaded_file = sidebar_uploaded_file

# ---------------------------------------------------------------------------
# Eager CV processing — runs on every rerun where a file is uploaded
# ---------------------------------------------------------------------------
if uploaded_file is not None:
    if not st.session_state._cv_consent_given:
        st.warning("Please provide CV processing consent before uploading your CV.")
        st.stop()

    file_bytes = uploaded_file.getbuffer()
    if len(file_bytes) > 5 * 1024 * 1024:
        st.error("File exceeds 5 MB limit. Please upload a smaller file.")
        st.stop()

    file_hash = _cv_file_hash(bytes(file_bytes))
    if file_hash != st.session_state.cv_file_hash:
        # New or changed file — extract text + profile
        cv_text = _extract_uploaded_cv(uploaded_file)
        st.session_state.cv_text = cv_text
        st.session_state.cv_file_hash = file_hash
        st.session_state.cv_file_name = uploaded_file.name
        # Clear stale downstream state
        st.session_state.profile = None
        st.session_state.queries = None
        st.session_state.evaluated_jobs = None
        st.session_state.profile_edit_enabled = False
        st.session_state.summary = None
        st.session_state.summary_error = None
        prev_future = st.session_state.get("summary_future")
        if isinstance(prev_future, Future):
            prev_future.cancel()
        st.session_state.summary_future = None
        st.rerun()

# Capture button intent — profile may not be ready yet
if has_cv and not has_results and run_button:
    if not st.session_state._cv_consent_given:
        st.warning("Please provide CV processing consent before starting the job search.")
    else:
        st.session_state.run_requested = True
        st.session_state.location = location
        # Rerun so the sidebar shows the location and the form re-renders
        # in disabled state before the blocking pipeline execution begins.
        st.rerun()

# Eager profile extraction — if we have CV text but no profile yet
if st.session_state.cv_text and st.session_state.profile is None:
    cache = _get_cache()
    cached_profile = cache.load_profile(st.session_state.cv_text)
    if cached_profile is not None:
        st.session_state.profile = cached_profile
        st.session_state._cv_consent_given = True  # consent was given in the session that created the cache
        st.rerun()
    elif _keys_ok():
        label = (
            "🧠 Analyzing your CV... (job search will start automatically)"
            if st.session_state.run_requested
            else "🧠 Analyzing your CV..."
        )
        with st.status(label, expanded=False) as status:
            client = create_client()
            profile = profile_candidate(client, st.session_state.cv_text)
            cache.save_profile(st.session_state.cv_text, profile)
            st.session_state.profile = profile
            status.update(label="✅ Profile extracted", state="complete")
        st.rerun()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def _run_pipeline() -> None:
    """Execute the pipeline from query generation onward."""
    profile = st.session_state.profile
    location = st.session_state.location
    if profile is None:
        st.error("No candidate profile available. Please upload a CV first.")
        return

    cache = _get_cache()
    provider = get_provider(location)
    provider_fingerprint = get_provider_fingerprint(provider)
    # Eagerly create the Gemini client so it's ready before the pipeline starts —
    # avoids lazy-init delay between query generation and job evaluation.
    client = create_client() if _keys_ok() else None

    # ---- Step 1: Generate queries ----------------------------------------
    with st.status("✨ Crafting search queries...", expanded=False) as status:
        cached_queries = cache.load_queries(profile, location, provider_fingerprint)
        if cached_queries is not None:
            queries = cached_queries
            status.update(label="✅ Queries generated (cached)", state="complete")
        else:
            if client is None:
                client = create_client()
            queries = generate_search_queries(client, profile, location, provider=provider)
            cache.save_queries(profile, location, queries, provider_fingerprint)
            status.update(label="✅ Queries generated", state="complete")
    st.session_state.queries = queries

    # ---- Step 2 & 3: Search + evaluate in parallel ----------------------
    # Jobs are submitted for evaluation as soon as each search query returns
    # results, overlapping the two phases for faster end-to-end time.
    cached_jobs = cache.load_jobs(location)

    if cached_jobs is not None:
        jobs = cached_jobs
        with st.status(f"✅ Found {len(jobs)} jobs (cached)", state="complete"):
            pass

        if not jobs:
            st.warning("No jobs found. Try adjusting your location or uploading a different CV.")
            return

        new_jobs, cached_evals = cache.get_unevaluated_jobs(jobs, profile)
        if not new_jobs:
            with st.status("✅ All evaluations loaded (cached)", state="complete"):
                pass
            all_evals = cached_evals
        else:
            if client is None:
                client = create_client()
            all_evals = dict(cached_evals)
            progress_bar = st.progress(0, text="⭐ Rating each job for you...")
            results_container = st.container()
            with ThreadPoolExecutor(max_workers=30) as executor:
                futures = {executor.submit(evaluate_job, client, profile, job): job for job in new_jobs}
                for i, future in enumerate(as_completed(futures), 1):
                    job = futures[future]
                    evaluation = future.result()
                    ej = EvaluatedJob(job=job, evaluation=evaluation)
                    key = f"{ej.job.title}|{ej.job.company_name}|{ej.job.location}"
                    all_evals[key] = ej
                    progress_bar.progress(
                        i / len(new_jobs),
                        text=f"⭐ Rating each job for you... ({i}/{len(new_jobs)})",
                    )
                    with results_container:
                        _render_job_card(ej)
            progress_bar.empty()
            results_container.empty()
            cache.save_evaluations(profile, all_evals)
    else:
        # Fresh search: overlap searching and evaluating.
        if client is None:
            client = create_client()

        # Load any previously evaluated jobs so we skip re-evaluating them.
        cached_evals = cache.load_evaluations(profile)
        all_evals: dict[str, EvaluatedJob] = dict(cached_evals) if cached_evals else {}
        eval_executor = ThreadPoolExecutor(max_workers=30)
        try:
            eval_futures: dict[Future, JobListing] = {}
            eval_lock = threading.Lock()

            def _on_jobs_found(new_unique_jobs: list[JobListing]) -> None:
                """Submit newly found jobs for evaluation immediately."""
                for job in new_unique_jobs:
                    key = f"{job.title}|{job.company_name}|{job.location}"
                    if key in all_evals:
                        continue  # already evaluated (from cache)
                    fut = eval_executor.submit(evaluate_job, client, profile, job)
                    with eval_lock:
                        eval_futures[fut] = job

            # -- Search phase with status wrapper --
            search_progress = st.progress(0, text="🌍 Scouting jobs...")
            with st.status("🌍 Searching for jobs...", expanded=False) as search_status:

                def _search_progress(qi: int, total: int, unique: int) -> None:
                    pct = qi / total
                    search_progress.progress(
                        pct, text=f"🌍 Searching query {qi}/{total} — {unique} unique jobs found so far..."
                    )

                jobs = search_all_queries(
                    queries,
                    jobs_per_query=jobs_per_query,
                    location=location,
                    on_progress=_search_progress,
                    on_jobs_found=_on_jobs_found,
                    provider=provider,
                )
                pre_validation = len(jobs)
                jobs = validate_jobs(jobs)
                cache.save_jobs(jobs, location)
                validated_note = (
                    f" ({pre_validation - len(jobs)} dead links removed)" if len(jobs) < pre_validation else ""
                )
                search_status.update(label=f"✅ Found {len(jobs)} unique jobs{validated_note}", state="complete")
            search_progress.empty()

            if not jobs:
                st.warning("No jobs found. Try adjusting your location or uploading a different CV.")
                return

            # -- Evaluation phase: collect results from futures already in flight --
            total_evals = len(eval_futures)
            if total_evals == 0:
                pass  # no jobs to evaluate (all were cached)
            else:
                # Some evals may have completed during search — the progress bar
                # and card rendering will catch up immediately.
                eval_progress = st.progress(0, text=f"⭐ Rating each job for you... (0/{total_evals})")
                results_container = st.container()
                for i, future in enumerate(as_completed(eval_futures), 1):
                    job = eval_futures[future]
                    evaluation = future.result()
                    ej = EvaluatedJob(job=job, evaluation=evaluation)
                    key = f"{ej.job.title}|{ej.job.company_name}|{ej.job.location}"
                    all_evals[key] = ej
                    eval_progress.progress(
                        i / total_evals,
                        text=f"⭐ Rating each job for you... ({i}/{total_evals})",
                    )
                    with results_container:
                        _render_job_card(ej)
                eval_progress.empty()
                results_container.empty()

            cache.save_evaluations(profile, all_evals)
        finally:
            eval_executor.shutdown(wait=True, cancel_futures=True)

    # Build final sorted list
    evaluated_jobs = sorted(
        all_evals.values(),
        key=lambda x: x.evaluation.score,
        reverse=True,
    )
    st.session_state.evaluated_jobs = evaluated_jobs


# ---------------------------------------------------------------------------
# Run pipeline on button click
# ---------------------------------------------------------------------------
_RATE_LIMIT_SECONDS = 30
_RATE_LIMIT_STALE_SECONDS = 300  # clean up entries older than 5 min

# Module-level dict shared across sessions on the same Streamlit instance
_ip_rate_limit: dict[str, float] = {}


def _get_client_ip() -> str | None:
    """Extract client IP from X-Forwarded-For header."""
    try:
        headers = dict(st.context.headers)
    except Exception:
        return None
    forwarded_for = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return None


def _check_ip_rate_limit() -> int | None:
    """Return seconds remaining if IP is rate-limited, else None. Also cleans stale entries."""
    now = time.monotonic()
    # Purge stale entries
    stale = [ip for ip, ts in _ip_rate_limit.items() if now - ts > _RATE_LIMIT_STALE_SECONDS]
    for ip in stale:
        del _ip_rate_limit[ip]

    client_ip = _get_client_ip()
    if not client_ip:
        return None
    last_run = _ip_rate_limit.get(client_ip)
    if last_run is not None:
        elapsed = now - last_run
        if elapsed < _RATE_LIMIT_SECONDS:
            return int(_RATE_LIMIT_SECONDS - elapsed)
    return None


def _record_ip_rate_limit() -> None:
    """Record the current time for the client's IP."""
    client_ip = _get_client_ip()
    if client_ip:
        _ip_rate_limit[client_ip] = time.monotonic()


if st.session_state.run_requested and st.session_state.profile is not None:
    st.session_state.run_requested = False
    # Check session-based rate limit
    elapsed = time.monotonic() - st.session_state.last_run_time
    if elapsed < _RATE_LIMIT_SECONDS:
        remaining = int(_RATE_LIMIT_SECONDS - elapsed)
        st.warning(f"Please wait {remaining}s before running again.")
        st.rerun()
    elif (ip_remaining := _check_ip_rate_limit()) is not None:
        st.warning(f"Please wait {ip_remaining}s before running again.")
        st.rerun()
    elif _keys_ok():
        try:
            st.session_state.last_run_time = time.monotonic()
            _record_ip_rate_limit()
            _run_pipeline()
            st.rerun()
        except Exception:
            logger.exception("Pipeline error")
            st.error("Something went wrong. Please try again or upload a different CV.")

# ---------------------------------------------------------------------------
# Display results — Jobs first, summary collapsed below
# ---------------------------------------------------------------------------
if st.session_state.evaluated_jobs is not None:
    evaluated_jobs: list[EvaluatedJob] = st.session_state.evaluated_jobs

    # -- Search queries (collapsed) ----------------------------------------
    if st.session_state.queries is not None:
        with st.expander(
            f"🔍 **Search Queries** ({len(st.session_state.queries)})",
            expanded=False,
        ):
            for q in st.session_state.queries:
                _, clean_query = parse_provider_query(q)
                st.markdown(f"- {clean_query}")

    # -- Profile (collapsed) -----------------------------------------------
    if st.session_state.profile is not None:
        with st.expander("Your AI Profile", expanded=False, icon="📋"):
            _render_profile(st.session_state.profile)

    st.divider()
    _greeting_name = getattr(st.session_state.profile, "first_name", "") if st.session_state.profile else ""
    st.subheader(f"🎯 {_greeting_name}'s Job Matches" if _greeting_name else "🎯 Job Matches")

    # -- Filter controls ---------------------------------------------------
    all_companies = sorted({ej.job.company_name for ej in evaluated_jobs})
    all_locations = sorted({ej.job.location for ej in evaluated_jobs})

    fcol1, fcol2, fcol3, fcol4 = st.columns([2, 2, 1, 1])

    with fcol1:
        selected_companies = st.multiselect(
            "Filter by company",
            options=all_companies,
            default=[],
            placeholder="All companies",
        )

    with fcol2:
        selected_locations = st.multiselect(
            "Filter by location",
            options=all_locations,
            default=[],
            placeholder="All locations",
        )

    with fcol3:
        date_filter = st.selectbox(
            "Published within",
            options=["Any", "Last 24h", "Last 7 days"],
            index=0,
        )

    with fcol4:
        sort_option = st.selectbox(
            "Sort by",
            options=["Score ↓", "Score ↑", "Date (newest)", "Date (oldest)", "Title A–Z", "Company A–Z"],
            index=0,
        )

    # -- Apply filters -----------------------------------------------------
    _date_cutoff = None
    _now = datetime.now(timezone.utc)
    if date_filter == "Last 24h":
        _date_cutoff = _now - timedelta(hours=24)
    elif date_filter == "Last 7 days":
        _date_cutoff = _now - timedelta(days=7)

    # Pre-compute parsed dates once to avoid redundant parsing during filter+sort
    _parsed_dates: dict[str, datetime | None] = {}
    for _ej in evaluated_jobs:
        _pa = _ej.job.posted_at
        if _pa not in _parsed_dates:
            _parsed_dates[_pa] = _parse_relative_date(_pa)

    filtered = [
        ej
        for ej in evaluated_jobs
        if ej.evaluation.score >= min_score
        and (not selected_companies or ej.job.company_name in selected_companies)
        and (not selected_locations or ej.job.location in selected_locations)
        and (_date_cutoff is None or (_parsed_dates[ej.job.posted_at] or _now) >= _date_cutoff)
    ]

    # -- Apply sorting -----------------------------------------------------
    _epoch = datetime.min.replace(tzinfo=timezone.utc)

    sort_key_map: dict[str, tuple] = {
        "Score ↓": (lambda ej: ej.evaluation.score, True),
        "Score ↑": (lambda ej: ej.evaluation.score, False),
        "Date (newest)": (lambda ej: _parsed_dates[ej.job.posted_at] or _epoch, True),
        "Date (oldest)": (lambda ej: _parsed_dates[ej.job.posted_at] or _epoch, False),
        "Title A–Z": (lambda ej: ej.job.title.lower(), False),
        "Company A–Z": (lambda ej: ej.job.company_name.lower(), False),
    }
    key_fn, reverse = sort_key_map[sort_option]
    filtered.sort(key=key_fn, reverse=reverse)

    # -- Metrics row -------------------------------------------------------
    mcol1, mcol2, mcol3 = st.columns(3)
    mcol1.metric("Total matches", len(evaluated_jobs))
    mcol2.metric(f"Score ≥ {min_score}", len(filtered))
    if filtered:
        mcol3.metric("Top score", max(ej.evaluation.score for ej in filtered))

    # -- Cards -------------------------------------------------------------
    if not filtered:
        st.info(f"No jobs match the current filters (score ≥ {min_score}). Try lowering the minimum score.")
    else:
        for ej in filtered:
            _render_job_card(ej)

    # -- Career summary (collapsed, after job cards) -----------------------
    if hasattr(st, "fragment"):

        @st.fragment(run_every="2s")
        def _summary_fragment() -> None:
            _render_career_summary(evaluated_jobs)

        _summary_fragment()
    else:
        pending = _render_career_summary(evaluated_jobs)
        if pending:
            st.caption("Auto-refresh for background summary is unavailable in this Streamlit version.")
            if st.button("Refresh summary", key="refresh_summary_btn"):
                st.rerun()

    # -- Newsletter CTA (after everything) ---------------------------------
    st.markdown(
        '<div class="newsletter-cta">'
        "<h3>Didn't find your dream job yet?</h3>"
        "<p>Get fresh AI-matched jobs delivered to your inbox every day.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    with st.form("subscribe_form"):
        sub_col1, sub_col2 = st.columns([3, 1])
        with sub_col1:
            sub_email = st.text_input(
                "Your email",
                placeholder="you@example.com",
                max_chars=254,
                label_visibility="collapsed",
            )
        with sub_col2:
            sub_submit = st.form_submit_button(
                "Subscribe to Daily Matches",
                use_container_width=True,
                type="primary",
            )
        sub_consent = st.checkbox(
            f"I agree to receive daily job match emails for {SUBSCRIPTION_DAYS} days. See our [Privacy Policy](/privacy).",
            value=False,
        )

    _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    if sub_submit and sub_email:
        if not _EMAIL_RE.match(sub_email.strip()):
            st.error("Please enter a valid email address.")
        elif not sub_consent:
            st.warning("Please agree to the Privacy Policy to subscribe.")
        elif st.session_state.profile is None or st.session_state.queries is None:
            st.warning("Please run a job search before subscribing so we can save your profile.")
        else:
            try:
                from datetime import datetime as _dt
                from datetime import timedelta as _td
                from datetime import timezone as _tz

                from immermatch.db import (
                    add_subscriber,
                    get_job_ids_by_urls,
                    get_subscriber_by_email,
                    log_sent_jobs,
                    save_subscription_context,
                )
                from immermatch.db import (
                    get_admin_client as _get_admin_db,
                )
                from immermatch.db import (
                    upsert_jobs as _upsert_jobs,
                )
                from immermatch.emailer import send_verification_email

                _db = _get_admin_db()
                _token = secrets.token_urlsafe(32)
                _expires = (_dt.now(_tz.utc) + _td(hours=24)).isoformat()
                _signup_ip, _signup_ua = _request_metadata()
                _existing = add_subscriber(
                    _db,
                    sub_email.strip(),
                    _token,
                    _expires,
                    consent_text_version=_CONSENT_TEXT_VERSION,
                    signup_ip=_signup_ip,
                    signup_user_agent=_signup_ua,
                )

                if _existing:
                    st.info("This email address is already subscribed.")
                else:
                    # Fetch the newly-created subscriber row to get its ID
                    _sub_row = get_subscriber_by_email(_db, sub_email.strip())
                    if _sub_row:
                        # Save profile, queries, location for the daily task
                        _ctx_saved = save_subscription_context(
                            _db,
                            _sub_row["id"],
                            profile_json=st.session_state.profile.model_dump(),
                            search_queries=st.session_state.queries,
                            target_location=st.session_state.location or "",
                            min_score=min_score,
                        )
                        if not _ctx_saved:
                            logger.warning(
                                "save_subscription_context returned False for subscriber %s",
                                _sub_row["id"],
                            )
                            st.error("Could not save your subscription context. Please try again.")
                        else:
                            # Pre-seed job_sent_logs with jobs already displayed
                            # so the first newsletter doesn't repeat them
                            try:
                                if st.session_state.evaluated_jobs:
                                    _seen_jobs = []
                                    for _ej in st.session_state.evaluated_jobs:
                                        _url = (
                                            _ej.job.apply_options[0].url if _ej.job.apply_options else _ej.job.link
                                        ) or ""
                                        if _url:
                                            _seen_jobs.append(
                                                {
                                                    "title": _ej.job.title,
                                                    "company": _ej.job.company_name,
                                                    "url": _url,
                                                    "location": _ej.job.location,
                                                    "description": _ej.job.description,
                                                }
                                            )
                                    if _seen_jobs:
                                        _upsert_jobs(_db, _seen_jobs)
                                        _url_to_id = get_job_ids_by_urls(_db, [j["url"] for j in _seen_jobs])
                                        _job_ids = list(_url_to_id.values())
                                        if _job_ids:
                                            log_sent_jobs(_db, _sub_row["id"], _job_ids)
                            except Exception as _seed_err:
                                logger.warning(
                                    "Could not pre-seed sent jobs for %s: %s",
                                    _sub_row["id"],
                                    _seed_err,
                                )

                            _app_url = os.environ.get("APP_URL", "").rstrip("/")
                            _verify_url = f"{_app_url}/verify?token={_token}"
                            send_verification_email(sub_email.strip(), _verify_url)
                            st.success(
                                "Please check your inbox to confirm your subscription. "
                                "The link is valid for 24 hours. "
                                f"You'll receive daily job matches for {SUBSCRIPTION_DAYS} days after confirming."
                            )
                    else:
                        st.error("Could not retrieve your subscription details. Please try again.")
            except Exception:
                logger.exception("Subscription error")
                st.error("Could not subscribe. Please try again later.")

    # -- Manage Subscription -----------------------------------------------
    with st.expander("Manage Subscription", expanded=False):
        _qp_manage_token = st.query_params.get("manage_token", "")
        _manage_token = _qp_manage_token[0] if isinstance(_qp_manage_token, list) else _qp_manage_token
        if _manage_token and st.session_state.get("_manage_token_checked") != _manage_token:
            try:
                from immermatch.db import get_admin_client as _get_manage_db
                from immermatch.db import get_subscriber_by_manage_token as _get_sub_by_manage_token

                _manage_db = _get_manage_db()
                _token_sub = _get_sub_by_manage_token(_manage_db, _manage_token)
                if _token_sub:
                    st.session_state["_manage_sub_data"] = _token_sub
                    st.session_state["_manage_token_value"] = _manage_token
                else:
                    st.session_state.pop("_manage_sub_data", None)
                    st.session_state.pop("_manage_token_value", None)
                    st.warning("This manage link is invalid or expired. Request a new one below.")
            except Exception:
                logger.exception("Manage subscription token lookup error")
                st.error("Could not load subscription. Please try again later.")
            finally:
                st.session_state["_manage_token_checked"] = _manage_token

        with st.form("manage_sub_link_form"):
            _manage_email = st.text_input(
                "Your email",
                placeholder="Enter your subscribed email",
                key="manage_sub_email",
            )
            _send_manage_link_btn = st.form_submit_button("Email secure manage link")

        if _send_manage_link_btn and _manage_email:
            try:
                from immermatch.db import get_admin_client as _get_manage_db
                from immermatch.db import get_subscriber_by_email as _get_sub_by_email
                from immermatch.db import issue_manage_token as _issue_manage_token
                from immermatch.emailer import send_manage_subscription_email as _send_manage_subscription_email

                _manage_db = _get_manage_db()
                _manage_sub = _get_sub_by_email(_manage_db, _manage_email.strip())
                if _manage_sub and _manage_sub.get("is_active"):
                    _manage_token_value = secrets.token_urlsafe(32)
                    _manage_expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                    _issued = _issue_manage_token(
                        _manage_db,
                        _manage_sub["id"],
                        token=_manage_token_value,
                        expires_at=_manage_expires,
                    )
                    if _issued:
                        _app_url = os.environ.get("APP_URL", "").rstrip("/")
                        if _app_url:
                            _manage_url = f"{_app_url}/?manage_token={_manage_token_value}"
                            _send_manage_subscription_email(_manage_email.strip(), _manage_url)
                st.success("If an active subscription exists for this email, we sent you a secure manage link.")
            except Exception:
                logger.exception("Manage subscription link request error")
                st.error("Could not process your request. Please try again later.")

        _manage_sub = st.session_state.get("_manage_sub_data")
        _manage_token_value = st.session_state.get("_manage_token_value")
        if _manage_sub:
            _current_min = _manage_sub.get("min_score") or 70
            _current_cadence = _manage_sub.get("cadence") or "daily"

            with st.form("manage_sub_form"):
                _pref_score = st.slider(
                    "Minimum match score",
                    min_value=0,
                    max_value=100,
                    value=_current_min,
                    step=5,
                    help="Only jobs scoring at or above this threshold will be emailed to you.",
                )
                _pref_cadence = st.radio(
                    "Delivery cadence",
                    options=["daily", "weekly"],
                    index=0 if _current_cadence == "daily" else 1,
                    horizontal=True,
                )
                _save_prefs = st.form_submit_button("Save preferences")
                if _save_prefs:
                    try:
                        from immermatch.db import clear_manage_token as _clear_manage_token
                        from immermatch.db import get_admin_client as _get_manage_db2
                        from immermatch.db import update_subscriber_preferences as _update_prefs

                        _manage_db2 = _get_manage_db2()
                        _ok = _update_prefs(
                            _manage_db2,
                            _manage_sub["id"],
                            min_score=_pref_score,
                            cadence=_pref_cadence,
                        )
                        if _ok:
                            _clear_manage_token(_manage_db2, _manage_sub["id"])
                            st.session_state.pop("_manage_sub_data", None)
                            st.session_state.pop("_manage_token_value", None)
                            st.session_state.pop("_manage_token_checked", None)
                            if "manage_token" in st.query_params:
                                del st.query_params["manage_token"]
                            st.success("Preferences saved.")
                        else:
                            st.error("Could not save preferences. Please try again.")
                    except Exception:
                        logger.exception("Manage subscription save error")
                        st.error("Could not save preferences. Please try again later.")
        elif _manage_token or _manage_token_value:
            st.info("Use the secure manage link from your email to update subscription preferences.")
