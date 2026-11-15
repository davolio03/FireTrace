"""Offline configuration tests; no board or network is accessed."""

import argparse
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / ".agents" / "skills" / "kanvas" / "kanvas.py"


def load_cli():
    spec = importlib.util.spec_from_file_location("kanvas_config_test", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KanvasConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "remote.json"
        self.example = self.config.with_name("remote.example.json")
        self.example.write_text('{"url": "https://board.example.invalid/FireTrace/"}')
        config_patch = patch.object(self.cli, "REMOTE_CONFIG", str(self.config))
        config_patch.start()
        self.addCleanup(config_patch.stop)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.args = argparse.Namespace(command="status", local=False)

    def test_missing_config_refuses_before_any_board_access(self):
        with self.assertRaisesRegex(self.cli.KanvasError, "Configure.*remote.json"):
            self.cli.remote_url_for(self.args)

    def test_empty_config_refuses_instead_of_using_local_snapshot(self):
        for data in ({}, {"url": ""}, {"url": "   "}, {"url": None}):
            with self.subTest(data=data):
                self.config.write_text(json.dumps(data))
                with self.assertRaisesRegex(self.cli.KanvasError, "Configure.*remote.json"):
                    self.cli.remote_url_for(self.args)

    def test_configured_remote_is_returned_without_connecting(self):
        url = "https://board.example.invalid/FireTrace/"
        self.config.write_text(json.dumps({"url": url}))
        self.assertEqual(self.cli.remote_url_for(self.args), url)

    def test_explicit_local_server_is_preserved(self):
        self.args.local = True
        self.assertIsNone(self.cli.remote_url_for(self.args))
        self.args.local = False
        self.args.command = "serve"
        self.assertIsNone(self.cli.remote_url_for(self.args))

    def test_generic_kanvas_without_example_keeps_local_behavior(self):
        self.example.unlink()
        self.assertIsNone(self.cli.remote_url_for(self.args))

    def test_environment_remote_is_preserved(self):
        url = "https://board.example.invalid/FireTrace/"
        with patch.dict(os.environ, {"KANVAS_REMOTE_URL": url}):
            self.assertEqual(self.cli.remote_url_for(self.args), url)
