"""Run the Python and web checks for a repository quality phase."""

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


def run(phase: str) -> int:
    for command in COMMANDS[phase]:
        result = subprocess.run(command, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python3 scripts/quality_commands.py {lint|test}", file=sys.stderr)
        sys.exit(2)
    sys.exit(run(sys.argv[1]))
