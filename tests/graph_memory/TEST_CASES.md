# 图记忆测试对照表

依据 [SPEC.md](SPEC.md)，仅调用真实 CLI，不实现图记忆。1–41 对应任务编号；同编号的多个方法拆开验证各个条件。42 是原词检索评测门槛，43 是仅报告的 P2 目标。

每个测试模块加载时执行 `record.py line --help`；非零即抛出 `unittest.SkipTest("graph memory 尚未实现")`。因此功能未实现时是 **8 个模块跳过**，并不表示下表的 62 个测试方法已经运行。`_base.py` 只负责临时副本、环境和命令调用，不模拟功能。

| 编号 | 文件::方法 | 覆盖的契约条款（SPEC.md 小节名） | 阶段 |
| --- | --- | --- | --- |
| 1 | `test_line_storage.py::test_open_fields_and_daily_sequence` | 线文件；CLI（`scripts/record.py` 的新子命令）：新建线字段齐全且当天编号从 001 依次递增。 | P1 |
| 2 | `test_line_storage.py::test_open_rejects_blank_why` | 线文件；CLI（`scripts/record.py` 的新子命令）：空白 why 必须返回 2 且不创建线文件。 | P1 |
| 3 | `test_line_storage.py::test_open_rejects_missing_start` | 线文件；CLI（`scripts/record.py` 的新子命令）：起点不存在时新建线必须返回 2。 | P1 |
| 4 | `test_line_storage.py::test_open_from_second_update` | 线文件；CLI（`scripts/record.py` 的新子命令）：第二个更新段可作为新线起点。 | P1 |
| 5 | `test_line_storage.py::test_extend_preserves_order_and_allows_shared_nodes` | 线文件；CLI（`scripts/record.py` 的新子命令）：追加保持路径顺序且允许不同线经过同一点。 | P1 |
| 6 | `test_line_storage.py::test_extend_rejects_tail_duplicate` | 线文件；CLI（`scripts/record.py` 的新子命令）：相邻两步引用同一点时返回 2。 | P1 |
| 6 | `test_line_storage.py::test_extend_rejects_missing_node` | 线文件；CLI（`scripts/record.py` 的新子命令）：追加不存在的点时返回 2。 | P1 |
| 6 | `test_line_storage.py::test_extend_rejects_closed_line` | 线文件；CLI（`scripts/record.py` 的新子命令）：所有非 open 状态的线都不能追加。 | P1 |
| 7 | `test_line_storage.py::test_close_worked_and_abandoned` | 线文件；CLI（`scripts/record.py` 的新子命令）：关闭线时保存 worked 或 abandoned 状态及结论。 | P1 |
| 7 | `test_line_storage.py::test_close_rejects_blank_outcome` | 线文件；CLI（`scripts/record.py` 的新子命令）：空白 outcome 不能关闭线且返回 2。 | P1 |
| 7 | `test_line_storage.py::test_close_rejects_repeated_close` | 线文件；CLI（`scripts/record.py` 的新子命令）：重复关闭已关闭的线返回 2。 | P1 |
| 8 | `test_line_storage.py::test_link_supersedes_sets_target_status` | 线文件；CLI（`scripts/record.py` 的新子命令）：取代关系写到新线上并将旧线标记为 superseded。 | P1 |
| 8 | `test_line_storage.py::test_link_rejects_self_reference` | 线文件；CLI（`scripts/record.py` 的新子命令）：线关系不允许自引用并返回 2。 | P1 |
| 8 | `test_line_storage.py::test_link_rejects_supersedes_cycle` | 线文件；CLI（`scripts/record.py` 的新子命令）：跨多级取代链形成环时返回 2。 | P1 |
| 9 | `test_line_storage.py::test_all_line_operations_preserve_daily_bytes` | 线文件；CLI（`scripts/record.py` 的新子命令）：新建追加关闭关联与归档后每日日志的哈希完全不变。 | P1 |
| 10 | `test_line_storage.py::test_open_branches_from_and_link_relation` | 线文件；CLI（`scripts/record.py` 的新子命令）：新建时指定分支与后续关联都写入 branches_from 关系。 | P1 |
| 11 | `test_line_storage.py::test_first_open_in_git_ignores_worklog` | 线文件；CLI（`scripts/record.py` 的新子命令）：Git 项目首次新建线后忽略规则覆盖日志及索引目录。 | P1 |
| 12 | `test_dedupe.py::test_near_identical_returns_candidates_without_creation` | 相似检查（`line open`）；CLI（`scripts/record.py` 的新子命令）：几乎相同的未归档思路返回 3 及候选且不创建文件。 | P1 |
| 13 | `test_dedupe.py::test_force_new_overrides_duplicate_check` | 相似检查（`line open`）；CLI（`scripts/record.py` 的新子命令）：相同思路带 force-new 时仍可创建。 | P1 |
| 14 | `test_dedupe.py::test_unrelated_situation_and_method_create` | 相似检查（`line open`）；CLI（`scripts/record.py` 的新子命令）：完全无关的问题与走法直接创建新线。 | P1 |
| 15 | `test_dedupe.py::test_archived_line_is_not_duplicate_candidate` | 相似检查（`line open`）；CLI（`scripts/record.py` 的新子命令）：与归档线相同的思路不参与重复检查。 | P1 |
| 16 | `test_recall_view.py::test_default_json_contains_no_node_body` | 视图层（上下文隔离）：默认 JSON 召回不得泄漏任何点的正文标记。 | P1 |
| 16 | `test_recall_view.py::test_default_text_contains_no_node_body` | 视图层（上下文隔离）：默认文本召回同样不得泄漏任何点的正文标记。 | P1 |
| 17 | `test_recall_view.py::test_archived_content_never_appears_in_results` | 视图层（上下文隔离）：普通查询及直接查询归档文字时结果和热点都隐藏归档内容。 | P1 |
| 18 | `test_recall_view.py::test_archived_only_query_has_no_history` | 视图层（上下文隔离）：仅命中归档线内容时成功返回无相关历史。 | P1 |
| 18 | `test_recall_view.py::test_archived_node_only_query_has_no_history` | 视图层（上下文隔离）：仅命中已归档点标题时成功返回无相关历史。 | P1 |
| 19 | `test_recall_view.py::test_unrelated_query_has_no_history` | 视图层（上下文隔离）：完全无关的查询成功返回无相关历史。 | P1 |
| 20 | `test_recall_view.py::test_explicit_and_default_limits` | 视图层（上下文隔离）：指定上限最多返回两条且默认最多返回五条。 | P1 |
| 21 | `test_recall_view.py::test_abandoned_line_has_exact_l0_fields` | 视图层（上下文隔离）：放弃的失败经验仍可召回且每条线严格只包含 L0 字段。 | P1 |
| 22 | `test_recall_view.py::test_superseded_hit_redirects_to_latest` | 视图层（上下文隔离）：仅命中旧缓存方案时返回新方案并记录原始命中编号。 | P1 |
| 23 | `test_recall_view.py::test_multilevel_supersession_preserves_original_via` | 视图层（上下文隔离）：多级取代走到最终方案且 via 保留最初命中的旧线。 | P1 |
| 24 | `test_recall_view.py::test_old_and_new_hits_return_final_line_once` | 视图层（上下文隔离）：同时命中旧方案与新方案时最终线只返回一次。 | P1 |
| 25 | `test_recall_view.py::test_hot_nodes_count_and_descending_order` | 视图层（上下文隔离）：取代前同时召回三条重叠线时共享点计数为三且热点降序。 | P1 |
| 26 | `test_recall_view.py::test_by_method_crosses_project_boundaries` | 视图层（上下文隔离）：按走法查询二分排查时命中 B1 和 C1 而不命中查文档的 B2。 | P1 |
| 27 | `test_recall_view.py::test_by_situation_keeps_same_problem_different_methods` | 视图层（上下文隔离）：按场景查报表时区错位时命中 B1 和 B2 而不命中 C1。 | P1 |
| 28 | `test_recall_view.py::test_every_line_exposes_branched_from` | 视图层（上下文隔离）：每条返回线都有分支来源且 A2 的来源为 A1。 | P1 |
| 29 | `test_expand_view.py::test_steps_follow_path_with_summary_fields` | 概念；视图层（上下文隔离）：展开步骤按路径顺序给出摘要字段且不泄漏其余正文。 | P1 |
| 30 | `test_expand_view.py::test_shared_node_lists_other_nonarchived_lines` | 概念；视图层（上下文隔离）：共享点的 also_in 列出其他非归档线且不列自身和归档线。 | P1 |
| 31 | `test_expand_view.py::test_archived_node_is_only_placeholder` | 概念；视图层（上下文隔离）：经过归档点时只返回编号与归档标记而不泄漏标题结论。 | P1 |
| 32 | `test_expand_view.py::test_expand_archived_line_returns_four` | 概念；视图层（上下文隔离）：展开已归档的线必须返回 4。 | P1 |
| 33 | `test_expand_view.py::test_conclusion_uses_first_result_value` | 概念；视图层（上下文隔离）：存在结果字段时一句结论取其值。 | P1 |
| 33 | `test_expand_view.py::test_conclusion_uses_first_completion_before_later_result` | 概念；视图层（上下文隔离）：本次完成先于结果出现时取先出现的字段而非固定字段优先级。 | P1 |
| 33 | `test_expand_view.py::test_conclusion_supports_change_field` | 概念；视图层（上下文隔离）：本次变更字段也可作为一句结论。 | P1 |
| 33 | `test_expand_view.py::test_conclusion_falls_back_to_first_nonempty_body_line` | 概念；视图层（上下文隔离）：没有结论字段时取正文第一行非空文本。 | P1 |
| 33 | `test_expand_view.py::test_conclusion_truncates_after_eighty_characters` | 概念；视图层（上下文隔离）：超过八十字的一句结论只保留前八十字。 | P1 |
| 34 | `test_show_archive.py::test_show_node_exposes_original_body` | CLI（`scripts/record.py` 的新子命令）；视图层（上下文隔离）：显式读取点时可见其原文和正文标记。 | P1 |
| 34 | `test_show_archive.py::test_show_update_exposes_update_body` | CLI（`scripts/record.py` 的新子命令）；视图层（上下文隔离）：显式读取第二个更新点时可见该段原文。 | P1 |
| 35 | `test_show_archive.py::test_show_line_returns_full_source` | CLI（`scripts/record.py` 的新子命令）；视图层（上下文隔离）：显式读取线时返回包含 frontmatter 的线全文。 | P1 |
| 36 | `test_show_archive.py::test_show_archived_line_requires_include_archived` | CLI（`scripts/record.py` 的新子命令）；视图层（上下文隔离）：归档线默认返回 4 且显式允许归档后才可读取。 | P1 |
| 36 | `test_show_archive.py::test_show_archived_node_requires_include_archived` | CLI（`scripts/record.py` 的新子命令）；视图层（上下文隔离）：归档点默认返回 4 且显式允许归档后才可读取。 | P1 |
| 37 | `test_show_archive.py::test_archive_line_removes_it_from_recall` | CLI（`scripts/record.py` 的新子命令）；视图层（上下文隔离）：归档线会保存 archived 状态并立即从召回结果消失。 | P1 |
| 37 | `test_show_archive.py::test_archive_node_writes_registry_without_daily_changes` | CLI（`scripts/record.py` 的新子命令）；视图层（上下文隔离）：归档点只写归档清单且每日日志保持字节不变。 | P1 |
| 38 | `test_index.py::test_deleted_index_rebuilds_identical_recall` | 概念；CLI（`scripts/record.py` 的新子命令）：删除索引后自动重建且完整召回结果保持一致。 | P1 |
| 39 | `test_index.py::test_manual_source_edit_is_visible_without_reindex` | 概念；CLI（`scripts/record.py` 的新子命令）：手改较新的线文件后召回自动反映新标题。 | P1 |
| 40 | `test_index.py::test_explicit_reindex_preserves_recall` | 概念；CLI（`scripts/record.py` 的新子命令）：显式重建索引前后的召回结果完全一致。 | P1 |
| 41 | `test_lint.py::test_clean_fixture` | CLI（`scripts/record.py` 的新子命令）：干净样本的 lint 成功且 issues 为空。 | P1 |
| 41 | `test_lint.py::test_missing_why` | CLI（`scripts/record.py` 的新子命令）：缺少非空理由的线报告 missing_why。 | P1 |
| 41 | `test_lint.py::test_missing_node` | CLI（`scripts/record.py` 的新子命令）：引用不存在的点时报告 missing_node。 | P1 |
| 41 | `test_lint.py::test_stale_open_uses_controlled_now` | CLI（`scripts/record.py` 的新子命令）：通过固定 now 判断开放线超过十四天后报告 stale_open。 | P1 |
| 41 | `test_lint.py::test_empty_path` | CLI（`scripts/record.py` 的新子命令）：空路径的线报告 empty_path。 | P1 |
| 41 | `test_lint.py::test_missing_outcome` | CLI（`scripts/record.py` 的新子命令）：已关闭但结论为空的线报告 missing_outcome。 | P1 |
| 42 | `test_eval_lexical.py::test_lexical_recall_at_five_and_no_forbidden_results` | 视图层（上下文隔离）；阶段：所有原词查询的 recall@5 为一且不得返回禁用线。 | P1 |
| 43 | `eval/run_eval.py::evaluate`（queries.yaml Q13–Q20） | 阶段：paraphrase 目标召回；不作为 P1 硬性测试 | P2 |

## 契约歧义、遗漏与保守处理

1. **A3 的状态与三线热点要求冲突**：A3 被 A4 取代后，按视图层不能直接返回 A3。因此第 25 项只在该测试的临时副本中设 A3 为 worked，并移除 A4 的 supersedes 关系，恢复取代前状态；原 fixture 保留 A3 → A4。A1/A2/A3 共同经过 W-20260920-001（count=3），A1/A2 共同经过其 .u1（count=2），可验证降序且排除归档 Z1 的计数。
2. **归档编号隐藏与展开占位冲突**：默认 recall 的结果、hot_nodes 隐藏归档点；L1 遵循更具体的占位规则，允许 `{"node":...,"archived":true}`，严格禁止标题和结论。
3. **直接查询归档哨兵与 query 回显冲突**：L0 顶层有 query。输入本身含归档哨兵时，仅排除顶层 query 后检查全部结果字段；不要求 CLI 改写用户查询。普通查询的结果及文本仍检查隔离。
4. **`--expand` 是否可省略 QUERY 未说明**：所有展开命令仍提供 QUERY，不要求省略位置参数的扩展语法。
5. **lint 的时间注入未在命令表明确列出**：任务明确要求用 `--now` 控制 lint，因此测试传 `lint --now`；读命令 recall/show 不传。写操作统一固定为 2026-10-14T10:00:00-07:00，stale_open 另用 2026-10-25。
6. **标题去掉时间的边界未明确**：不强制删掉“工作 |”“更新”等标签；只检查标题非空且不含 HH:MM。无结论字段的样本使用纯文本首行，避开列表前缀应否保留的歧义。
7. **80 字的截断尾标记未说明**：按“截断到 80 字”的直接含义取 Python 字符串前 80 个字符，不额外添加省略号。样本只用中文和常见标点，不涉及组合字符计数。
8. **命中顺序、阈值、分数范围、via 多来源优先级未规定**：不规定具体分数和并列排序；相似检查用完全相同的 situation+method 或完全无关输入；多来源只断言最终线去重，不指定该场景的 via。hot_nodes 只要求次数降序，不规定同次数顺序。
9. **同线非相邻重复节点**：契约只禁止相邻重复；测试允许回访较早的点。also_in 按“其他非归档线”包含 superseded 的 A3，不擅自套用 L0 的隐藏规则。
10. **归档标题是否参与 content 检索**：归档点标题不应使非归档线命中；用 C1/Q1 共享归档点、直接查询该点哨兵以及两线同时命中时热点过滤的测试验证。
11. **Git 忽略规则的具体写法未规定**：通过 `git check-ignore` 验证日志线文件和 .index 路径确实被忽略，保留原有规则，不固定规则文本。
12. **show 的新线/更新段 JSON 形状未规定**：用文本模式确认线全文和点的原文片段；不发明 JSON 包装结构，也不要求 .u2 排除同条目的其他段。
13. **评测聚合口径**：recall@k = 前 k 条中命中 expect_any_of 任一的查询数 / 查询总数；forbid 违规按每条查询返回的禁用线编号去重后累计。每条查询均禁止 A3/A5/A6/Z1；原词 Q01–Q12 为 P1，改写 Q13–Q20 为 P2。P2 未规定目标数值，脚本报告结果，不设额外通过线。
14. **未实现时的评测输出**：含 `--json` 时仍遵照任务要求打印“graph memory 尚未实现”并返回 0；实现可用后 `--json` 输出分组及逐条结果。

## 运行与证据边界

```bash
python3 -m unittest discover -s tests -q
python3 -m unittest discover -s tests/graph_memory -t tests -q
python3 tests/graph_memory/eval/run_eval.py
python3 tests/graph_memory/eval/run_eval.py --json
```

测试复制 fixture 到临时目录，清除 AGENT_WORK_LOG_DIR 并设置 America/Los_Angeles；不读取真实日志，不修改生产脚本或 Skill，不提交 Git。原 fixture 不带 .index；索引测试只操作临时副本。未实现时跳过验证的是发现机制，不能作为检索或隔离功能已通过的证据。
