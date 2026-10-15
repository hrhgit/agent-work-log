"""L1 path summaries and archive placeholders."""

import json

from graph_memory._base import (
    ARCHIVED_NODE, GraphCliTestCase, L0_KEYS, LINES, SHARED, require_graph,
)

FALLBACK_DAY = """---
schema: agent-work-log/v1
date: '2026-10-11'
timezone: America/Los_Angeles
summary: 虚构测试：结论回退样本
updated_at: '2026-10-11T23:00:00-07:00'
entry_count: 2
work_ids:
- W-20261011-001
- W-20261011-002
---

# 2026-10-11

## 记录

<!-- work-id: W-20261011-001 -->
### 09:00 — 工作 | 元数据在前
- 状态：进行中
- 更新时间：2026-10-11T09:00:00-07:00
- 目标：合成案例验证。
- 验证/证据：BODY_SENTINEL_W-20261011-001
- 未完成/下一步：无。
缓存命中率先按日统计。

<!-- work-id: W-20261011-002 -->
### 10:00 — 工作 | 只有元数据
- 状态：进行中
- 记录时间：2026-10-11T10:00:00-07:00
- 目标：确认回退取目标值。
- 未完成/下一步：BODY_SENTINEL_W-20261011-002
"""

require_graph()


class ExpandViewTests(GraphCliTestCase):
    def test_steps_follow_path_with_summary_fields(self):
        """展开步骤按路径顺序给出摘要字段且不泄漏其余正文。"""
        view = self.expand("A1")
        path = self.line_meta("A1")["path"]
        self.assertEqual(set(view["line"]), L0_KEYS | {"why"})
        self.assertEqual(view["line"]["id"], LINES["A1"])
        self.assertEqual(view["line"]["why"], self.line_meta("A1")["why"])
        self.assertEqual([s["node"] for s in view["steps"]], [p["node"] for p in path])
        for seq, (step, expected) in enumerate(zip(view["steps"], path), 1):
            self.assertEqual(set(step), {"seq", "node", "role", "title", "conclusion", "also_in"})
            self.assertEqual(step["seq"], seq)
            self.assertEqual(step["role"], expected["role"])
            self.assertTrue(step["title"])
            self.assertNotRegex(step["title"], r"\d{2}:\d{2}")
        self.assertNotIn("BODY_SENTINEL_", json.dumps(view, ensure_ascii=False))

    def test_shared_node_lists_other_nonarchived_lines(self):
        """共享点的 also_in 列出其他非归档线且不列自身和归档线。"""
        view = self.expand("A1")
        step = next(s for s in view["steps"] if s["node"] == SHARED)
        self.assertEqual(set(step["also_in"]), {LINES["A2"], LINES["A3"]})
        self.assertNotIn(LINES["A1"], step["also_in"])
        self.assertNotIn(LINES["Z1"], step["also_in"])

    def test_archived_node_is_only_placeholder(self):
        """经过归档点时只返回编号与归档标记而不泄漏标题结论。"""
        view = self.expand("Q1")
        step = next(s for s in view["steps"] if s["node"] == ARCHIVED_NODE)
        self.assertEqual(step, {"node": ARCHIVED_NODE, "archived": True})
        self.assertNotIn("ARCHIVED_SENTINEL_", json.dumps(view, ensure_ascii=False))
        self.assertNotIn("BODY_SENTINEL_", json.dumps(view, ensure_ascii=False))

    def test_expand_archived_line_returns_four(self):
        """展开已归档的线必须返回 4。"""
        self.assert_error(4, "recall", "试了下统一代码格式化", "--expand", LINES["Z1"])

    def test_conclusion_uses_first_result_value(self):
        """存在结果字段时一句结论取其值。"""
        step = self.expand("A1")["steps"][0]
        self.assertEqual(step["conclusion"], "基准确认逐行转换耗时最高。")

    def test_conclusion_uses_first_completion_before_later_result(self):
        """本次完成先于结果出现时取先出现的字段而非固定字段优先级。"""
        step = next(s for s in self.expand("Q1")["steps"] if s["node"] == "W-20260923-001")
        self.assertEqual(step["conclusion"], "重复读取可复用内存结果。")

    def test_conclusion_supports_change_field(self):
        """本次变更字段也可作为一句结论。"""
        step = next(s for s in self.expand("A1")["steps"] if s["node"] == SHARED + ".u2")
        self.assertEqual(step["conclusion"], "向量化转换保持行顺序。")

    def test_conclusion_falls_back_to_first_nonempty_body_line(self):
        """没有结论字段时取正文第一行非空文本。"""
        step = next(s for s in self.expand("Q1")["steps"] if s["node"] == "D-20260928-001")
        self.assertEqual(step["conclusion"], "日期边界先按用户所在地计算。")

    def test_conclusion_truncates_after_eighty_characters(self):
        """超过八十字的一句结论只保留前八十字。"""
        full = "这是一段完全虚构的逐项复核结论，逐行比对输入输出并确认次序一致。" * 4
        self.assertGreater(len(full), 80)
        step = next(s for s in self.expand("Q1")["steps"] if s["node"] == "W-20261001-001")
        self.assertEqual(step["conclusion"], full[:80])

    def fallback_step(self, node):
        (self.log_dir / "2026" / "2026-10-11.md").write_text(FALLBACK_DAY, encoding="utf-8")
        self.assert_ok("line", "extend", LINES["Q1"], "--node", node, "--role", "evidence")
        return next(s for s in self.expand("Q1")["steps"] if s.get("node") == node)

    def test_conclusion_fallback_skips_metadata_fields(self):
        """没有结论字段时跳过状态、目标等元数据行，取第一行非元数据文本。"""
        step = self.fallback_step("W-20261011-001")
        self.assertEqual(step["conclusion"], "缓存命中率先按日统计。")

    def test_conclusion_fallback_uses_goal_when_only_metadata(self):
        """正文只有元数据字段时一句结论取目标的值。"""
        step = self.fallback_step("W-20261011-002")
        self.assertEqual(step["conclusion"], "确认回退取目标值。")
