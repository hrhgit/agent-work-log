"""Shared CLI helpers; never read the user's real work logs."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "record.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "worklog"
NOW = "2026-10-14T10:00:00-07:00"
LINES = {
    "A1": "L-20260920-001", "A2": "L-20260922-001",
    "A3": "L-20260923-001", "A4": "L-20260924-001",
    "A5": "L-20260925-001", "A6": "L-20260926-001",
    "A7": "L-20260927-001", "B1": "L-20260928-001",
    "B2": "L-20260929-001", "C1": "L-20260930-001",
    "Z1": "L-20261003-001", "Q1": "L-20261010-001",
}
SHARED = "W-20260920-001"
ARCHIVED_NODE = "W-20261002-001"
MISSING_NODE = "W-20261009-999"
L0_KEYS = {"id", "title", "status", "situation", "method", "outcome",
           "branched_from", "via"}
LINE_KEYS = {"schema", "id", "title", "status", "situation", "method", "why",
             "path", "outcome", "relates", "created_at", "updated_at"}


def cli_env():
    env = os.environ.copy()
    env["AGENT_WORK_LOG_EMBED"] = "none"
    env.pop("AGENT_WORK_LOG_DIR", None)
    env["AGENT_WORK_LOG_TIMEZONE"] = "America/Los_Angeles"
    return env


def graph_available():
    """Probe only the help command, without opening any work log."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "line", "--help"],
        cwd=ROOT, env=cli_env(), text=True, capture_output=True,
    )
    return result.returncode == 0


def require_graph():
    # Called at module load by every test module, including the lexical gate.
    if not graph_available():
        raise unittest.SkipTest("graph memory 尚未实现")


def read_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---", 2)[1])


def write_frontmatter(path, meta):
    body = path.read_text(encoding="utf-8").split("---", 2)[2]
    path.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
                    + "---" + body, encoding="utf-8")


class GraphCliTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="worklog-graph-test-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        self.log_dir = self.project / "worklog"
        shutil.copytree(FIXTURE, self.log_dir)
        self.env = cli_env()

    def run_cli(self, *args, cwd=None, now=NOW):
        argv = list(args)
        if "--log-dir" not in argv and "--project-root" not in argv:
            argv.extend(["--log-dir", str(self.log_dir)])
        if argv[0] in {"line", "archive", "reindex", "lint"} and "--now" not in argv:
            argv.extend(["--now", now])
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv], cwd=cwd or self.project,
            env=self.env, text=True, capture_output=True,
        )

    def json_cli(self, *args, **kwargs):
        result = self.run_cli(*args, "--json", **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def assert_ok(self, *args, **kwargs):
        result = self.run_cli(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def assert_error(self, code, *args):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        self.assertRegex(result.stderr, r"[\u4e00-\u9fff]", "错误原因应使用中文")
        return result

    def line_path(self, alias_or_id):
        return self.log_dir / "lines" / (LINES.get(alias_or_id, alias_or_id) + ".md")

    def line_meta(self, alias_or_id):
        return read_frontmatter(self.line_path(alias_or_id))

    def change_line(self, alias_or_id, **fields):
        path = self.line_path(alias_or_id)
        meta = read_frontmatter(path)
        meta.update(fields)
        write_frontmatter(path, meta)

    def line_files(self):
        return set((self.log_dir / "lines").glob("L-*.md"))

    def daily_hashes(self):
        return {p.relative_to(self.log_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.log_dir.glob("[0-9][0-9][0-9][0-9]/*.md")}

    def open_line(self, **overrides):
        values = dict(title="土壤酸碱度校准", situation="盆栽土壤酸碱度读数偏移",
                      method="使用标准溶液校准探头", why="先排除测量误差", node=SHARED)
        values.update(overrides)
        args = ["line", "open", "--title", values["title"],
                "--situation", values["situation"], "--method", values["method"],
                "--why", values["why"], "--from", values["node"]]
        if values.get("branches_from"):
            args += ["--branches-from", values["branches_from"]]
        before = self.line_files()
        result = self.assert_ok(*args)
        created = self.line_files() - before
        self.assertEqual(len(created), 1, result.stdout)
        lid = created.pop().stem
        self.assertIn(lid, result.stdout)
        return lid

    def recall(self, query, *args):
        return self.json_cli("recall", query, *args)

    def expand(self, alias):
        # QUERY is supplied because the CLI table declares it positional.
        return self.recall(self.line_meta(alias)["title"], "--expand", LINES[alias])

    def ids(self, view):
        return [row["id"] for row in view["lines"]]

    def assert_no_archived(self, value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        self.assertNotIn("ARCHIVED_SENTINEL_", text)
        self.assertNotIn(LINES["Z1"], text)
        self.assertNotIn(ARCHIVED_NODE, text)

    def assert_empty_recall(self, query):
        view = self.recall(query)
        self.assertEqual(view["lines"], [])
        self.assertEqual(view["message"], "无相关历史")
        self.assertEqual(view["hot_nodes"], [])

    def restore_before_cache_supersession(self):
        self.change_line("A3", status="worked")
        self.change_line("A4", relates=[])
