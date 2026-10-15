"""Only unequivocal near-duplicate and unrelated similarity examples."""

import json

from graph_memory._base import GraphCliTestCase, LINES, SHARED, require_graph

require_graph()


class DedupeTests(GraphCliTestCase):
    def duplicate_args(self, alias):
        meta = self.line_meta(alias)
        return ("line", "open", "--title", "虚构候选", "--situation", meta["situation"],
                "--method", meta["method"], "--why", "核查重复思路", "--from", SHARED)

    def test_near_identical_returns_candidates_without_creation(self):
        """几乎相同的未归档思路返回 3 及候选且不创建文件。"""
        before = self.line_files()
        result = self.run_cli(*self.duplicate_args("A1"), "--json")
        self.assertEqual(result.returncode, 3, result.stderr + result.stdout)
        self.assertEqual(self.line_files(), before)
        candidates = json.loads(result.stdout)["candidates"]
        self.assertIn(LINES["A1"], [row["id"] for row in candidates])
        for row in candidates:
            self.assertTrue({"id", "title", "score"} <= set(row))

    def test_force_new_overrides_duplicate_check(self):
        """相同思路带 force-new 时仍可创建。"""
        before = self.line_files()
        self.assert_ok(*self.duplicate_args("A1"), "--force-new")
        self.assertEqual(len(self.line_files() - before), 1)

    def test_unrelated_situation_and_method_create(self):
        """完全无关的问题与走法直接创建新线。"""
        self.open_line()

    def test_archived_line_is_not_duplicate_candidate(self):
        """与归档线相同的思路不参与重复检查。"""
        before = self.line_files()
        self.assert_ok(*self.duplicate_args("Z1"))
        self.assertEqual(len(self.line_files() - before), 1)
