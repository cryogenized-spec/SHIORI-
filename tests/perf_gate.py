#!/usr/bin/env python3
"""Fail on meaningful local performance regressions with auditable numeric budgets.

Default budgets are intentionally generous until calibrated from more stable runners.
No analytics or benchmark data leave the local machine unless uploaded by CI.
"""
import argparse
import json
from pathlib import Path

DEFAULT_BUDGETS = {
    "database_open_ms": 250.0,
    "point_lookup": 15.0,
    "project_filter": 200.0,
    "due_filter": 200.0,
    "text_search": 200.0,
}


def validate(data, budgets):
    if data.get("schema") != 1 or data.get("dataset_rows", 0) < 1000:
        raise ValueError("Missing or invalid performance fixture")
    measurements = data.get("measurements")
    if not isinstance(measurements, list):
        raise ValueError("Missing measurements array")
    metrics = {entry["name"]: entry for entry in measurements}
    failures = []
    for name, limit in budgets.items():
        value = data.get(name) if name == "database_open_ms" else metrics.get(name, {}).get("p95")
        if not isinstance(value, (float, int)) or not 0 <= value < float("inf"):
            failures.append(f"{name}: absent or nonfinite measurement")
        elif value > limit:
            failures.append(f"{name}: {value:.3f} ms exceeds {limit:.3f} ms")
        else:
            print(f"PASS {name}: {value:.3f} ms (budget {limit:.1f} ms)")
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--budgets", type=Path, default=Path("tests/performance-budgets.json"))
    args = parser.parse_args()
    data = json.loads(args.report.read_text())
    budgets = json.loads(args.budgets.read_text())
    errors = validate(data, budgets)
    if errors:
        raise SystemExit("\n".join(errors))
    print("Performance budget gate passed")


if __name__ == "__main__":
    main()
