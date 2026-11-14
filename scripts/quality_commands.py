"""Run the Python and web checks for a repository quality phase."""

import shutil
import subprocess
import sys

COMMANDS = {
    "lint": [
        ["uv", "run", "ruff", "check", "."],
        ["npm", "--prefix", "web", "run", "lint"],
    ],
    "test": [
        ["uv", "run", "pytest"],
        ["npm", "--prefix", "web", "run", "test"],
    ],
}


def resolve_argv(command: list[str]) -> list[str]:
    """Make a quality.json argv launchable on every OS without a shell.

    ``python3``/``python`` run with the current interpreter (Windows has no ``python3``
    by default), and other programs resolve through PATH/PATHEXT so Windows finds
    ``npm.cmd``. Unresolvable names are left unchanged and fail with the usual error.
    """
    program, *args = command
    if program in ("python3", "python"):
        return [sys.executable, *args]
    return [shutil.which(program) or program, *args]


def run(phase: str) -> int:
    for command in COMMANDS[phase]:
        result = subprocess.run(resolve_argv(command), check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python3 scripts/quality_commands.py {lint|test}", file=sys.stderr)
        sys.exit(2)
    sys.exit(run(sys.argv[1]))
