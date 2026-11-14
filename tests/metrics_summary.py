#!/usr/bin/env python3
"""Render only aggregate synthetic benchmark numbers in GitHub job summaries."""
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
print("### SHIORI local SQLite benchmark\n")
print(f"Synthetic tasks: {data['dataset_rows']:,} · DB open: {data['database_open_ms']:.2f} ms\n")
print("| Operation | p50 (ms) | p95 (ms) | p99 (ms) |")
print("|---|---:|---:|---:|")
for item in data["measurements"]:
    print(f"| {item['name']} | {item['p50']:.2f} | {item['p95']:.2f} | {item['p99']:.2f} |")
print("\nMeasurements are from synthetic fixtures on shared CI hardware, not customer telemetry.")
