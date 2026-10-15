"""Markdown remains authoritative over a disposable index."""

import os
import shutil
import time

from graph_memory._base import GraphCliTestCase, LINES, require_graph

require_graph()


class IndexTests(GraphCliTestCase):
    def test_deleted_index_rebuilds_identical_recall(self):
        """删除索引后自动重建且完整召回结果保持一致。"""
        before = self.recall("CSV 导入服务很慢", "--limit", "20")
        index = self.log_dir / ".index"
        self.assertTrue(index.is_dir())
        shutil.rmtree(index)
        self.assertEqual(self.recall("CSV 导入服务很慢", "--limit", "20"), before)
        self.assertTrue(index.is_dir())

    def test_manual_source_edit_is_visible_without_reindex(self):
        """手改较新的线文件后召回自动反映新标题。"""
        self.assertIn(LINES["A1"], self.ids(self.recall("profile")))
        title = "profile 靛蓝核验词手工修订的虚构标题"
        self.change_line("A1", title=title)
        index = self.log_dir / ".index"
        newest = max([time.time(), index.stat().st_mtime] +
                     [p.stat().st_mtime for p in index.rglob("*")])
        # Explicit mtime avoids relying on filesystem clock granularity or sleeps.
        os.utime(self.line_path("A1"), (newest + 2, newest + 2))
        view = self.recall("靛蓝核验词")
        row = next(r for r in view["lines"] if r["id"] == LINES["A1"])
        self.assertEqual(row["title"], title)

    def test_explicit_reindex_preserves_recall(self):
        """显式重建索引前后的召回结果完全一致。"""
        before = self.recall("银杏缓冲")
        self.assert_ok("reindex")
        self.assertTrue((self.log_dir / ".index").is_dir())
        self.assertEqual(self.recall("银杏缓冲"), before)
