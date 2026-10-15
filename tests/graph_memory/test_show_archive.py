"""Explicit L2 access and archive writes."""

from graph_memory._base import (
    ARCHIVED_NODE, GraphCliTestCase, LINES, SHARED, require_graph,
)

require_graph()


class ShowArchiveTests(GraphCliTestCase):
    def test_show_node_exposes_original_body(self):
        """显式读取点时可见其原文和正文标记。"""
        result = self.assert_ok("show", SHARED)
        self.assertIn("BODY_SENTINEL_" + SHARED, result.stdout)
        self.assertIn("基准确认逐行转换耗时最高。", result.stdout)

    def test_show_update_exposes_update_body(self):
        """显式读取第二个更新点时可见该段原文。"""
        result = self.assert_ok("show", SHARED + ".u2")
        self.assertIn("BODY_SENTINEL_" + SHARED + ".u2", result.stdout)
        self.assertIn("向量化转换保持行顺序。", result.stdout)

    def test_show_line_returns_full_source(self):
        """显式读取线时返回包含 frontmatter 的线全文。"""
        result = self.assert_ok("show", LINES["A1"])
        self.assertIn(self.line_path("A1").read_text(encoding="utf-8").rstrip(), result.stdout)

    def test_show_archived_line_requires_include_archived(self):
        """归档线默认返回 4 且显式允许归档后才可读取。"""
        self.assert_error(4, "show", LINES["Z1"])
        result = self.assert_ok("show", LINES["Z1"], "--include-archived")
        self.assertIn("ARCHIVED_SENTINEL_Z1", result.stdout)
        self.assertIn(self.line_path("Z1").read_text().rstrip(), result.stdout)

    def test_show_archived_node_requires_include_archived(self):
        """归档点默认返回 4 且显式允许归档后才可读取。"""
        self.assert_error(4, "show", ARCHIVED_NODE)
        result = self.assert_ok("show", ARCHIVED_NODE, "--include-archived")
        self.assertIn("ARCHIVED_SENTINEL_" + ARCHIVED_NODE, result.stdout)
        self.assertIn("BODY_SENTINEL_" + ARCHIVED_NODE, result.stdout)

    def test_archive_line_removes_it_from_recall(self):
        """归档线会保存 archived 状态并立即从召回结果消失。"""
        self.assertIn(LINES["A2"], self.ids(self.recall("多线程并行导入")))
        self.assert_ok("archive", LINES["A2"])
        self.assertEqual(self.line_meta("A2")["status"], "archived")
        self.assertNotIn(LINES["A2"], self.ids(self.recall("多线程并行导入")))

    def test_archive_node_writes_registry_without_daily_changes(self):
        """归档点只写归档清单且每日日志保持字节不变。"""
        before = self.daily_hashes()
        self.assert_ok("archive", SHARED)
        registry = (self.log_dir / "lines" / ".archived_nodes").read_text().splitlines()
        self.assertIn(SHARED, registry)
        self.assertIn(ARCHIVED_NODE, registry)
        self.assertEqual(self.daily_hashes(), before)
        self.assert_error(4, "show", SHARED)
        steps = self.expand("A1")["steps"]
        self.assertEqual(next(s for s in steps if s["node"] == SHARED), {"node": SHARED, "archived": True})
