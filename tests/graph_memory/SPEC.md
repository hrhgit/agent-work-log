# Graph memory 接口契约（测试用）

本文件是 worklog 图记忆（点 / 线 / 视图层 / 上下文隔离）的**行为契约**，测试按它编写；实现尚未开始。实现时若需改契约，先改本文件再改测试。

## 概念

- **点（node）**：现有每日 Markdown 里的工作/讨论条目及其“更新”段。
  - 条目编号沿用 `W-YYYYMMDD-NNN` / `D-YYYYMMDD-NNN`。
  - 更新段按出现顺序编号为 `<条目编号>.u1`、`.u2` …（不写入文件，由解析得出）。
  - 点的“标题”= 条目 `###` 标题或更新段 `####` 标题去掉时间；“一句结论”= 该段中 `- 结果：` / `- 本次完成：` / `- 本次变更：` 第一个出现的值；都没有时跳过元数据字段行（`- 状态：`、`- 更新时间：`、`- 记录时间：`、`- 目标：`、`- 验证/证据：`、`- 未完成/下一步：` 等 `- 字段：` 形式的记录要素），取正文第一行非元数据文本；正文只有元数据时取 `- 目标：` 的值。截断到 80 字。
- **线（line）**：一个思路，是经过若干点的**有序路径**。不同线可经过同一点（重叠），两点之间可有多条线。
- **Markdown 是唯一可信来源**；索引在 `<log_dir>/.index/`，可删除后重建。

## 线文件

路径 `<log_dir>/lines/L-YYYYMMDD-NNN.md`（日期为创建当天的本地日期，NNN 当天递增，从 001 起）。YAML frontmatter：

```yaml
schema: agent-work-log/line-v1
id: L-20261014-001
title: "短标题"
status: open            # open | worked | abandoned | superseded | archived
situation: "遇到了什么问题"
method: "怎么走、走法本身"
why: "为什么这么走"      # 必填，非空白
path:                   # 有序；同一线内相邻两步不能是同一点
  - {node: W-20261010-002, role: problem}   # role: problem|attempt|decision|evidence|result
outcome: ""             # worked/abandoned 时必填
relates:                # 线与线的关系
  - {line: L-20261009-003, rel: branches_from}   # rel: branches_from | supersedes
created_at: "2026-10-14T10:00:00-07:00"
updated_at: "2026-10-14T10:00:00-07:00"
```

`superseded` 状态由 `line link A --rel supersedes --to B`（A 取代 B）自动写到 B 上。

## CLI（`scripts/record.py` 的新子命令）

所有命令支持 `--log-dir` / `--project-root`（同现有规则）和 `--json`；写命令支持 `--now <ISO8601>` 以便测试固定时间。错误时退出码非 0，stderr 给中文原因。不加 `--json` 时 stdout 为简洁中文文本（不是 JSON）：写命令给出操作结果与相关编号，`lint` 列出线编号、中文说明与问题代码，`recall --expand` 按步骤列出标题与结论；recall L0 文本中为空的“分支来源”“经由”不打印。

| 命令 | 行为 |
|---|---|
| `line open --title T --situation S --method M --why W --from NODE [--role problem] [--branches-from L] [--force-new]` | 新建线，首个点为 NODE；打印新编号。NODE 不存在 → 退出码 2。`why` 为空白 → 退出码 2。若存在相似的未归档线（见“相似检查”）且未给 `--force-new` → **不创建**，退出码 3，stdout（`--json` 时为 `{"candidates":[{"id","title","score"}]}`）列出候选。 |
| `line extend L --node NODE --role R` | 在 path 末尾追加；NODE 不存在 → 2；与末尾点相同 → 2；L 已关闭（非 open）→ 2。 |
| `line close L --status worked\|abandoned --outcome O` | 关闭；outcome 为空白 → 2；L 非 open → 2。 |
| `line link A --rel supersedes\|branches_from --to B` | 在 A 的 `relates` 写入；`supersedes` 同时把 B 状态设为 `superseded`。自引用或形成 supersedes 环 → 2。 |
| `archive ID` | ID 为线或点。线：状态设为 `archived`。点：写入 `<log_dir>/lines/.archived_nodes`（每行一个编号），不改每日文件。 |
| `reindex` | 从 Markdown 全量重建 `.index/`。 |
| `recall QUERY [--by content\|situation\|method] [--limit 5] [--expand L]` | 见“视图层”。若索引不存在或任一源文件比索引新，先自动重建。 |
| `show ID` | 现有行为扩展到 `L-` 编号与 `.uN` 点；ID 已归档 → 退出码 4 并提示，加 `--include-archived` 才显示。 |
| `lint [--stale-days 14]` | 报告问题，有问题退出码 1：`missing_why`、`missing_node`、`stale_open`（`updated_at` 早于 now−stale-days）、`empty_path`、`missing_outcome`（已关闭但 outcome 空）。`--json` 输出 `{"issues":[{"line","code"}]}`。 |

线操作**不得修改任何每日日志文件**（字节级不变）。首次写入时确保 `.gitignore` 规则覆盖日志目录（沿用现有规则，`.index/` 随之被忽略）。

## 视图层（上下文隔离）

`recall` 默认只返回 **L0**：

```json
{"query": "...", "by": "content",
 "lines": [{"id","title","status","situation","method","outcome","branched_from":[], "via": null}],
 "hot_nodes": [{"node","count"}],
 "message": null}
```

- 最多 `--limit` 条（默认 5）。
- **不包含任何点的正文**；文本模式下同样只输出这些字段。
- `abandoned` 线照常返回（失败经验），只给 L0 字段。
- `superseded` 线不返回；命中它时沿 supersedes 链走到最新的非 superseded 线返回，并设 `via` 为最初命中的旧线编号。同一最终线只出现一次。
- `archived` 线、已归档点**永不出现**在 recall 的任何层级与 `hot_nodes` 中；仅命中归档内容时视为无命中。
- 无命中或全部低于相关性阈值 → `lines: []`，`message: "无相关历史"`，退出码 0。
- `hot_nodes`：被 ≥2 条返回线经过的点，按经过次数降序。
- `--by situation` 只在 situation 上匹配；`--by method` 只在 method 上匹配；`content`（默认）匹配 title+situation+method+why+outcome 以及线所经过点的标题。

`recall --expand L` 返回 **L1**：

```json
{"line": {...L0 字段..., "why": "..."},
 "steps": [{"seq":1,"node","role","title","conclusion","also_in":["L-..."]}]}
```

- 按 path 顺序；`conclusion` 为“一句结论”；**不包含点的其余正文**。
- `also_in` 列出同样经过该点的其他非归档线。
- 已归档的点在 steps 中以 `{"node": ..., "archived": true}` 占位，不给标题和结论。
- L 为 archived → 退出码 4。

`show W-…` 才给出 **L2**（原文）。

## 相似检查（`line open`）

在未归档、非 superseded 的线中，比较新线 `situation + method` 与已有线的相似度；超过阈值即为候选。P1 可用词项重合实现，P2 换 embedding；测试只用“几乎完全相同”与“完全无关”两类明确样本，不依赖具体阈值。

## 阶段

- P1（不依赖 embedding）：除 `eval/` 中标为 `paraphrase` 的查询外，全部测试应通过。
- P2（接入 embedding）：`paraphrase` 查询达到目标召回。

## P2：embedding

### 后端选择

环境变量 `AGENT_WORK_LOG_EMBED`：

| 值 | 行为 |
|---|---|
| `auto`（默认） | 本地后端可用则用，否则静默回退 `none` |
| `none` | 只用 P1 词项检索（P1 测试固定使用此值） |
| `local` | 强制本地后端；不可用时回退词项检索，stderr 输出一行 `embedding 不可用，已回退词项检索：<原因>`，退出码不变 |
| `fake:<json 路径>` | 测试用确定性后端：JSON 为 `{"<文本>": [向量]}`；未列出的文本用其 sha256 派生的固定伪随机单位向量；每次调用把请求的文本追加到 `<json 路径>.calls`（每行一条 JSON 数组），用于断言缓存 |

### 本地后端

- 依赖不进入 `record.py` 的运行环境：在 `<skill>/.venv` 中用 uv 安装（onnx 运行时，不装 torch），由 `scripts/embed_worker.py` 在该 venv 中以子进程运行，JSON 经 stdin/stdout 交换。解释器可用 `AGENT_WORK_LOG_EMBED_PYTHON` 覆盖。
- 模型缓存放在 `~/.cache/agent-work-log/models`；recall 等命令**不触发下载**，只用本地已有文件。下载只发生在 `record.py embed-setup`。
- 模型标识（名称+版本）存入索引 meta；变化时重算向量。

### 嵌入什么

每条非归档线三个向量：`situation`、`method`、`content`（title+situation+method+why+outcome+所经过点的标题）。查询按 `--by` 对应字段比较。

### 向量缓存

`<log_dir>/.index/embeddings.sqlite`，键为 (模型标识, 角色 query|passage, 文本 sha256)。全量 reindex 不清空它；文本未变时不重复调用后端。

### 打分与命中

- `lex` = P1 分数；`cos` = 余弦相似度。
- 命中：`lex ≥ LEX_THRESHOLD` 或 `cos ≥ SEM_THRESHOLD`。
- 排序分：`0.5·lex + 0.5·clip((cos − SEM_FLOOR)/(1 − SEM_FLOOR), 0, 1)`，并列规则同 P1。
- 阈值为每个后端各自的常量（fake 后端固定 `SEM_THRESHOLD=0.8, SEM_FLOOR=0.5`）。
- 视图层规则（L0 字段、取代重定向、归档排除、limit、无相关历史）与 P1 完全一致，语义命中与词项命中同等对待。

### 相似检查

`line open` 的候选条件扩展为：Jaccard ≥ 0.6 **或** `situation+method` 向量余弦 ≥ `DEDUP_SEM_THRESHOLD`（fake 后端 0.95）。

### 新命令

`embed-setup [--model NAME]`：创建 venv、安装依赖、下载模型，打印模型标识与缓存位置。`embed-status`：打印当前后端、模型标识、是否可用。
