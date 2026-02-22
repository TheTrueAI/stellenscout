"""Tests for CV consent state persistence across Streamlit phases.

The consent checkbox only renders in Phase A (no CV uploaded).
Once a CV is uploaded (Phase B), the checkbox widget disappears.
Streamlit deletes session-state keys for unrendered widgets, so the
consent flag must be stored in a separate non-widget key.

These tests verify that invariant without needing a live Streamlit app:
we simulate what Streamlit does internally (widget-key cleanup) and
check that the consent flag survives.
"""

import pytest

# ---------------------------------------------------------------------------
# Minimal fake that mirrors st.session_state (dict + attribute access)
# ---------------------------------------------------------------------------


class FakeSessionState(dict):
    """Minimal dict-like that also supports attribute access."""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name: str, value):
        self[name] = value


# ---------------------------------------------------------------------------
# Constants matching the real app.py
# ---------------------------------------------------------------------------

WIDGET_KEY = "cv_consent_checkbox"
PERSISTENT_KEY = "_cv_consent_given"

_DEFAULTS = {
    "profile": None,
    "cv_text": None,
    "cv_file_hash": None,
    PERSISTENT_KEY: False,
}


# ---------------------------------------------------------------------------
# Helpers that replicate the relevant app logic
# ---------------------------------------------------------------------------


def _init_session(ss: FakeSessionState) -> None:
    """Replica of the app's default-init loop."""
    for k, v in _DEFAULTS.items():
        if k not in ss:
            ss[k] = v


def _render_checkbox(ss: FakeSessionState, user_checks: bool) -> None:
    """Simulate rendering the Phase-A consent checkbox + on_change callback."""
    ss[WIDGET_KEY] = user_checks
    # The on_change callback syncs widget value → persistent key
    ss[PERSISTENT_KEY] = ss[WIDGET_KEY]


def _streamlit_cleanup_widget(ss: FakeSessionState) -> None:
    """Simulate Streamlit removing the widget key when Phase A is gone."""
    ss.pop(WIDGET_KEY, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConsentPersistence:
    """Consent flag must survive Phase A → Phase B transition."""

    def test_consent_survives_widget_cleanup(self):
        """After the user checks consent and uploads a CV, the consent
        checkbox disappears (Phase B). Streamlit deletes the widget key.
        The persistent flag must still be True."""
        ss = FakeSessionState()
        _init_session(ss)

        # Phase A: user checks the consent box
        _render_checkbox(ss, user_checks=True)
        assert ss[PERSISTENT_KEY] is True

        # CV uploaded → Phase B renders, checkbox widget removed by Streamlit
        ss["cv_text"] = "some cv text"
        ss["cv_file_hash"] = "abc123"
        _streamlit_cleanup_widget(ss)

        # Re-run defaults (Streamlit reruns the script)
        _init_session(ss)

        # The persistent consent flag must survive
        assert ss[PERSISTENT_KEY] is True, (
            "_cv_consent_given was reset to False after widget cleanup — "
            "this means the consent key is still tied to the widget"
        )

    def test_consent_false_by_default(self):
        """Fresh session must start with consent=False."""
        ss = FakeSessionState()
        _init_session(ss)
        assert ss[PERSISTENT_KEY] is False

    def test_unchecking_consent_sets_false(self):
        """If user unchecks consent, the persistent flag must update."""
        ss = FakeSessionState()
        _init_session(ss)

        _render_checkbox(ss, user_checks=True)
        assert ss[PERSISTENT_KEY] is True

        _render_checkbox(ss, user_checks=False)
        assert ss[PERSISTENT_KEY] is False

    def test_cached_profile_sets_consent(self):
        """When a cached profile is loaded, consent should be set True
        (the cache was created with consent)."""
        ss = FakeSessionState()
        _init_session(ss)

        # Simulate cached profile restoration (as the app does on cache hit)
        ss["profile"] = {"skills": ["Python"]}
        ss[PERSISTENT_KEY] = True

        _streamlit_cleanup_widget(ss)
        _init_session(ss)

        assert ss[PERSISTENT_KEY] is True

    def test_persistent_key_differs_from_widget_key(self):
        """The persistent consent key must differ from the checkbox widget key.
        This is the core invariant that prevents the bug."""
        assert PERSISTENT_KEY != WIDGET_KEY, (
            "The persistent consent key and widget key must be different — "
            "Streamlit deletes widget keys for unrendered widgets"
        )


class TestConsentInAppSource:
    """Verify the actual app.py source uses the correct key setup."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        from pathlib import Path

        self.source = (Path(__file__).parent.parent / "stellenscout" / "app.py").read_text()

    def test_checkbox_uses_widget_key_not_persistent(self):
        """The checkbox must use 'cv_consent_checkbox' as its key,
        NOT '_cv_consent_given'."""
        assert 'key="cv_consent_checkbox"' in self.source, "Checkbox should use key='cv_consent_checkbox'"
        # The persistent key must NOT appear as a checkbox widget key
        assert 'key="_cv_consent_given"' not in self.source, (
            "Found key='_cv_consent_given' on a widget — this will be "
            "deleted by Streamlit when the widget stops rendering"
        )

    def test_on_change_callback_syncs_to_persistent_key(self):
        """The checkbox must have an on_change that writes to _cv_consent_given."""
        assert "on_change" in self.source
        assert "_cv_consent_given" in self.source
