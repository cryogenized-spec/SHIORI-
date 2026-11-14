#!/usr/bin/env python3
"""Static safety and structure validation for vendored SHIORI agent skills."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".github" / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REFERENCE_RE = re.compile(r"references/([A-Za-z0-9_.-]+\.md)")
errors = []
skill_count = 0

if not SKILLS.is_dir():
    errors.append(f"Missing skill directory: {SKILLS}")

for path in sorted(SKILLS.glob("*/SKILL.md")):
    skill_count += 1
    content = path.read_text(encoding="utf-8")
    sections = content.split("---", 2)
    if len(sections) < 3 or sections[0].strip():
        errors.append(f"{path}: missing YAML frontmatter")
        continue
    meta = sections[1]
    name = re.search(r"(?m)^name:\s*([a-z0-9-]+)\s*$", meta)
    description = re.search(r"(?m)^description:\s*(.+)?$", meta)
    if not name or not NAME_RE.fullmatch(name.group(1)) or name.group(1) != path.parent.name:
        errors.append(f"{path}: invalid or mismatched name")
    if not description or not description.group(1) and not meta.split("description:", 1)[-1].strip():
        errors.append(f"{path}: missing description")
    if not content.strip().endswith("\n") and not content.endswith("\n"):
        errors.append(f"{path}: missing final newline")
    if len(content.encode()) > 65_536:
        errors.append(f"{path}: overly large skill file")
    for reference in REFERENCE_RE.findall(content):
        target = path.parent / "references" / reference
        if not target.is_file():
            errors.append(f"{path}: missing reference {reference}")
    for item in path.parent.rglob("*"):
        if item.is_symlink():
            errors.append(f"{item}: symlinks are not permitted in vendored skills")
        if item.is_file() and item.suffix not in {".md", ".txt"}:
            errors.append(f"{item}: executable or non-document resource needs explicit review")

if skill_count != 8:
    errors.append(f"Expected 8 reviewed skills, found {skill_count}")
if errors:
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    raise SystemExit(1)
print(f"Valid skill structure and references for {skill_count} SHIORI skills.")
