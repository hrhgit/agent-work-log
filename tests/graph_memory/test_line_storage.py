"""Line files and writes, exercised only through the production CLI."""

import subprocess
from datetime import datetime

from graph_memory._base import (
    GraphCliTestCase, LINE_KEYS, LINES, MISSING_NODE, NOW, SHARED, require_graph,
)

require_graph()


class LineStorageTests(GraphCliTestCase):
    def test_open_fields_and_daily_sequence(self):
        """新建线字段齐全且当天编号从 001 依次递增。"""
        first = self.open_line()
        self.assertEqual(first, "L-20261014-001")
        meta = self.line_meta(first)
        self.assertTrue(LINE_KEYS <= set(meta))
        self.assertEqual(meta["schema"], "agent-work-log/line-v1")
        self.assertEqual(meta["id"], first)
        self.assertEqual(meta["title"], "土壤酸碱度校准")
        self.assertEqual(meta["situation"], "盆栽土壤酸碱度读数偏移")
        self.assertEqual(meta["method"], "使用标准溶液校准探头")
        self.assertEqual(meta["why"], "先排除测量误差")
        self.assertEqual(meta["status"], "open")
        self.assertEqual(meta["path"], [{"node": SHARED, "role": "problem"}])
        self.assertEqual(meta["outcome"], "")
        self.assertEqual(meta["relates"], [])
        for key in ("created_at", "updated_at"):
            self.assertEqual(datetime.fromisoformat(str(meta[key])), datetime.fromisoformat(NOW))
        second = self.open_line(title="校准后复核", situation="温室照度偏低", method="清洁灯罩后测量")
        self.assertEqual(second, "L-20261014-002")

    def test_open_rejects_blank_why(self):
        """空白 why 必须返回 2 且不创建线文件。"""
        before = self.line_files()
        self.assert_error(2, "line", "open", "--title", "空理由", "--situation", "全新问题",
                          "--method", "全新方法", "--why", " \t ", "--from", SHARED)
        self.assertEqual(self.line_files(), before)

    def test_open_rejects_missing_start(self):
        """起点不存在时新建线必须返回 2。"""
        before = self.line_files()
        self.assert_error(2, "line", "open", "--title", "缺失起点", "--situation", "全新问题",
                          "--method", "全新方法", "--why", "验证引用", "--from", MISSING_NODE)
        self.assertEqual(self.line_files(), before)

    def test_open_from_second_update(self):
        """第二个更新段可作为新线起点。"""
        lid = self.open_line(node=SHARED + ".u2")
        self.assertEqual(self.line_meta(lid)["path"], [{"node": SHARED + ".u2", "role": "problem"}])

    def test_extend_preserves_order_and_allows_shared_nodes(self):
        """追加保持路径顺序且允许不同线经过同一点。"""
        lid = self.open_line()
        for node, role in [(SHARED + ".u1", "attempt"), (SHARED + ".u2", "evidence")]:
            self.assert_ok("line", "extend", lid, "--node", node, "--role", role)
        self.assertEqual(self.line_meta(lid)["path"], [
            {"node": SHARED, "role": "problem"},
            {"node": SHARED + ".u1", "role": "attempt"},
            {"node": SHARED + ".u2", "role": "evidence"},
        ])
        other = self.open_line(situation="温室照度偏低", method="清洁灯罩后测量")
        self.assertEqual(self.line_meta(other)["path"][0]["node"], SHARED)
        # Only adjacent repetition is prohibited; revisiting an earlier node is valid.
        self.assert_ok("line", "extend", lid, "--node", SHARED, "--role", "decision")
        self.assertEqual(self.line_meta(lid)["path"][-1]["node"], SHARED)

    def test_extend_rejects_tail_duplicate(self):
        """相邻两步引用同一点时返回 2。"""
        lid = self.open_line()
        self.assert_error(2, "line", "extend", lid, "--node", SHARED, "--role", "attempt")
        self.assertEqual(len(self.line_meta(lid)["path"]), 1)

    def test_extend_rejects_missing_node(self):
        """追加不存在的点时返回 2。"""
        lid = self.open_line()
        self.assert_error(2, "line", "extend", lid, "--node", MISSING_NODE, "--role", "attempt")

    def test_extend_rejects_closed_line(self):
        """所有非 open 状态的线都不能追加。"""
        for alias in ("A1", "A2", "A3", "Z1"):
            with self.subTest(alias=alias):
                self.assert_error(2, "line", "extend", LINES[alias], "--node", SHARED + ".u2", "--role", "attempt")

    def test_close_worked_and_abandoned(self):
        """关闭线时保存 worked 或 abandoned 状态及结论。"""
        for status, situation, method in (("worked", "盆栽土壤酸碱度读数偏移", "标准溶液校准"),
                                          ("abandoned", "夜空观测镜头结露", "加热镜片")):
            with self.subTest(status=status):
                lid = self.open_line(situation=situation, method=method)
                outcome = f"合成核验结论 {status}"
                self.assert_ok("line", "close", lid, "--status", status, "--outcome", outcome)
                meta = self.line_meta(lid)
                self.assertEqual(meta["status"], status)
                self.assertEqual(meta["outcome"], outcome)

    def test_close_rejects_blank_outcome(self):
        """空白 outcome 不能关闭线且返回 2。"""
        lid = self.open_line()
        self.assert_error(2, "line", "close", lid, "--status", "worked", "--outcome", " \n ")
        self.assertEqual(self.line_meta(lid)["status"], "open")

    def test_close_rejects_repeated_close(self):
        """重复关闭已关闭的线返回 2。"""
        self.assert_error(2, "line", "close", LINES["A1"], "--status", "worked", "--outcome", "再次关闭")

    def test_link_supersedes_sets_target_status(self):
        """取代关系写到新线上并将旧线标记为 superseded。"""
        lid = self.open_line()
        self.assert_ok("line", "link", lid, "--rel", "supersedes", "--to", LINES["A1"])
        self.assertIn({"line": LINES["A1"], "rel": "supersedes"}, self.line_meta(lid)["relates"])
        self.assertEqual(self.line_meta("A1")["status"], "superseded")

    def test_link_rejects_self_reference(self):
        """线关系不允许自引用并返回 2。"""
        for relation in ("supersedes", "branches_from"):
            with self.subTest(relation=relation):
                self.assert_error(2, "line", "link", LINES["A1"], "--rel", relation, "--to", LINES["A1"])

    def test_link_rejects_supersedes_cycle(self):
        """跨多级取代链形成环时返回 2。"""
        self.assert_error(2, "line", "link", LINES["A5"], "--rel", "supersedes", "--to", LINES["A7"])

    def test_all_line_operations_preserve_daily_bytes(self):
        """新建追加关闭关联与归档后每日日志的哈希完全不变。"""
        before = self.daily_hashes()
        lid = self.open_line()
        self.assertEqual(self.daily_hashes(), before)
        self.assert_ok("line", "extend", lid, "--node", SHARED + ".u1", "--role", "attempt")
        self.assertEqual(self.daily_hashes(), before)
        self.assert_ok("line", "close", lid, "--status", "worked", "--outcome", "校准完成")
        self.assertEqual(self.daily_hashes(), before)
        for rel, target in (("branches_from", "A1"), ("supersedes", "A2")):
            self.assert_ok("line", "link", lid, "--rel", rel, "--to", LINES[target])
            self.assertEqual(self.daily_hashes(), before)
        self.assert_ok("archive", lid)
        self.assertEqual(self.daily_hashes(), before)

    def test_open_branches_from_and_link_relation(self):
        """新建时指定分支与后续关联都写入 branches_from 关系。"""
        lid = self.open_line(branches_from=LINES["A1"])
        self.assertIn({"line": LINES["A1"], "rel": "branches_from"}, self.line_meta(lid)["relates"])
        self.assert_ok("line", "link", lid, "--rel", "branches_from", "--to", LINES["B1"])
        self.assertIn({"line": LINES["B1"], "rel": "branches_from"}, self.line_meta(lid)["relates"])

    def test_first_open_in_git_ignores_worklog(self):
        """Git 项目首次新建线后忽略规则覆盖日志及索引目录。"""
        subprocess.run(["git", "init", "-q", str(self.project)], check=True, capture_output=True)
        (self.project / ".gitignore").write_text("existing-rule/\n", encoding="utf-8")
        lid = self.open_line()
        self.assertIn("existing-rule/", (self.project / ".gitignore").read_text())
        result = subprocess.run(
            ["git", "check-ignore", str(self.line_path(lid)), str(self.log_dir / ".index" / "probe")],
            cwd=self.project, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(result.stdout.splitlines()), {
            str(self.line_path(lid)), str(self.log_dir / ".index" / "probe"),
        })
