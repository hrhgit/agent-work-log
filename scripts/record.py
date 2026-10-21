#!/usr/bin/env python3
"""Create and update date-grouped agent work logs.

The skill owns the decision of *when* to write and *what* to summarize. This
script provides the deterministic file, ID, frontmatter, and section mechanics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from types import SimpleNamespace

import graph_memory

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only on minimal hosts
    raise SystemExit("PyYAML is required by agent-work-log/scripts/record.py") from exc


FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
ID_RE = re.compile(r"<!--\s*(discussion|work)-id:\s*([^\s]+)\s*-->")
WORK_STATUS_RE = re.compile(r"(?m)^- 状态：[^\r\n]*$")
DAILY_FILE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.md")
RECORD_MARKER_RE = re.compile(r"(?m)^<!--\s*(discussion|work)-id:\s*([^\s]+)\s*-->[ \t]*$")
UPDATE_RE = re.compile(r"(?m)^####[ \t]+更新[^\r\n]*$")
TIMESTAMP_RE = re.compile(r"(?m)^-\s*(?:更新时间|记录时间)[：:]\s*([^\r\n]+)$")


def local_now() -> datetime:
    return datetime.now().astimezone()


def iso_timestamp(value: datetime | None = None) -> str:
    return (value or local_now()).isoformat(timespec="seconds")


def local_date(value: datetime | None = None) -> str:
    return (value or local_now()).date().isoformat()


def local_timezone_name(value: datetime | None = None) -> str:
    stamp = value or local_now()
    configured = os.environ.get("AGENT_WORK_LOG_TIMEZONE")
    if configured:
        return configured
    offset = stamp.utcoffset()
    if offset is None:
        return "local"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    absolute = abs(total_minutes)
    return f"UTC{sign}{absolute // 60:02d}:{absolute % 60:02d}"


def project_root(start: Path | None = None) -> Path:
    """Use Git, or locate an existing worklog/project marker above the cwd."""

    current = (start or Path.cwd()).expanduser().resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            cwd=current,
        )
        candidate = result.stdout.strip()
        if candidate:
            return Path(candidate).resolve()
    except (OSError, subprocess.CalledProcessError):
        pass
    if start is None:
        for candidate in (current, *current.parents):
            if (candidate / "worklog").is_dir() or (candidate / "AGENTS.md").is_file():
                return candidate
    return current


def git_root_for(path: Path) -> Path | None:
    """Return the Git work-tree root containing *path*, if any."""

    candidate = path if path.exists() else path.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return Path(value).resolve() if value else None


def resolve_root(
    explicit: str | None = None, *, log_dir: str | None = None, project: str | None = None
) -> Path:
    """Resolve an exact log directory or a project's default worklog directory."""

    base = project_root(Path(project)) if project is not None else project_root()
    raw = log_dir or explicit or (None if project is not None else os.environ.get("AGENT_WORK_LOG_DIR"))
    if raw is None:
        path = base / "worklog"
    else:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve()
        if explicit is not None:
            # Legacy --root was often mistaken for a project directory. Existing
            # custom log directories remain exact; --log-dir is always exact.
            direct_logs = any(path.glob("[0-9][0-9][0-9][0-9]/????-??-??.md"))
            child = path / "worklog"
            if direct_logs and child.is_dir():
                raise ValueError(
                    f"目录同时含日期日志和 worklog/：{path}；请用 --log-dir 指明日志目录"
                )
            if not direct_logs and (
                path == base or child.is_dir() or git_root_for(path) == path
            ):
                path = child
    if path.exists() and not path.is_dir():
        raise ValueError(f"日志目录不是文件夹：{path}")
    return path.resolve()


def args_root(args: argparse.Namespace) -> Path:
    return resolve_root(args.root, log_dir=args.log_dir, project=args.project_root)


def daily_path(root: Path, date_value: str) -> Path:
    year = date_value[:4]
    return root / year / f"{date_value}.md"


def dump_frontmatter(meta: dict[str, Any]) -> str:
    text = yaml.safe_dump(
        meta,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
    ).rstrip()
    return f"---\n{text}\n---\n\n"


def default_meta(date_value: str, stamp: str, timezone: str) -> dict[str, Any]:
    return {
        "schema": "agent-work-log/v1",
        "date": date_value,
        "timezone": timezone,
        "summary": "暂无摘要；首次写入后维护。",
        "updated_at": stamp,
        "entry_count": 0,
        "work_ids": [],
    }


def parse_log(content: str, path: Path, date_value: str | None = None) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(f"日志缺少 YAML frontmatter: {path}")
    parsed = yaml.safe_load(match.group(1))
    if not isinstance(parsed, dict):
        raise ValueError(f"YAML frontmatter 必须是对象: {path}")
    body = content[match.end() :]
    parsed.setdefault("schema", "agent-work-log/v1")
    parsed.setdefault("date", date_value or local_date())
    parsed.setdefault("timezone", local_timezone_name())
    parsed.setdefault("summary", "暂无摘要；首次写入后维护。")
    parsed.setdefault("updated_at", iso_timestamp())
    parsed.setdefault("entry_count", len(list(ID_RE.finditer(body))))
    parsed.setdefault("work_ids", [m.group(2) for m in ID_RE.finditer(body) if m.group(1) == "work"])
    if not isinstance(parsed.get("work_ids"), list):
        parsed["work_ids"] = []
    return parsed, body


def read_log(path: Path, date_value: str | None = None) -> tuple[dict[str, Any], str]:
    if not path.exists():
        stamp = iso_timestamp()
        date_text = date_value or local_date()
        meta = default_meta(date_text, stamp, local_timezone_name())
        return meta, f"# {date_text}\n\n## 记录\n\n"
    return parse_log(path.read_text(encoding="utf-8"), path, date_value)


def write_log(path: Path, meta: dict[str, Any], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_frontmatter(meta) + body.lstrip("\n"), encoding="utf-8", newline="\n")


def ensure_gitignore(log_root: Path, *, track: bool = True) -> bool:
    """Keep the log directory under version control; ignore only its derived index.

    Default (user preference): worklog/ is committed and uploaded with the
    project, and only worklog/.index/ (rebuildable cache) is ignored. Set
    AGENT_WORK_LOG_IGNORE=1 to restore the old behaviour of ignoring the whole
    directory. Returns True when the needed rule was added or already existed.
    A custom log root outside Git is deliberately left untouched.
    """

    ignore_all = os.environ.get("AGENT_WORK_LOG_IGNORE") == "1"
    if not ignore_all and not track:
        return False
    git_root = git_root_for(log_root)
    if git_root is None:
        return False
    resolved_log_root = log_root.resolve()
    try:
        relative = resolved_log_root.relative_to(git_root)
    except ValueError:
        return False
    if not relative.parts:
        return False

    entry = relative.as_posix().rstrip("/") + "/" + ("" if ignore_all else ".index/")
    gitignore = git_root / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    except OSError:
        return False
    normalized_entry = entry.rstrip("/")
    for line in existing.splitlines():
        normalized = line.strip().replace("\\", "/")
        if normalized in {normalized_entry, "/" + normalized_entry, entry, "/" + entry}:
            return True
        if ignore_all and normalized.startswith(normalized_entry + "/"):
            return True
        if not ignore_all and normalized in {relative.as_posix().rstrip("/"), relative.as_posix().rstrip("/") + "/"}:
            return True  # an older whole-directory rule already hides the index

    prefix = existing
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += "\n"
    try:
        gitignore.write_text(prefix + entry + "\n", encoding="utf-8", newline="\n")
    except OSError:
        return False
    return True


def clean_body(value: str) -> str:
    return value.strip().replace("\r\n", "\n").replace("\r", "\n")


def read_body(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")
    if args.body is not None:
        return args.body
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def next_id(existing: Iterable[str], prefix: str, date_value: str) -> str:
    date_compact = date_value.replace("-", "")
    pattern = re.compile(rf"^{re.escape(prefix)}-{date_compact}-(\d+)$")
    numbers = [int(match.group(1)) for value in existing if (match := pattern.match(value))]
    return f"{prefix}-{date_compact}-{max(numbers, default=0) + 1:03d}"


def all_log_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    paths = (path for path in root.glob("**/*.md") if DAILY_FILE_RE.fullmatch(path.name))
    return sorted(paths, key=lambda item: (item.stat().st_mtime, str(item)), reverse=True)


def find_work(root: Path, work_id: str) -> tuple[Path, int, int, str, dict[str, Any], str] | None:
    """Return path, marker start, section end, marker, metadata, body."""

    for path in all_log_paths(root):
        meta, body = read_log(path)
        marker = f"<!-- work-id: {work_id} -->"
        start = body.find(marker)
        if start < 0:
            continue
        next_marker = ID_RE.search(body, start + len(marker))
        end = next_marker.start() if next_marker else len(body)
        return path, start, end, marker, meta, body
    return None


def ensure_record_heading(body: str) -> str:
    if re.search(r"(?m)^## 记录\s*$", body):
        return body
    suffix = "\n" if body.endswith("\n") else "\n\n"
    return body + suffix + "## 记录\n\n"


def append_section(body: str, section: str) -> str:
    body = ensure_record_heading(body)
    if not body.endswith("\n"):
        body += "\n"
    if not body.endswith("\n\n"):
        body += "\n"
    return body + section.rstrip() + "\n\n"


def update_meta(meta: dict[str, Any], body: str, summary: str, stamp: str) -> None:
    meta["summary"] = summary.strip()
    meta["updated_at"] = stamp
    meta["entry_count"] = len(list(ID_RE.finditer(body)))
    meta["work_ids"] = [match.group(2) for match in ID_RE.finditer(body) if match.group(1) == "work"]


def status_label(status: str) -> str:
    return {
        "in_progress": "进行中",
        "completed": "已完成",
        "blocked": "受阻",
        "cancelled": "已取消",
    }.get(status, status)


def cmd_append(args: argparse.Namespace) -> int:
    stamp_dt = local_now()
    stamp = iso_timestamp(stamp_dt)
    date_value = local_date(stamp_dt)
    root = args_root(args)
    path = daily_path(root, date_value)
    meta, body = read_log(path, date_value)
    existing_ids = [match.group(2) for match in ID_RE.finditer(body)]
    prefix = "D" if args.kind == "discussion" else "W"
    record_id = args.record_id or next_id(existing_ids, prefix, date_value)
    if record_id in existing_ids:
        raise SystemExit(f"ID 已存在于当天文件：{record_id}")

    text = clean_body(read_body(args))
    if args.kind == "discussion":
        section = (
            f"<!-- discussion-id: {record_id} -->\n"
            f"### {stamp_dt:%H:%M} — 讨论 | {args.title}\n"
            f"{text}\n"
            f"- 记录时间：{stamp}\n"
        )
    else:
        section = (
            f"<!-- work-id: {record_id} -->\n"
            f"### {stamp_dt:%H:%M} — 工作 | {args.title}\n"
            f"- 状态：{status_label(args.status)}\n"
            f"{text}\n"
            f"- 更新时间：{stamp}\n"
        )
    body = append_section(body, section)
    update_meta(meta, body, args.summary, stamp)
    ensure_gitignore(root, track=args.track)
    write_log(path, meta, body)
    print(record_id)
    print(path)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    root = args_root(args)
    found = find_work(root, args.work_id)
    if not found:
        raise SystemExit(f"未找到 work_id：{args.work_id}")
    path, start, end, marker, meta, body = found
    stamp_dt = local_now()
    stamp = iso_timestamp(stamp_dt)
    text = clean_body(read_body(args))
    section = body[start:end]
    status_text = f"- 状态：{status_label(args.status)}"
    if WORK_STATUS_RE.search(section):
        section = WORK_STATUS_RE.sub(status_text, section, count=1)
    update_title = args.title or "继续工作"
    update = (
        f"\n#### 更新 {stamp_dt:%H:%M} — {update_title}\n"
        f"{text}\n"
        f"- 状态：{status_label(args.status)}\n"
        f"- 更新时间：{stamp}\n"
    )
    section = section.rstrip() + "\n" + update
    body = body[:start] + section + body[end:]
    update_meta(meta, body, args.summary, stamp)
    ensure_gitignore(root, track=args.track)
    write_log(path, meta, body)
    print(args.work_id)
    print(path)
    return 0


@dataclass
class RecordSection:
    text: str
    line: int


@dataclass
class Record:
    record_id: str
    kind: str
    title: str
    date: str
    status: str
    updated_at: str | None
    path: Path
    line: int
    text: str
    sections: list[RecordSection]

    def info(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "kind": self.kind,
            "title": self.title,
            "date": self.date,
            "status": self.status,
            "updated_at": self.updated_at,
            "path": str(self.path),
            "line": self.line,
        }

    def latest_time(self) -> float:
        try:
            return datetime.fromisoformat(self.updated_at or self.date).timestamp()
        except ValueError:
            return 0


def structural_matches(pattern: re.Pattern[str], text: str) -> list[re.Match[str]]:
    """Read log markers/headings, excluding quoted examples in fenced code."""

    matches = []
    fence: tuple[str, int] | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        token = re.match(r"^[ \t]*(\x60{3,}|~{3,})", line)
        if token:
            marker = token.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
        elif fence is None:
            match = pattern.match(text, offset)
            if match:
                matches.append(match)
        offset += len(line)
    return matches


def read_records(root: Path) -> tuple[list[Record], list[str]]:
    records = []
    warnings = []
    for path in all_log_paths(root):
        try:
            content = path.read_text(encoding="utf-8")
            meta, body = parse_log(content, path)
            if meta["schema"] != "agent-work-log/v1":
                continue
            offset = len(content) - len(body)
            markers = structural_matches(RECORD_MARKER_RE, body)
            for index, marker in enumerate(markers):
                end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
                text = body[marker.start():end].rstrip()
                line = content.count("\n", 0, offset + marker.start()) + 1
                heading = re.search(r"(?m)^###[ \t]+([^\r\n]+)$", text)
                heading_text = heading.group(1) if heading else marker.group(2)
                title = heading_text.split("|", 1)[-1].strip()
                statuses = [match.group(0) for match in structural_matches(WORK_STATUS_RE, text)]
                status = statuses[-1].split("：", 1)[1].strip() if statuses else (
                    "讨论" if marker.group(1) == "discussion" else "未标明"
                )
                timestamps = [match.group(1) for match in structural_matches(TIMESTAMP_RE, text)]
                starts = [0] + [update.start() for update in structural_matches(UPDATE_RE, text)]
                sections = [
                    RecordSection(
                        text[start:starts[n + 1] if n + 1 < len(starts) else len(text)].rstrip(),
                        line + text.count("\n", 0, start),
                    )
                    for n, start in enumerate(starts)
                ]
                records.append(Record(
                    marker.group(2), marker.group(1), title, str(meta["date"]), status,
                    timestamps[-1].strip() if timestamps else None, path, line, text, sections,
                ))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            warnings.append(f"无法读取工作记录 {path}：{exc}")
    return records, warnings


def query_text(args: argparse.Namespace) -> str:
    if args.query is not None and args.terms:
        raise ValueError("关键词使用位置参数或 --query，二者任选一种")
    query = args.query if args.query is not None else " ".join(args.terms)
    if not query.strip():
        raise ValueError("请提供任务名、关键词或记录编号")
    return query.strip()


def contains_term(folded: str, term: str) -> bool:
    if term.isdecimal():
        # A time budget such as 900 must not match a score like 33,900.5.
        return bool(re.search(rf"(?<!\d)(?<!\d[.,]){re.escape(term)}(?!\d|[.,]\d)", folded))
    return term in folded


def matches_query(text: str, terms: list[str], mode: str) -> bool:
    folded = text.casefold()
    if mode == "phrase":
        return terms[0] in folded
    hits = [contains_term(folded, term) for term in terms]
    return all(hits) if mode == "all" else any(hits)


def search_view(record: Record, terms: list[str], mode: str) -> dict[str, Any]:
    """Include matching original paragraphs and every subsequent update.

    Historical decisions are not labelled correct/incorrect by this script.
    Returning later updates lets readers see explicit corrections themselves.
    """

    matching = [
        n for n, section in enumerate(record.sections)
        if matches_query(section.text, terms, "any" if mode != "phrase" else mode)
    ]
    complete = [
        n for n, section in enumerate(record.sections)
        if matches_query(section.text, terms, mode)
    ]
    # Prefer a section about the complete query over an earlier, incidental
    # occurrence of just one term in a long-running task.
    cross_boundary = not matching
    if cross_boundary:
        folded = record.text.casefold()
        hit_line = record.line + folded.count("\n", 0, folded.index(terms[0]))
        first = max(n for n, section in enumerate(record.sections) if section.line <= hit_line)
    else:
        first = complete[0] if complete else matching[0]
    snippets = []
    if first == 0:
        section = record.sections[0]
        start = 0
        for paragraph in re.split(r"\n[ \t]*\n", section.text):
            position = section.text.find(paragraph, start)
            start = position + len(paragraph)
            if cross_boundary or matches_query(paragraph, terms, "any" if mode != "phrase" else mode):
                snippets.append({
                    "line": section.line + section.text.count("\n", 0, position),
                    "text": paragraph,
                })
    updates = [
        {"line": section.line, "text": section.text}
        for section in record.sections[max(1, first):]
    ]
    return {**record.info(), "matches": snippets, "updates": updates}


def print_record_header(result: dict[str, Any]) -> None:
    print(f"{result['record_id']} | {result['title']}")
    stamp = result["updated_at"] or "未标明"
    print(f"日期：{result['date']}  当前状态：{result['status']}  最近记录时间：{stamp}")
    print(f"来源：{result['path']}:{result['line']}")


def print_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"agent-work-log: {warning}", file=sys.stderr)


def search_rank(record: Record, terms: list[str], query: str, mode: str) -> tuple:
    term_counts = [
        sum(contains_term(section.text.casefold(), term) for term in terms) for section in record.sections
    ]
    complete_lengths = [
        len("\n".join(
            line for line in section.text.splitlines()
            if not line.startswith(("<!--", "###", "- 状态：", "- 更新时间：", "- 记录时间："))
        )) for section in record.sections
        if matches_query(section.text, terms, mode)
    ]
    return (
        record.record_id.casefold() == query.casefold(),
        sum(contains_term(record.title.casefold(), term) for term in terms),
        max(term_counts), -min(complete_lengths) if complete_lengths else -len(record.text),
        record.latest_time(), record.record_id,
    )


def cmd_search(args: argparse.Namespace) -> int:
    root = args_root(args)
    query = query_text(args)
    terms = [query.casefold()] if args.match == "phrase" else list(dict.fromkeys(query.casefold().split()))
    records, warnings = read_records(root)
    selected = [
        record for record in records
        if matches_query(record.text, terms, args.match)
        and (not args.unfinished or record.status in {"进行中", "受阻"})
    ]
    selected.sort(key=lambda record: search_rank(record, terms, query, args.match), reverse=True)
    results = [search_view(record, terms, args.match) for record in selected]
    if args.json:
        print(json.dumps({
            "log_dir": str(root), "query": query, "match": args.match,
            "results": results, "warnings": warnings,
        }, ensure_ascii=False, indent=2))
    elif results:
        print(f"日志目录：{root}  匹配条目：{len(results)}")
        for result in results:
            print()
            print_record_header(result)
            if result["matches"]:
                print("命中内容：")
                for snippet in result["matches"]:
                    print(f"[{result['path']}:{snippet['line']}]\n{snippet['text']}")
            if result["updates"]:
                print("相关后续更新（请结合更正与最新结果阅读）：")
                for update in result["updates"]:
                    print(f"[{result['path']}:{update['line']}]\n{update['text']}")
    else:
        detail = "目录尚不存在" if not root.exists() else "未找到匹配条目"
        print(f"{detail}：{root}；查询：{query}")
    print_warnings(warnings)
    return 0 if results else (2 if warnings else 1)


def cmd_show(args: argparse.Namespace) -> int:
    root = args_root(args)
    graph_result = graph_memory.show(args, root, graph_helpers())
    if graph_result is not None:
        return graph_result
    records, warnings = read_records(root)
    selected = [record for record in records if record.record_id.casefold() == args.record_id.casefold()]
    if len(selected) > 1:
        locations = ", ".join(f"{record.path}:{record.line}" for record in selected)
        raise ValueError(f"记录编号重复：{args.record_id}，请核对来源：{locations}")
    record = selected[0] if selected else None
    if args.json:
        result = {**record.info(), "content": record.text} if record else None
        print(json.dumps({
            "log_dir": str(root), "record": result, "warnings": warnings,
        }, ensure_ascii=False, indent=2))
    elif record:
        print_record_header(record.info())
        print(f"\n{record.text}")
    else:
        print(f"未找到记录编号：{args.record_id}；日志目录：{root}")
    print_warnings(warnings)
    return 0 if record else (2 if warnings else 1)


def add_location(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--project-root", help="项目目录；使用其 worklog/，在 Git 内会定位仓库根目录")
    group.add_argument("--log-dir", help="实际日志目录；相对路径按项目根目录解析")
    group.add_argument(
        "--root", help="兼容旧命令；项目目录自动使用其 worklog/，自定义日志目录建议用 --log-dir"
    )


def add_common(parser: argparse.ArgumentParser, *, include_status: bool = False) -> None:
    add_location(parser)
    parser.add_argument("--summary", required=True, help="写入后整份日期文件的 YAML 摘要")
    parser.add_argument("--body", help="正文；省略时可从 stdin 读取")
    parser.add_argument("--body-file", help="从 UTF-8 文件读取正文")
    parser.add_argument("--track", action="store_true", default=True, help="默认行为：日志纳入 Git，只忽略 .index/；整目录忽略需设置 AGENT_WORK_LOG_IGNORE=1")
    if include_status:
        parser.add_argument("--status", choices=("in_progress", "completed", "blocked", "cancelled"), default="in_progress")


def graph_helpers() -> SimpleNamespace:
    return SimpleNamespace(
        args_root=args_root, add_location=add_location, read_records=read_records,
        all_log_paths=all_log_paths, structural_matches=structural_matches,
        ensure_gitignore=ensure_gitignore, local_now=local_now,
        iso_timestamp=iso_timestamp, local_date=local_date, next_id=next_id,
        FRONTMATTER_RE=FRONTMATTER_RE,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and update date-grouped agent work logs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    append = subparsers.add_parser("append", help="append a discussion or work entry to today's file")
    append.add_argument("--kind", choices=("discussion", "work"), required=True)
    append.add_argument("--title", required=True)
    append.add_argument("--record-id", help="optional explicit D- or W- ID")
    add_common(append, include_status=True)
    append.set_defaults(func=cmd_append)

    update = subparsers.add_parser("update", help="append an update to an existing work entry")
    update.add_argument("--work-id", required=True)
    update.add_argument("--title", help="update title")
    add_common(update, include_status=True)
    update.set_defaults(func=cmd_update)

    search = subparsers.add_parser("search", aliases=["find"], help="按关键词查相关条目及其后续更新")
    search.add_argument("terms", nargs="*", help="任务名、关键词或记录编号；默认所有词须出现在同一条目")
    search.add_argument("--query", help="兼容旧 find 用法，等价于位置参数")
    search.add_argument("--match", choices=("all", "any", "phrase"), default="all",
                        help="all：全部词；any：任一词；phrase：整段原文")
    search.add_argument("--unfinished", action="store_true", help="只查当前状态为进行中或受阻的工作")
    search.add_argument("--json", action="store_true", help="输出条目信息、命中内容及更新的 JSON")
    add_location(search)
    search.set_defaults(func=cmd_search)

    show = subparsers.add_parser("show", help="按编号读取完整原记录和全部后续更新")
    show.add_argument("record_id", help="W-、D-、L- 编号或 .uN 更新点")
    show.add_argument("--include-archived", action="store_true", help="允许读取归档原文")
    show.add_argument("--json", action="store_true")
    add_location(show)
    show.set_defaults(func=cmd_show)
    graph_memory.register(subparsers, graph_helpers())
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"agent-work-log: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
