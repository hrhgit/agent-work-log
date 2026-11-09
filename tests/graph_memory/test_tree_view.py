"""The opt-in tree view expands line relationships without changing recall L0."""

import json

from graph_memory._base import GraphCliTestCase, LINES, SHARED, require_graph

require_graph()


class TreeViewTests(GraphCliTestCase):
    def test_tree_infers_legacy_fork_and_includes_ancestors(self):
        """旧关系没有 fork_at 时可读，并在树中标出推断分叉点。"""
        view = self.tree("A2")
        self.assertEqual(view["selected"], LINES["A2"])
        self.assertEqual(len(view["roots"]), 1)
        root = view["roots"][0]
        self.assertEqual(root["id"], LINES["A1"])
        self.assertEqual(len(root["children"]), 1)
        child = root["children"][0]
        self.assertEqual(child["id"], LINES["A2"])
        self.assertEqual(child["relation"], "branches_from")
        self.assertEqual(child["fork_at"], SHARED + ".u1")
        self.assertTrue(child["fork_at_inferred"])
        self.assertNotIn("BODY_SENTINEL_", json.dumps(view, ensure_ascii=False))

    def test_tree_root_has_no_branch_children_when_unrelated(self):
        """没有分支关系的线仍返回一个单根树。"""
        view = self.tree("B2")
        self.assertEqual(view["selected"], LINES["B2"])
        self.assertEqual([node["id"] for node in view["roots"]], [LINES["B2"]])
        self.assertEqual(view["roots"][0]["children"], [])

    def test_tree_keeps_replacement_history_as_labeled_edge(self):
        """取代线也保留在树中，但不改变普通 recall 的最新线跳转。"""
        view = self.tree("A4")
        root = view["roots"][0]
        self.assertEqual(root["id"], LINES["A3"])
        child = root["children"][0]
        self.assertEqual(child["id"], LINES["A4"])
        self.assertEqual(child["relation"], "supersedes")
        self.assertIsNone(child["fork_at"])

    def test_tree_is_opt_in_and_recall_shape_is_unchanged(self):
        """普通 recall 仍只返回原来的 L0 字段。"""
        view = self.recall("CSV 导入服务很慢", "--limit", "20")
        self.assertTrue(view["lines"])
        self.assertTrue(all(set(row) == {
            "id", "title", "status", "situation", "method", "outcome",
            "branched_from", "via",
        } for row in view["lines"]))

    def test_tree_text_shows_fork_point(self):
        """文本树显示父子线和分叉点。"""
        result = self.run_cli("tree", LINES["A2"])
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("树状视图", result.stdout)
        self.assertIn(LINES["A1"], result.stdout)
        self.assertIn(LINES["A2"], result.stdout)
        self.assertIn("分支点", result.stdout)
        self.assertIn(SHARED + ".u1", result.stdout)

    def test_archived_tree_requires_explicit_opt_in(self):
        """归档线默认隐藏，显式选项才允许查看。"""
        result = self.run_cli("tree", LINES["Z1"])
        self.assertEqual(result.returncode, 4)
        view = self.json_cli("tree", LINES["Z1"], "--include-archived")
        self.assertEqual(view["selected"], LINES["Z1"])

