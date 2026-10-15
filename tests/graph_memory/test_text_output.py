"""Text mode prints concise Chinese instead of JSON."""

import json

from graph_memory._base import GraphCliTestCase, LINES, SHARED, require_graph

require_graph()


class TextOutputTests(GraphCliTestCase):
    def assert_text(self, *args, code=0):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        with self.assertRaises(ValueError, msg=result.stdout):
            json.loads(result.stdout)
        self.assertRegex(result.stdout, r"[一-鿿]")
        return result.stdout

    def test_line_commands_print_text(self):
        """line open/extend/close/link 与 archive 的文本输出含编号且不是 JSON。"""
        lid = self.open_line()
        out = self.assert_text("line", "extend", lid, "--node", SHARED + ".u1", "--role", "attempt")
        self.assertIn(lid, out)
        self.assertIn(lid, self.assert_text("line", "close", lid, "--status", "worked", "--outcome", "完成"))
        out = self.assert_text("line", "link", lid, "--rel", "branches_from", "--to", LINES["A1"])
        self.assertIn(LINES["A1"], out)
        self.assertIn(lid, self.assert_text("archive", lid))
        self.assertIn(SHARED, self.assert_text("archive", SHARED))

    def test_similar_candidates_print_text(self):
        """相似候选在文本模式下列出编号而不是 JSON。"""
        lid = self.open_line()
        result = self.run_cli("line", "open", "--title", "重复", "--situation", "盆栽土壤酸碱度读数偏移",
                              "--method", "使用标准溶液校准探头", "--why", "复核", "--from", SHARED)
        self.assertEqual(result.returncode, 3, result.stderr + result.stdout)
        self.assertIn(lid, result.stdout)
        with self.assertRaises(ValueError):
            json.loads(result.stdout)

    def test_lint_prints_text(self):
        """lint 文本模式给出中文说明，有问题时列出线编号与代码。"""
        self.assert_text("lint")
        self.change_line("Q1", why=" ")
        out = self.assert_text("lint", code=1)
        self.assertIn(LINES["Q1"], out)
        self.assertIn("missing_why", out)

    def test_expand_prints_text_without_body(self):
        """recall --expand 文本模式按步骤列出摘要且不泄漏正文。"""
        out = self.assert_text("recall", "x", "--expand", LINES["A1"])
        self.assertIn(SHARED, out)
        self.assertIn("基准确认逐行转换耗时最高。", out)
        self.assertNotIn("BODY_SENTINEL_", out)

    def test_recall_text_omits_empty_branch_and_via(self):
        """L0 文本中空的分支来源和经由行不打印，非空时照常打印。"""
        out = self.assert_text("recall", "CSV 导入服务很慢")
        block = out.split(LINES["A1"], 1)[1].split("\nL-", 1)[0]
        self.assertNotIn("分支来源", block)
        self.assertNotIn("经由", block)
        self.assertIn("分支来源：" + LINES["A1"], out)
