"""Streamlit web UI for JobMatch-DE."""

import os
import uuid
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Inject API keys from Streamlit secrets into env vars
# (must happen before any jobmatch_de imports that read env vars)
# ---------------------------------------------------------------------------
for key in ("GOOGLE_API_KEY", "SERPAPI_KEY"):
    if key not in os.environ:
        try:
            os.environ[key] = st.secrets[key]
        except (KeyError, FileNotFoundError):
            pass  # handled later via validation

from jobmatch_de.cv_parser import extract_text, SUPPORTED_EXTENSIONS  # noqa: E402
from jobmatch_de.llm import create_client  # noqa: E402
from jobmatch_de.search_agent import (  # noqa: E402
    profile_candidate,
    generate_search_queries,
    search_all_queries,
)
from jobmatch_de.evaluator_agent import evaluate_job  # noqa: E402
from jobmatch_de.models import CandidateProfile, EvaluatedJob  # noqa: E402
from jobmatch_de.cache import ResultCache  # noqa: E402

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="JobMatch-DE",
    page_icon="🇩🇪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "session_id": str(uuid.uuid4()),
    "profile": None,
    "queries": None,
    "evaluated_jobs": None,
    "cv_text": None,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------------------------
# Cache scoped to this browser session
# ---------------------------------------------------------------------------
CACHE_ROOT = Path(".jobmatch_cache")


def _get_cache() -> ResultCache:
    return ResultCache(cache_dir=CACHE_ROOT / st.session_state.session_id)


def _cleanup_old_sessions(max_age_hours: int = 24) -> None:
    """Delete session cache dirs older than *max_age_hours*."""
    if not CACHE_ROOT.exists():
        return
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    for child in CACHE_ROOT.iterdir():
        if child.is_dir() and child.name != st.session_state.session_id:
            try:
                mtime = datetime.fromtimestamp(child.stat().st_mtime)
                if mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                pass


# Housekeeping — runs once per session on first load
if "cleanup_done" not in st.session_state:
    _cleanup_old_sessions()
    st.session_state.cleanup_done = True

# ---------------------------------------------------------------------------
# Sidebar — inputs
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🇩🇪 JobMatch-DE")
    st.caption("AI-powered job matching for Germany")
    st.divider()

    uploaded_file = st.file_uploader(
        "Upload your CV",
        type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
        help="Supported formats: PDF, DOCX, Markdown, plain text",
    )

    location = st.text_input("Target location", value="Germany")

    min_score = st.slider(
        "Minimum match score",
        min_value=0,
        max_value=100,
        value=70,
        step=5,
        help="Only show jobs scoring at or above this threshold",
    )

    jobs_per_query = st.slider(
        "Jobs per search query",
        min_value=5,
        max_value=20,
        value=10,
        step=5,
    )

    run_button = st.button(
        "🚀 Find Jobs",
        use_container_width=True,
        disabled=uploaded_file is None,
        type="primary",
    )

    st.divider()
    st.caption(
        "Built with [Streamlit](https://streamlit.io) • "
        "Powered by Gemini & SerpApi"
    )


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
        return extract_text(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helper: display profile (no wrapping expander — always visible)
# ---------------------------------------------------------------------------
def _render_profile(profile: CandidateProfile) -> None:
    st.subheader("📋 Candidate Profile")
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


# ---------------------------------------------------------------------------
# Helper: score emoji
# ---------------------------------------------------------------------------
def _score_emoji(score: int) -> str:
    if score >= 85:
        return "🟢"
    if score >= 70:
        return "🟡"
    if score >= 50:
        return "🟠"
    return "🔴"


# ---------------------------------------------------------------------------
# Profile placeholder — sits at the top, rendered early during pipeline
# ---------------------------------------------------------------------------
profile_slot = st.empty()

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
def _run_pipeline() -> None:
    """Execute the full pipeline with live status updates."""
    cache = _get_cache()
    client = None  # lazy — only created when needed

    # ---- Step 1: Parse CV ------------------------------------------------
    with st.status("📄 Reading CV…", expanded=False) as status:
        cv_text = _extract_uploaded_cv(uploaded_file)
        st.session_state.cv_text = cv_text
        status.update(label="✅ CV loaded", state="complete")

    # ---- Step 2: Profile candidate ---------------------------------------
    with st.status("🧠 Analyzing CV with AI…", expanded=False) as status:
        cached_profile = cache.load_profile(cv_text)
        if cached_profile is not None:
            profile = cached_profile
            status.update(label="✅ Profile extracted (cached)", state="complete")
        else:
            client = create_client()
            profile = profile_candidate(client, cv_text)
            cache.save_profile(cv_text, profile)
            status.update(label="✅ Profile extracted", state="complete")
    st.session_state.profile = profile

    # Show profile immediately in the top slot
    with profile_slot.container():
        _render_profile(profile)

    # ---- Step 3: Generate queries ----------------------------------------
    with st.status("🔍 Generating search queries…", expanded=False) as status:
        cached_queries = cache.load_queries(profile, location)
        if cached_queries is not None:
            queries = cached_queries
            status.update(label="✅ Queries generated (cached)", state="complete")
        else:
            if client is None:
                client = create_client()
            queries = generate_search_queries(client, profile, location)
            cache.save_queries(profile, location, queries)
            status.update(label="✅ Queries generated", state="complete")
    st.session_state.queries = queries

    # ---- Step 4: Search for jobs -----------------------------------------
    with st.status("🌐 Searching for jobs…", expanded=False) as status:
        cached_jobs = cache.load_jobs()
        if cached_jobs is not None:
            jobs = cached_jobs
            status.update(label=f"✅ Found {len(jobs)} jobs (cached)", state="complete")
        else:
            jobs = search_all_queries(queries, jobs_per_query=jobs_per_query, location=location)
            cache.save_jobs(jobs)
            status.update(label=f"✅ Found {len(jobs)} unique jobs", state="complete")

    if not jobs:
        st.warning("No jobs found. Try adjusting your location or uploading a different CV.")
        return

    # ---- Step 5: Evaluate jobs -------------------------------------------
    new_jobs, cached_evals = cache.get_unevaluated_jobs(jobs, profile)

    if not new_jobs:
        with st.status("✅ All evaluations loaded (cached)", state="complete"):
            pass
        all_evals = cached_evals
    else:
        if client is None:
            client = create_client()

        new_evaluated: list[EvaluatedJob] = []
        progress_bar = st.progress(0, text=f"Evaluating 0/{len(new_jobs)} jobs…")

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(evaluate_job, client, profile, job): job
                for job in new_jobs
            }
            for i, future in enumerate(as_completed(futures), 1):
                job = futures[future]
                evaluation = future.result()
                new_evaluated.append(EvaluatedJob(job=job, evaluation=evaluation))
                progress_bar.progress(
                    i / len(new_jobs),
                    text=f"Evaluated {i}/{len(new_jobs)} jobs…",
                )

        progress_bar.empty()

        all_evals = dict(cached_evals)
        for ej in new_evaluated:
            key = f"{ej.job.title}|{ej.job.company_name}"
            all_evals[key] = ej
        cache.save_evaluations(profile, all_evals)

    # Build final sorted list
    evaluated_jobs = sorted(
        all_evals.values(),
        key=lambda x: x.evaluation.score,
        reverse=True,
    )
    st.session_state.evaluated_jobs = evaluated_jobs


# ---------------------------------------------------------------------------
# Validate keys before running
# ---------------------------------------------------------------------------
def _keys_ok() -> bool:
    missing = []
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")
    if not os.getenv("SERPAPI_KEY"):
        missing.append("SERPAPI_KEY")
    if missing:
        st.error(
            f"Missing API key(s): **{', '.join(missing)}**. "
            "Add them to `.streamlit/secrets.toml` or set them as environment variables."
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Run pipeline on button click
# ---------------------------------------------------------------------------
if run_button and uploaded_file is not None:
    if _keys_ok():
        try:
            _run_pipeline()
        except Exception as exc:
            st.error(f"Pipeline error: {exc}")

# ---------------------------------------------------------------------------
# Display persisted state across reruns (when pipeline is NOT running)
# ---------------------------------------------------------------------------
elif st.session_state.profile is not None:
    with profile_slot.container():
        _render_profile(st.session_state.profile)

if not run_button and st.session_state.queries is not None:
    with st.expander(
        f"🔍 **Search Queries** ({len(st.session_state.queries)})",
        expanded=False,
    ):
        for q in st.session_state.queries:
            st.markdown(f"- {q}")

# ---------------------------------------------------------------------------
# Display results — unified card layout
# ---------------------------------------------------------------------------
if st.session_state.evaluated_jobs is not None:
    evaluated_jobs: list[EvaluatedJob] = st.session_state.evaluated_jobs

    st.divider()
    st.subheader("🎯 Job Matches")

    # -- Filter controls ---------------------------------------------------
    all_companies = sorted({ej.job.company_name for ej in evaluated_jobs})
    all_locations = sorted({ej.job.location for ej in evaluated_jobs})

    fcol1, fcol2, fcol3 = st.columns([2, 2, 1])

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
        sort_option = st.selectbox(
            "Sort by",
            options=["Score ↓", "Score ↑", "Title A–Z", "Company A–Z"],
            index=0,
        )

    # -- Apply filters -----------------------------------------------------
    filtered = [
        ej for ej in evaluated_jobs
        if ej.evaluation.score >= min_score
        and (not selected_companies or ej.job.company_name in selected_companies)
        and (not selected_locations or ej.job.location in selected_locations)
    ]

    # -- Apply sorting -----------------------------------------------------
    sort_key_map = {
        "Score ↓": (lambda ej: ej.evaluation.score, True),
        "Score ↑": (lambda ej: ej.evaluation.score, False),
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
        st.info(
            f"No jobs match the current filters (score ≥ {min_score}). "
            "Try lowering the minimum score."
        )
    else:
        for ej in filtered:
            score = ej.evaluation.score
            emoji = _score_emoji(score)
            missing = ", ".join(ej.evaluation.missing_skills) if ej.evaluation.missing_skills else None

            with st.container(border=True):
                left, center, right = st.columns([0.6, 4, 1])

                with left:
                    st.markdown(f"## {emoji}")
                    st.markdown(f"**{score}**/100")

                with center:
                    st.markdown(f"**{ej.job.title}** @ {ej.job.company_name}")
                    st.caption(
                        f"📍 {ej.job.location}"
                        + (f"  •  🕐 {ej.job.posted_at}" if ej.job.posted_at else "")
                    )
                    st.markdown(ej.evaluation.reasoning)
                    if missing:
                        st.markdown(f"**Missing:** {missing}")

                with right:
                    if ej.job.link:
                        st.link_button("Apply ↗", ej.job.link, use_container_width=True)

elif uploaded_file is None:
    # Landing page
    st.markdown(
        """
        ## 🇩🇪 Welcome to JobMatch-DE

        **AI-powered job matching for the German market.**

        1. **Upload your CV** (PDF, DOCX, Markdown, or TXT) in the sidebar
        2. **Choose your target location** (e.g., Munich, Berlin, Remote)
        3. **Click "Find Jobs"** and let AI match you with the best openings

        Your CV is analyzed by Gemini AI, relevant jobs are fetched from
        Google Jobs, and each listing is scored against your profile.
        """
    )
