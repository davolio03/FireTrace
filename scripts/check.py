#!/usr/bin/env python3
"""Check team guidance and require real lint/tests when application code exists.

This bootstrap gate does not validate application behavior or radar science.
Contract fixtures have a separate validator with its own dependency metadata.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quality.json"
REQUIRED_FILES = (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    ".engram/config.json",
    "docs/PRODUCT.md",
    "docs/ARCHITECTURE.md",
    "docs/CONTRACTS.md",
    "docs/TEAM.md",
    "docs/STATUS.md",
    "docs/ENGRAM_CLOUD.md",
    "docs/ONBOARDING.md",
    "docs/QUALITY.md",
    "docs/DEMO.md",
    "contracts/README.md",
    ".github/pull_request_template.md",
)
CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go",
    ".rs", ".java", ".kt", ".swift", ".cpp", ".cc", ".c", ".h",
    ".hpp", ".cs", ".rb", ".php", ".html", ".vue", ".svelte",
    ".sql", ".dart", ".sh",
}
SKIP_DIRS = {"node_modules", "dist", "build", "coverage", "__pycache__", ".venv", ".git"}
MARKDOWN_LINK = re.compile(r"\[[^\]\n]+\]\(([^\s)]+)\)")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def guidance_link_errors() -> list[str]:
    """Check local inline link destinations, including new/untracked guidance.

    This is a file-existence check, not a Markdown/anchor or external URL audit.
    """
    problems = []
    documents = [ROOT / name for name in REQUIRED_FILES if name.endswith(".md")]
    documents.extend(ROOT / name for name in (
        "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md",
        "docs/tasks/TEMPLATE.md", "docs/decisions/0001-template.md", "tests/README.md",
    ))
    for document in documents:
        if not document.is_file():
            continue
        for link in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            url = urlsplit(link)
            if url.scheme or url.netloc or not url.path:
                continue
            destination = (document.parent / unquote(url.path)).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                problems.append(f"broken local link in {document.relative_to(ROOT)}: {link}")
    return problems


def source_files(roots: list[str]) -> list[Path]:
    found = []
    for name in roots:
        directory = (ROOT / name).resolve()
        if not directory.is_relative_to(ROOT):
            raise ValueError(f"source root escapes repository: {name}")
        if not directory.is_dir():
            continue
        for item in directory.rglob("*"):
            if not item.is_file() or item.suffix.lower() not in CODE_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in item.relative_to(ROOT).parts):
                continue
            found.append(item.relative_to(ROOT))
    return sorted(set(found))


def validate_command(name: str, value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        raise ValueError(f"commands.{name} must be a list of non-empty argv strings")
    return value


def main() -> int:
    problems = []
    for rel in REQUIRED_FILES:
        file = ROOT / rel
        if not file.is_file() or file.stat().st_size == 0:
            problems.append(f"missing/empty required file: {rel}")
    if problems:
        for problem in problems:
            fail(problem)
        return 2

    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        project = json.loads((ROOT / ".engram/config.json").read_text(encoding="utf-8"))
        if not isinstance(config, dict) or config.get("version") != 1:
            raise ValueError("quality.json requires version 1")
        if not isinstance(project, dict) or project.get("project_name") != "firetrace":
            raise ValueError(".engram/config.json requires project_name firetrace")
        roots = config.get("source_roots")
        if not isinstance(roots, list) or not roots or not all(isinstance(x, str) and x.strip() for x in roots):
            raise ValueError("source_roots must be a non-empty list of directory names")
        commands = config.get("commands")
        if not isinstance(commands, dict):
            raise ValueError("commands must be an object")
        plan = {k: validate_command(k, commands.get(k)) for k in ("lint", "test", "build")}
        sources = source_files(roots)
        problems.extend(guidance_link_errors())
    except (OSError, ValueError) as exc:
        fail(f"invalid repository quality configuration: {exc}")
        return 2

    print(f"Project: {project['project_name']}")
    print(f"Governance: {len(REQUIRED_FILES)} required files present")
    print(f"Application code: {len(sources)} code file(s) under configured source roots")
    if sources:
        print("Sample code paths: " + ", ".join(map(str, sources[:8])))
        for name in ("lint", "test"):
            if not plan[name]:
                problems.append(f"application code detected but commands.{name} is unset in quality.json")
    elif not any(plan.values()):
        print("Bootstrap only: no application source or real stack quality commands yet.")
        print("Configure lint/test BEFORE adding code; this is not a green product test suite.")
    if problems:
        for problem in problems:
            fail(problem)
        return 2

    print("PASS local guidance link destinations (file existence only)")
    for name in ("lint", "test", "build"):
        command = plan[name]
        if not command:
            print(f"SKIP {name}: no command configured")
            continue
        print(f"RUN {name}: {command}", flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT, check=False)
        except OSError as exc:
            fail(f"unable to launch {name}: {exc}")
            return 1
        if result.returncode != 0:
            fail(f"{name} exited with code {result.returncode}")
            return 1
        print(f"PASS {name}")
    print("PASS repository checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
