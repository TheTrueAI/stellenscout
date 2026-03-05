#!/usr/bin/env python3
"""Generate a reliability-labelling review file from cached jobs.

Reads every jobs.json found under .immermatch_cache/, extracts SerpAPI
listings (Bundesagentur is always "verified" — nothing to review), and
writes one JSONL line per job into the labels file.

Already-labelled keys are preserved; only new jobs are appended.

Usage:
    python scripts/label_reliability.py [--labels PATH] [--cache-dir PATH]

Then open the labels file, and for each entry where the prediction is
wrong, change the "label" field to the correct value:
  verified | aggregator | unverified | blocked
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from immermatch.cache import DEFAULT_CACHE_DIR

DEFAULT_LABELS = Path("immermatch/search_api/reliability_labels.jsonl")


def _extract_domains(apply_options: list[dict]) -> list[str]:
    """Extract netloc from each apply option URL."""
    domains = []
    for opt in apply_options:
        netloc = urlparse(opt.get("url", "")).netloc
        if netloc:
            domains.append(netloc.lower())
    return domains


def _load_existing_labels(path: Path) -> dict[str, dict]:
    """Load existing labels keyed by job key."""
    existing: dict[str, dict] = {}
    if not path.exists():
        return existing
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            existing[entry["key"]] = entry
        except (json.JSONDecodeError, KeyError):
            continue
    return existing


def _collect_jobs(cache_dir: Path) -> list[dict]:
    """Collect all non-bundesagentur jobs from all cache subdirectories."""
    jobs: list[dict] = []
    for jobs_file in sorted(cache_dir.glob("*/jobs.json")):
        try:
            data = json.loads(jobs_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for key, job in data.get("jobs", {}).items():
            if job.get("source") == "bundesagentur":
                continue
            job["_cache_key"] = key
            job["_cache_file"] = str(jobs_file)
            jobs.append(job)
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS, help="Path to labels JSONL file")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Cache root directory")
    args = parser.parse_args()

    if not args.cache_dir.exists():
        print(f"Cache directory not found: {args.cache_dir}", file=sys.stderr)
        sys.exit(1)

    existing = _load_existing_labels(args.labels)
    jobs = _collect_jobs(args.cache_dir)

    if not jobs:
        print("No SerpAPI jobs found in cache.")
        return

    new_count = 0
    lines: list[str] = []

    for job in jobs:
        key = job["_cache_key"]
        if key in existing:
            continue

        domains = _extract_domains(job.get("apply_options", []))
        predicted = job.get("reliability", "unverified")

        entry = {
            "key": key,
            "predicted": predicted,
            "label": predicted,  # pre-fill with prediction; user edits where wrong
            "reason": "",
            "domains": domains,
            "source_names": [opt.get("source", "") for opt in job.get("apply_options", [])],
        }
        lines.append(json.dumps(entry, ensure_ascii=False))
        new_count += 1

    if not lines:
        print(f"All {len(existing)} jobs already labelled. Nothing new to add.")
        return

    # Append new entries to the labels file
    args.labels.parent.mkdir(parents=True, exist_ok=True)
    with args.labels.open("a") as f:
        for line in lines:
            f.write(line + "\n")

    total = len(existing) + new_count
    print(f"Added {new_count} new entries ({total} total). Edit labels in: {args.labels}")


if __name__ == "__main__":
    main()
