"""L0 isolation, retrieval fields, replacement chains and shared nodes."""

import json

from graph_memory._base import (
    ARCHIVED_NODE, GraphCliTestCase, L0_KEYS, LINES, SHARED, require_graph,
)

require_graph()


class RecallViewTests(GraphCliTestCase):
    def test_default_json_contains_no_node_body(self):
        """默认 JSON 召回不得泄漏任何点的正文标记。"""
        for alias, lid in LINES.items():
            if alias == "Z1":
                continue
            with self.subTest(alias=alias):
                view = self.recall(self.line_meta(lid)["title"])
                self.assertTrue(view["lines"])
                self.assertNotIn("BODY_SENTINEL_", json.dumps(view, ensure_ascii=False))

    def test_default_text_contains_no_node_body(self):
        """默认文本召回同样不得泄漏任何点的正文标记。"""
        result = self.assert_ok("recall", "CSV 导入服务很慢")
        self.assertIn(LINES["A1"], result.stdout)
        self.assertNotIn("BODY_SENTINEL_", result.stdout)

    def test_archived_content_never_appears_in_results(self):
        """普通查询及直接查询归档文字时结果和热点都隐藏归档内容。"""
        for alias in ("C1", "Q1"):
            self.change_line(alias, situation="归档过滤核验")
        shared_view = self.recall("归档过滤核验", "--by", "situation")
        self.assertEqual(set(self.ids(shared_view)), {LINES["C1"], LINES["Q1"]})
        self.assert_no_archived(shared_view)
        queries = ["归档过滤核验", "CSV 导入服务很慢", "结论规则核验", "试了下统一代码格式化",
                   "ARCHIVED_SENTINEL_Z1", "ARCHIVED_SENTINEL_" + ARCHIVED_NODE,
                   ARCHIVED_NODE, LINES["Z1"]]
        for query in queries:
            with self.subTest(query=query):
                view = self.recall(query, "--limit", "20")
                # The envelope echoes QUERY by contract; inspect every result field.
                self.assert_no_archived({k: v for k, v in view.items() if k != "query"})

    def test_archived_only_query_has_no_history(self):
        """仅命中归档线内容时成功返回无相关历史。"""
        self.assert_empty_recall("ARCHIVED_SENTINEL_Z1")

    def test_archived_node_only_query_has_no_history(self):
        """仅命中已归档点标题时成功返回无相关历史。"""
        self.assert_empty_recall("ARCHIVED_SENTINEL_" + ARCHIVED_NODE)

    def test_unrelated_query_has_no_history(self):
        """完全无关的查询成功返回无相关历史。"""
        self.assert_empty_recall("南极企鹅迁徙路线与火山岩标本")

    def test_explicit_and_default_limits(self):
        """指定上限最多返回两条且默认最多返回五条。"""
        # Give seven eligible lines an exact shared phrase so this is not vacuous.
        aliases = ("A1", "A2", "A4", "A7", "B1", "B2", "C1")
        for alias in aliases:
            self.change_line(alias, situation="召回条数核验专用词")
        full = self.recall("召回条数核验专用词", "--by", "situation", "--limit", "20")
        self.assertEqual(set(self.ids(full)), {LINES[a] for a in aliases})
        limited = self.recall("召回条数核验专用词", "--by", "situation", "--limit", "2")
        default = self.recall("召回条数核验专用词", "--by", "situation")
        self.assertTrue(limited["lines"])
        self.assertLessEqual(len(limited["lines"]), 2)
        self.assertTrue(default["lines"])
        self.assertLessEqual(len(default["lines"]), 5)

    def test_abandoned_line_has_exact_l0_fields(self):
        """放弃的失败经验仍可召回且每条线严格只包含 L0 字段。"""
        view = self.recall("多线程并行导入")
        self.assertIn(LINES["A2"], self.ids(view))
        for row in view["lines"]:
            self.assertEqual(set(row), L0_KEYS)
        row = next(row for row in view["lines"] if row["id"] == LINES["A2"])
        self.assertEqual(row["status"], "abandoned")
        self.assertIn("竞态", row["outcome"])
        self.assertIn("行顺序错乱", row["outcome"])

    def test_superseded_hit_redirects_to_latest(self):
        """仅命中旧缓存方案时返回新方案并记录原始命中编号。"""
        view = self.recall("蓝莓缓存")
        self.assertIn(LINES["A4"], self.ids(view))
        self.assertNotIn(LINES["A3"], self.ids(view))
        row = next(r for r in view["lines"] if r["id"] == LINES["A4"])
        self.assertEqual(row["via"], LINES["A3"])

    def test_multilevel_supersession_preserves_original_via(self):
        """多级取代走到最终方案且 via 保留最初命中的旧线。"""
        view = self.recall("银杏缓冲")
        self.assertIn(LINES["A7"], self.ids(view))
        self.assertNotIn(LINES["A5"], self.ids(view))
        self.assertNotIn(LINES["A6"], self.ids(view))
        row = next(r for r in view["lines"] if r["id"] == LINES["A7"])
        self.assertEqual(row["via"], LINES["A5"])

    def test_old_and_new_hits_return_final_line_once(self):
        """同时命中旧方案与新方案时最终线只返回一次。"""
        view = self.recall("缓存", "--limit", "20")
        self.assertEqual(self.ids(view).count(LINES["A4"]), 1)
        self.assertNotIn(LINES["A3"], self.ids(view))

    def test_hot_nodes_count_and_descending_order(self):
        """取代前同时召回三条重叠线时共享点计数为三且热点降序。"""
        self.restore_before_cache_supersession()
        view = self.recall("CSV 导入服务很慢", "--by", "situation", "--limit", "20")
        self.assertEqual(set(self.ids(view)), {LINES[a] for a in ("A1", "A2", "A3")})
        hot = view["hot_nodes"]
        self.assertIn({"node": SHARED, "count": 3}, hot)
        self.assertIn({"node": SHARED + ".u1", "count": 2}, hot)
        self.assertEqual([h["count"] for h in hot], sorted((h["count"] for h in hot), reverse=True))
        self.assertTrue(all(h["count"] >= 2 for h in hot))
        self.assert_no_archived(hot)

    def test_by_method_crosses_project_boundaries(self):
        """按走法查询二分排查时命中 B1 和 C1 而不命中查文档的 B2。"""
        view = self.recall("二分排查", "--by", "method")
        self.assertEqual(view["by"], "method")
        self.assertTrue({LINES["B1"], LINES["C1"]} <= set(self.ids(view)))
        self.assertNotIn(LINES["B2"], self.ids(view))

    def test_by_situation_keeps_same_problem_different_methods(self):
        """按场景查报表时区错位时命中 B1 和 B2 而不命中 C1。"""
        view = self.recall("报表时区错位", "--by", "situation")
        self.assertEqual(view["by"], "situation")
        self.assertTrue({LINES["B1"], LINES["B2"]} <= set(self.ids(view)))
        self.assertNotIn(LINES["C1"], self.ids(view))

    def test_every_line_exposes_branched_from(self):
        """每条返回线都有分支来源且 A2 的来源为 A1。"""
        view = self.recall("CSV 导入服务很慢", "--limit", "20")
        self.assertIn(LINES["A2"], self.ids(view))
        for row in view["lines"]:
            self.assertIn("branched_from", row)
            self.assertIsInstance(row["branched_from"], list)
        row = next(r for r in view["lines"] if r["id"] == LINES["A2"])
        self.assertEqual(row["branched_from"], [LINES["A1"]])
