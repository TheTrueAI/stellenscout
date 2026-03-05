#!/usr/bin/env python3
"""Analyze reliability labels to find heuristic gaps.

Reads the JSONL labels file and prints:
1. Confusion matrix (predicted vs actual label)
2. Accuracy per category
3. Domain patterns that should move to _TRUSTED_PORTALS or blocked_portals.txt
4. Suggested code changes

Usage:
    python scripts/analyze_labels.py [--labels PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_LABELS = Path("immermatch/search_api/reliability_labels.jsonl")

CATEGORIES = ("verified", "aggregator", "unverified", "blocked")


def _load_labels(path: Path) -> list[dict]:
    entries: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _print_confusion_matrix(entries: list[dict]) -> None:
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for e in entries:
        matrix[e["predicted"]][e["label"]] += 1

    all_labels = sorted({e["label"] for e in entries} | {e["predicted"] for e in entries})
    col_width = max(len(lbl) for lbl in all_labels + ["predicted \\ label"]) + 2

    print("\n=== Confusion Matrix (predicted \\ actual) ===\n")
    header = "predicted \\ label".ljust(col_width) + "".join(lbl.ljust(col_width) for lbl in all_labels)
    print(header)
    print("-" * len(header))

    for pred in all_labels:
        row = pred.ljust(col_width)
        for actual in all_labels:
            count = matrix[pred][actual]
            cell = str(count) if count else "."
            row += cell.ljust(col_width)
        print(row)


def _print_accuracy(entries: list[dict]) -> None:
    print("\n=== Accuracy ===\n")
    total = len(entries)
    correct = sum(1 for e in entries if e["predicted"] == e["label"])
    print(f"Overall: {correct}/{total} = {correct / total:.0%}" if total else "No entries")

    by_predicted: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_predicted[e["predicted"]].append(e)

    for pred in sorted(by_predicted):
        group = by_predicted[pred]
        group_correct = sum(1 for e in group if e["predicted"] == e["label"])
        print(f"  {pred}: {group_correct}/{len(group)} = {group_correct / len(group):.0%}")


def _print_domain_suggestions(entries: list[dict]) -> None:
    # Collect domains where prediction was wrong
    misclassified: list[dict] = [e for e in entries if e["predicted"] != e["label"]]
    if not misclassified:
        print("\n=== Domain Suggestions ===\n")
        print("No misclassifications found — heuristic is perfect for this dataset!")
        return

    # domain → set of labels assigned by the user
    domain_labels: dict[str, Counter[str]] = defaultdict(Counter)
    domain_sources: dict[str, set[str]] = defaultdict(set)

    for e in misclassified:
        for domain in e.get("domains", []):
            domain_labels[domain][e["label"]] += 1
        for source in e.get("source_names", []):
            if source:
                domain_sources[e.get("domains", ["?"])[0] if e.get("domains") else "?"].add(source)

    print("\n=== Domain Suggestions (from misclassified jobs) ===\n")

    # Suggest trusted portals
    to_trust = []
    to_block = []
    for domain, labels in sorted(domain_labels.items()):
        most_common_label = labels.most_common(1)[0][0]
        count = sum(labels.values())
        sources = domain_sources.get(domain, set())
        source_str = f" (source names: {', '.join(sorted(sources))})" if sources else ""
        if most_common_label == "aggregator":
            to_trust.append((domain, count, source_str))
        elif most_common_label == "blocked":
            to_block.append((domain, count, source_str))

    if to_trust:
        print("Add to _TRUSTED_PORTALS (user labelled as 'aggregator'):")
        for domain, count, source_str in to_trust:
            # Extract the key part of the domain for the portals set
            parts = domain.replace("www.", "").split(".")
            keyword = parts[0] if parts else domain
            print(f'  "{keyword}"  # {domain}{source_str} ({count}x)')

    if to_block:
        print("\nAdd to blocked_portals.txt (user labelled as 'blocked'):")
        for domain, count, source_str in to_block:
            parts = domain.replace("www.", "").split(".")
            keyword = parts[0] if parts else domain
            print(f"  {keyword}  # {domain}{source_str} ({count}x)")

    # Show all misclassified entries for review
    print(f"\n=== All Misclassified ({len(misclassified)}) ===\n")
    for e in misclassified:
        domains_str = ", ".join(e.get("domains", []))
        reason = f" — {e['reason']}" if e.get("reason") else ""
        print(f"  {e['predicted']:12s} → {e['label']:12s} | {domains_str[:60]:60s}{reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS, help="Path to labels JSONL file")
    args = parser.parse_args()

    if not args.labels.exists():
        print(f"Labels file not found: {args.labels}", file=sys.stderr)
        print("Run `python scripts/label_reliability.py` first to generate it.", file=sys.stderr)
        sys.exit(1)

    entries = _load_labels(args.labels)
    if not entries:
        print("Labels file is empty.")
        sys.exit(1)

    unlabelled = [e for e in entries if not e.get("reason") and e["predicted"] == e["label"]]
    if unlabelled:
        print(f"Note: {len(unlabelled)}/{len(entries)} entries still have label == predicted with no reason.")
        print("These might be correct predictions, or might not have been reviewed yet.\n")

    _print_confusion_matrix(entries)
    _print_accuracy(entries)
    _print_domain_suggestions(entries)


if __name__ == "__main__":
    main()
