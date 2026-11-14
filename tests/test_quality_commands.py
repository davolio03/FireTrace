import unittest
from unittest.mock import patch

from scripts import quality_commands


class QualityCommandsTest(unittest.TestCase):
    @patch("scripts.quality_commands.subprocess.run")
    def test_lint_and_test_cover_python_and_web(self, run):
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


if __name__ == "__main__":
    unittest.main()
