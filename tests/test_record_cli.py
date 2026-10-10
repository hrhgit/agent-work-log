"""Exercise work-log lookup and write compatibility through the actual CLI."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record.py"


class RecordCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="worklog-cli-test-")
        self.addCleanup(self.temp.cleanup)
        self.project = (Path(self.temp.name) / "project").resolve()
        self.project.mkdir()
        self.env = os.environ.copy()
        self.env.pop("AGENT_WORK_LOG_DIR", None)
        self.env["AGENT_WORK_LOG_TIMEZONE"] = "America/Los_Angeles"

    def run_cli(self, *args, cwd=None, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=cwd or self.project, env=env or self.env,
            text=True, capture_output=True,
        )

    def json_cli(self, *args, **kwargs):
        result = self.run_cli(*args, "--json", **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def write_log(self, body, day="2026-10-01", root=None, summary="当天多个独立任务"):
        root = root or self.project / "worklog"
        path = root / day[:4] / f"{day}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "schema": "agent-work-log/v1", "date": day, "timezone": "America/Los_Angeles",
            "summary": summary, "updated_at": f"{day}T22:00:00-07:00",
            "entry_count": 0, "work_ids": [],
        }
        path.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True) + "---\n\n" + body)
        return path

    def history(self):
        return """<!-- work-id: W-20261001-001 -->
### 10:00 — 工作 | 值班员故障调查
- 状态：进行中
旧结论：只看故障后的读数就可以结束调查。
- 更新时间：2026-10-01T10:00:00-07:00

#### 更新 11:00 — 否定早期方案
否定原因：没有比较事发前的基准，天气变化同时存在时会漏报。
当前结论：查询前后记录，修复后再次验证。
- 状态：已完成
- 更新时间：2026-10-02T11:00:00-07:00

<!-- work-id: W-20261001-002 -->
### 12:00 — 工作 | 不相关任务
- 状态：进行中
这里出现故障，但与上一项工作无关。
- 更新时间：2026-10-01T12:00:00-07:00

<!-- discussion-id: D-20261001-001 -->
### 13:00 — 讨论 | 另一项需求
只讨论读数的显示方式。
- 记录时间：2026-10-01T13:00:00-07:00
"""

    def test_multi_word_query_stays_within_one_entry_and_returns_correction(self):
        path = self.write_log(self.history())
        result = self.json_cli("search", "故障", "读数")
        self.assertEqual([r["record_id"] for r in result["results"]], ["W-20261001-001"])
        entry = result["results"][0]
        self.assertEqual(entry["status"], "已完成")
        self.assertEqual(entry["updated_at"], "2026-10-02T11:00:00-07:00")
        self.assertIn("只看故障后的读数", entry["matches"][0]["text"])
        self.assertIn("没有比较事发前的基准", entry["updates"][0]["text"])
        source_lines = path.read_text().splitlines()
        self.assertEqual(source_lines[entry["line"] - 1], "<!-- work-id: W-20261001-001 -->")
        self.assertEqual(source_lines[entry["updates"][0]["line"] - 1], "#### 更新 11:00 — 否定早期方案")

    def test_early_decision_query_includes_later_update_without_repeated_keyword(self):
        self.write_log(self.history())
        result = self.run_cli("search", "只看")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("没有比较事发前的基准", result.stdout)
        self.assertNotIn("W-20261001-002", result.stdout)

    def test_multi_term_query_starts_at_relevant_update_and_ranks_focused_task(self):
        body = """<!-- work-id: W-20261001-010 -->
### 10:00 — 工作 | 长期研究
- 状态：已完成
CPU 用量检查是更早的无关工作。

#### 更新 11:00 — 其他工作
这里有很长的实验记录，尚未讨论目标规则。

#### 更新 12:00 — 补充运行规则
每张卡的 900 秒是 CPU 计算额度，D1 的等待更长。
背景说明和相关验证保留在这段更新中。

#### 更新 13:00 — 更正说明
需要保留实际运行保护上限。
- 状态：已完成
- 更新时间：2026-10-02T13:00:00-07:00

<!-- work-id: W-20261001-011 -->
### 14:00 — 工作 | 专门核对运行规则
- 状态：已完成
900 秒只算 CPU；D1 等待时间另计。
- 更新时间：2026-10-01T14:00:00-07:00
"""
        self.write_log(body)
        result = self.json_cli("search", "900 CPU D1")["results"]
        self.assertEqual(result[0]["record_id"], "W-20261001-011")
        history = result[1]
        self.assertEqual(len(history["updates"]), 2)
        self.assertIn("补充运行规则", history["updates"][0]["text"])
        self.assertIn("实际运行保护上限", history["updates"][1]["text"])
        self.assertNotIn("其他工作", str(history["updates"]))

    def test_show_returns_exact_whole_record_with_history_and_not_neighbor(self):
        self.write_log(self.history())
        result = self.json_cli("show", "W-20261001-001")
        self.assertEqual(result["record"]["content"], self.history().split(
            "<!-- work-id: W-20261001-002 -->"
        )[0].rstrip())
        self.assertIn("否定早期方案", result["record"]["content"])

    def test_legacy_find_and_explicit_matching_modes(self):
        self.write_log(self.history())
        found = self.json_cli("find", "--query", "故障 读数")
        self.assertEqual(len(found["results"]), 1)
        any_terms = self.json_cli("search", "故障 读数", "--match", "any")
        self.assertEqual(len(any_terms["results"]), 3)
        phrase = self.run_cli("search", "故障 读数", "--match", "phrase")
        self.assertEqual(phrase.returncode, 1)
        self.assertIn("未找到匹配条目", phrase.stdout)

    def test_numeric_budget_keyword_does_not_match_score_substrings(self):
        body = """<!-- work-id: W-20261001-001 -->
### 10:00 — 工作 | 运行时间
900 秒只计 CPU，D1 等待另计。

<!-- work-id: W-20261001-002 -->
### 11:00 — 工作 | 得分统计
D1 平台分数 33,900.5，CPU 用量另有日志。
"""
        self.write_log(body)
        result = self.json_cli("search", "900 CPU D1")["results"]
        self.assertEqual([row["record_id"] for row in result], ["W-20261001-001"])

    def test_phrase_across_update_boundary_keeps_both_parts(self):
        self.write_log(self.history())
        query = "2026-10-01T10:00:00-07:00\n\n#### 更新 11:00"
        result = self.json_cli("search", "--query", query, "--match", "phrase")["results"][0]
        self.assertIn("旧结论", result["matches"][0]["text"])
        self.assertIn("否定原因", result["updates"][0]["text"])

    def test_ambiguous_legacy_root_requires_explicit_log_directory(self):
        self.write_log(self.history())
        self.write_log(self.history(), root=self.project)
        result = self.run_cli("search", "只看", "--root", ".")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--log-dir", result.stderr)
        explicit = self.json_cli("search", "只看", "--log-dir", "worklog")
        self.assertEqual(len(explicit["results"]), 1)

    def test_search_excludes_file_summary_and_uses_latest_status(self):
        body = self.history() + """
#### 更新 14:00 — 仅讨论后续
这里没有创建工作任务。
"""
        self.write_log(body, summary="只出现在全日摘要里的特殊短语")
        result = self.run_cli("search", "特殊短语")
        self.assertEqual(result.returncode, 1)
        unfinished = self.json_cli("search", "故障", "--unfinished")
        self.assertEqual([r["record_id"] for r in unfinished["results"]], ["W-20261001-002"])

    def test_git_nested_default_root_and_legacy_project_root(self):
        self.write_log(self.history())
        subprocess.run(["git", "init", "-q", str(self.project)], check=True, capture_output=True)
        nested = self.project / "src" / "nested"
        nested.mkdir(parents=True)
        for args in [(), ("--root", ".")]:
            result = self.json_cli("search", "只看", *args, cwd=nested)
            self.assertEqual(result["log_dir"], str(self.project / "worklog"))
        write = self.run_cli(
            "append", "--kind", "work", "--title", "正确目录写入",
            "--summary", "已有调查及新任务", "--body", "验证写入目录。", "--root", ".", cwd=nested,
        )
        self.assertEqual(write.returncode, 0, write.stderr)
        self.assertFalse((self.project / "2026").exists())
        self.assertIn("worklog/", (self.project / ".gitignore").read_text())

    def test_non_git_nested_lookup_and_explicit_project_from_elsewhere(self):
        self.write_log(self.history())
        nested = self.project / "src" / "nested"
        nested.mkdir(parents=True)
        result = self.json_cli("show", "W-20261001-001", cwd=nested)
        self.assertEqual(result["log_dir"], str(self.project / "worklog"))
        elsewhere = Path(self.temp.name)
        result = self.json_cli(
            "search", "只看", "--project-root", str(self.project), cwd=elsewhere,
        )
        self.assertEqual(len(result["results"]), 1)

    def test_custom_directory_and_environment_are_honored(self):
        custom = Path(self.temp.name).resolve() / "custom-logs"
        self.write_log(self.history(), root=custom)
        result = self.json_cli("search", "只看", "--log-dir", str(custom))
        self.assertEqual(result["log_dir"], str(custom))
        env = {**self.env, "AGENT_WORK_LOG_DIR": str(custom)}
        result = self.json_cli("show", "W-20261001-001", env=env)
        self.assertEqual(result["log_dir"], str(custom))

    def test_read_commands_do_not_change_files_or_gitignore(self):
        self.write_log(self.history())
        (self.project / ".gitignore").write_text("existing-rule/\n")
        before = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.project.rglob("*") if p.is_file()
        }
        self.json_cli("search", "只看")
        self.json_cli("show", "W-20261001-001")
        after = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.project.rglob("*") if p.is_file()
        }
        self.assertEqual(before, after)

    def test_append_update_and_show_preserve_original_and_new_result(self):
        appended = self.run_cli(
            "append", "--kind", "work", "--title", "CLI 兼容性",
            "--summary", "初始状态", "--body", "旧方案待验证。",
        )
        self.assertEqual(appended.returncode, 0, appended.stderr)
        record_id, filename = appended.stdout.strip().splitlines()
        updated = self.run_cli(
            "update", "--work-id", record_id, "--status", "completed",
            "--summary", "旧方案已否定，新方案验证通过",
            "--body", "否定原因：旧方案条件不足。当前结论：新方案通过独立核验。",
        )
        self.assertEqual(updated.returncode, 0, updated.stderr)
        result = self.json_cli("show", record_id)["record"]
        self.assertEqual(result["status"], "已完成")
        self.assertIn("旧方案待验证", result["content"])
        self.assertIn("新方案通过独立核验", result["content"])
        meta = yaml.safe_load(Path(filename).read_text().split("---", 2)[1])
        self.assertEqual(meta["entry_count"], 1)
        self.assertEqual(meta["work_ids"], [record_id])

    def test_code_examples_do_not_create_records_updates_or_override_status(self):
        fence = chr(96) * 3
        body = self.history() + f"""
{fence}markdown
<!-- work-id: W-FAKE -->
#### 更新 20:00 — 示例
- 状态：已取消
- 更新时间：2099-01-01T20:00:00-07:00
{fence}
"""
        self.write_log(body)
        all_entries = self.json_cli("search", "故障 读数", "--match", "any")["results"]
        self.assertEqual(len(all_entries), 3)
        discussion = self.json_cli("show", "D-20261001-001")["record"]
        self.assertEqual(discussion["status"], "讨论")
        self.assertEqual(discussion["updated_at"], "2026-10-01T13:00:00-07:00")
        result = self.run_cli("show", "W-FAKE")
        self.assertEqual(result.returncode, 1)

    def test_duplicate_id_and_damaged_log_are_reported(self):
        self.write_log(self.history())
        self.write_log(self.history(), day="2026-10-02")
        duplicate = self.run_cli("show", "W-20261001-001")
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("记录编号重复", duplicate.stderr)
        broken = self.project / "worklog" / "2026" / "2026-10-03.md"
        broken.write_text("missing metadata")
        result = self.json_cli("search", "只看")
        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(result["warnings"])
        missing = self.run_cli("search", "不存在的关键词")
        self.assertEqual(missing.returncode, 2)

    def test_missing_logs_and_empty_query_have_clear_results(self):
        result = self.run_cli("search", "未知")
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(self.project / "worklog"), result.stdout)
        self.assertFalse((self.project / "worklog").exists())
        empty = self.run_cli("search")
        self.assertEqual(empty.returncode, 2)

    def test_all_matching_records_and_long_later_correction_are_returned(self):
        body = []
        for number in range(1, 25):
            body.append(f"<!-- work-id: W-20261001-{number:03d} -->\n"
                        f"### 10:00 — 工作 | 相同任务 {number}\n- 状态：已完成\n"
                        "保留所有匹配。\n")
        body[0] += ("\n#### 更新 11:00 — 完整更正\n" + "已有证据。\n" * 200
                    + "更正末尾的完整结论。\n- 状态：已完成\n")
        self.write_log("\n".join(body))
        result = self.json_cli("search", "相同任务")
        self.assertEqual(len(result["results"]), 24)
        first = next(r for r in result["results"] if r["record_id"] == "W-20261001-001")
        self.assertIn("更正末尾的完整结论", first["updates"][0]["text"])


if __name__ == "__main__":
    unittest.main()
