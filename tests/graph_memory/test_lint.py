"""Independent lint diagnostics on isolated fixture copies."""

import json

from graph_memory._base import (
    GraphCliTestCase, LINES, MISSING_NODE, require_graph,
)

require_graph()


class LintTests(GraphCliTestCase):
    def assert_issue(self, alias, code, **kwargs):
        result = self.run_cli("lint", "--json", **kwargs)
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        issues = json.loads(result.stdout)["issues"]
        self.assertIn({"line": LINES[alias], "code": code}, issues)

    def test_clean_fixture(self):
        """干净样本的 lint 成功且 issues 为空。"""
        self.assertEqual(self.json_cli("lint")["issues"], [])

    def test_missing_why(self):
        """缺少非空理由的线报告 missing_why。"""
        self.change_line("Q1", why=" \t ")
        self.assert_issue("Q1", "missing_why")

    def test_missing_node(self):
        """引用不存在的点时报告 missing_node。"""
        self.change_line("Q1", path=[{"node": MISSING_NODE, "role": "problem"}])
        self.assert_issue("Q1", "missing_node")

    def test_stale_open_uses_controlled_now(self):
        """通过固定 now 判断开放线超过十四天后报告 stale_open。"""
        self.assertEqual(self.json_cli("lint")["issues"], [])
        self.assert_issue("Q1", "stale_open", now="2026-10-25T10:00:00-07:00")
        self.assertEqual(self.json_cli("lint", "--stale-days", "30",
                                       now="2026-10-25T10:00:00-07:00")["issues"], [])

    def test_empty_path(self):
        """空路径的线报告 empty_path。"""
        self.change_line("Q1", path=[])
        self.assert_issue("Q1", "empty_path")

    def test_missing_outcome(self):
        """已关闭但结论为空的线报告 missing_outcome。"""
        for status in ("worked", "abandoned"):
            with self.subTest(status=status):
                self.change_line("Q1", status=status, outcome="")
                self.assert_issue("Q1", "missing_outcome")
