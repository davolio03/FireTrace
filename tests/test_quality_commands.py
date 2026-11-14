import sys
import unittest
from unittest.mock import patch

from scripts import quality_commands


class QualityCommandsTest(unittest.TestCase):
    # Program resolution is tested separately; keep argv as written in COMMANDS here.
    @patch("scripts.quality_commands.shutil.which", return_value=None)
    @patch("scripts.quality_commands.subprocess.run")
    def test_lint_and_test_cover_python_and_web(self, run, _which):
        run.return_value.returncode = 0
        self.assertEqual(quality_commands.run("lint"), 0)
        self.assertEqual(quality_commands.run("test"), 0)
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["uv", "run", "ruff", "check", "."],
                ["npm", "--prefix", "web", "run", "lint"],
                ["uv", "run", "pytest"],
                ["npm", "--prefix", "web", "run", "test"],
            ],
        )

    @patch("scripts.quality_commands.subprocess.run")
    def test_failure_is_returned_without_running_later_commands(self, run):
        run.return_value.returncode = 7
        self.assertEqual(quality_commands.run("lint"), 7)
        self.assertEqual(run.call_count, 1)


class ResolveArgvTest(unittest.TestCase):
    def test_python3_and_python_use_the_current_interpreter(self):
        for name in ("python3", "python"):
            self.assertEqual(
                quality_commands.resolve_argv([name, "x.py", "lint"]),
                [sys.executable, "x.py", "lint"],
            )

    @patch("scripts.quality_commands.shutil.which", return_value="C:/node/npm.cmd")
    def test_programs_resolve_through_path(self, which):
        self.assertEqual(
            quality_commands.resolve_argv(["npm", "run", "lint"]),
            ["C:/node/npm.cmd", "run", "lint"],
        )
        which.assert_called_once_with("npm")

    @patch("scripts.quality_commands.shutil.which", return_value=None)
    def test_unresolvable_program_is_left_unchanged(self, _which):
        self.assertEqual(quality_commands.resolve_argv(["nope", "a"]), ["nope", "a"])


if __name__ == "__main__":
    unittest.main()
