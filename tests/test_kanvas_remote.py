import copy
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "kanvas" / "kanvas.py"
BOARD_PATH = "/FireTrace/api/board"
BOARD = {
    "kanvas": 1,
    "title": "Test",
    "groups": [{"id": "T", "name": "Test"}],
    "tasks": [{"id": "T-01", "title": "Task", "state": "todo", "group": "T"}],
}


def etag(body):
    return '"' + hashlib.sha1(body).hexdigest()[:20] + '"'


def load_cli():
    spec = importlib.util.spec_from_file_location("kanvas_cli_test", SKILL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, status, body, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != BOARD_PATH:
            self.send_json(404, b'{"error":"not found"}')
            return
        body = json.dumps(self.server.board, ensure_ascii=False).encode()
        self.send_json(200, body, {"ETag": etag(body)})

    def do_PUT(self):
        if self.path != BOARD_PATH:
            self.send_json(404, b'{"error":"not found"}')
            return
        size = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(size)
        with self.server.lock:
            current = json.dumps(self.server.board, ensure_ascii=False).encode()
            expected = self.headers.get("If-Match")
            if not expected:
                self.send_json(428, b'{"error":"expected If-Match"}')
                return
            if expected != etag(current):
                self.send_json(409, current, {"ETag": etag(current)})
                return
            if self.server.conflict_once:
                self.server.conflict_once = False
                board = json.loads(current)
                board["tasks"].append(
                    {"id": "T-02", "title": "Other writer", "state": "proposed", "group": "T"}
                )
                self.server.board = board
                body = json.dumps(board, ensure_ascii=False).encode()
                self.send_json(409, body, {"ETag": etag(body)})
                return
            self.server.board = json.loads(raw)
            self.server.puts += 1
            body = json.dumps(self.server.board, ensure_ascii=False).encode()
            self.send_json(200, body, {"ETag": etag(body)})


class BoardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, board):
        super().__init__(("127.0.0.1", 0), Handler)
        self.board = board
        self.puts = 0
        self.conflict_once = False
        self.lock = threading.Lock()

    @property
    def base_url(self):
        host, port = self.server_address
        return f"http://{host}:{port}/FireTrace/"


class KanvasRemoteTest(unittest.TestCase):
    def setUp(self):
        self.server = BoardServer(copy.deepcopy(BOARD))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.cli = load_cli()
        self.env = patch.dict(
            os.environ,
            {"KANVAS_REMOTE_URL": self.server.base_url, "KANVAS_LOCAL": ""},
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(os.chdir, self.old_cwd)
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_propose_writes_the_live_board_and_not_the_local_file(self):
        code, out, err = self.run_cli("propose", "-", "New task")
        self.assertEqual(code, 0, err)
        self.assertEqual([t["title"] for t in self.server.board["tasks"]], ["Task", "New task"])
        self.assertFalse(Path("kanvas.json").exists())
        self.assertEqual(self.server.puts, 1)

    def test_status_reads_the_live_board_without_writing(self):
        code, out, err = self.run_cli("status")
        self.assertEqual(code, 0, err)
        self.assertIn("Test", out)
        self.assertEqual(self.server.puts, 0)

    def test_an_explicit_local_board_is_refused(self):
        code, out, err = self.run_cli("status", "-b", "other.json")
        self.assertEqual(code, 1)
        self.assertIn("live board", err)
        self.assertEqual(self.server.puts, 0)

    def test_a_conflict_retries_the_command_on_the_fresh_board(self):
        self.server.conflict_once = True
        code, out, err = self.run_cli("note", "T-01", "hello")
        self.assertEqual(code, 0, err)
        self.assertEqual([t["id"] for t in self.server.board["tasks"]], ["T-01", "T-02"])
        notes = self.server.board["tasks"][0]["notes"]
        self.assertTrue(any("hello" in note["text"] for note in notes))
        self.assertEqual(self.server.puts, 1)


if __name__ == "__main__":
    unittest.main()
