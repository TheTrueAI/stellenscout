"""JSON file cache for StellenScout pipeline results."""

import hashlib
import json
from datetime import date
from pathlib import Path

from .models import CandidateProfile, EvaluatedJob, JobEvaluation, JobListing

DEFAULT_CACHE_DIR = Path(".stellenscout_cache")


def _hash(text: str) -> str:
    """Return a short SHA-256 hex digest."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _profile_hash(profile: CandidateProfile) -> str:
    """Stable hash of a profile (used to detect CV changes)."""
    return _hash(profile.model_dump_json(exclude_none=True))


class ResultCache:
    """Manages JSON caches for each pipeline step."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _path(self, name: str) -> Path:
        return self.cache_dir / name

    def _load(self, name: str) -> dict | None:
        path = self._path(name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _save(self, name: str, data: dict) -> None:
        self._path(name).write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------------
    # 1. Profile  (keyed by CV hash)
    # ------------------------------------------------------------------

    def load_profile(self, cv_text: str) -> CandidateProfile | None:
        data = self._load("profile.json")
        if data is None:
            return None
        if data.get("cv_hash") != _hash(cv_text):
            return None
        try:
            return CandidateProfile(**data["profile"])
        except Exception:
            return None

    def save_profile(self, cv_text: str, profile: CandidateProfile) -> None:
        self._save(
            "profile.json",
            {
                "cv_hash": _hash(cv_text),
                "profile": profile.model_dump(),
            },
        )

    # ------------------------------------------------------------------
    # 2. Queries  (keyed by profile hash + location)
    # ------------------------------------------------------------------

    def load_queries(self, profile: CandidateProfile, location: str) -> list[str] | None:
        data = self._load("queries.json")
        if data is None:
            return None
        if data.get("profile_hash") != _profile_hash(profile):
            return None
        if data.get("location") != location:
            return None
        queries = data.get("queries")
        if not isinstance(queries, list):
            return None
        return queries

    def save_queries(self, profile: CandidateProfile, location: str, queries: list[str]) -> None:
        self._save(
            "queries.json",
            {
                "profile_hash": _profile_hash(profile),
                "location": location,
                "queries": queries,
            },
        )

    # ------------------------------------------------------------------
    # 3. Jobs  (date-based, merge new into existing)
    # ------------------------------------------------------------------

    def load_jobs(self, location: str = "") -> list[JobListing] | None:
        """Return cached jobs if they were searched today for the same location."""
        data = self._load("jobs.json")
        if data is None:
            return None
        if data.get("last_search") != date.today().isoformat():
            return None
        if data.get("location", "") != location:
            return None
        jobs_dict = data.get("jobs", {})
        try:
            return [JobListing(**v) for v in jobs_dict.values()]
        except Exception:
            return None

    def save_jobs(self, jobs: list[JobListing], location: str = "") -> None:
        """Merge *jobs* into existing cache and stamp today's date + location."""
        data = self._load("jobs.json") or {}

        # Reset if location changed (different search scope)
        if data.get("location", "") != location:
            existing: dict[str, dict] = {}
        else:
            existing = data.get("jobs", {})

        for job in jobs:
            key = f"{job.title}|{job.company_name}"
            existing[key] = job.model_dump()

        self._save(
            "jobs.json",
            {
                "last_search": date.today().isoformat(),
                "location": location,
                "jobs": existing,
            },
        )

    # ------------------------------------------------------------------
    # 4. Evaluations  (append-only, keyed by title|company)
    # ------------------------------------------------------------------

    def load_evaluations(self, profile: CandidateProfile) -> dict[str, EvaluatedJob]:
        """Return {key: EvaluatedJob} if profile hash matches, else empty dict."""
        data = self._load("evaluations.json")
        if data is None:
            return {}
        if data.get("profile_hash") != _profile_hash(profile):
            return {}
        result: dict[str, EvaluatedJob] = {}
        for key, entry in data.get("evaluated", {}).items():
            try:
                result[key] = EvaluatedJob(
                    job=JobListing(**entry["job"]),
                    evaluation=JobEvaluation(**entry["evaluation"]),
                )
            except Exception:
                continue
        return result

    def save_evaluations(self, profile: CandidateProfile, evaluated: dict[str, EvaluatedJob]) -> None:
        self._save(
            "evaluations.json",
            {
                "profile_hash": _profile_hash(profile),
                "evaluated": {
                    key: {
                        "job": ej.job.model_dump(),
                        "evaluation": ej.evaluation.model_dump(),
                    }
                    for key, ej in evaluated.items()
                },
            },
        )

    def get_unevaluated_jobs(
        self, jobs: list[JobListing], profile: CandidateProfile
    ) -> tuple[list[JobListing], dict[str, EvaluatedJob]]:
        """Return (jobs_to_evaluate, cached_evaluations).

        Jobs already in the evaluation cache are skipped.
        """
        cached = self.load_evaluations(profile)
        new_jobs = [job for job in jobs if f"{job.title}|{job.company_name}" not in cached]
        return new_jobs, cached
