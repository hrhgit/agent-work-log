#!/usr/bin/env python3
"""Create and update date-grouped agent work logs.

The skill owns the decision of *when* to write and *what* to summarize. This
script provides the deterministic file, ID, frontmatter, and section mechanics.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only on minimal hosts
    raise SystemExit("PyYAML is required by agent-work-log/scripts/record.py") from exc


FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
ID_RE = re.compile(r"<!--\s*(discussion|work)-id:\s*([^\s]+)\s*-->")
WORK_STATUS_RE = re.compile(r"(?m)^- 状态：[^\r\n]*$")


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


def project_root() -> Path:
    """Use the Git root when available, otherwise the current directory."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
        )
        candidate = result.stdout.strip()
        if candidate:
            return Path(candidate).resolve()
    except (OSError, subprocess.CalledProcessError):
        pass
    return Path.cwd().resolve()


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


def resolve_root(explicit: str | None) -> Path:
    raw = explicit or os.environ.get("AGENT_WORK_LOG_DIR")
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = project_root() / path
        return path.resolve()
    return project_root() / "worklog"


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


def read_log(path: Path, date_value: str | None = None) -> tuple[dict[str, Any], str]:
    if not path.exists():
        stamp = iso_timestamp()
        date_text = date_value or local_date()
        meta = default_meta(date_text, stamp, local_timezone_name())
        return meta, f"# {date_text}\n\n## 记录\n\n"

    content = path.read_text(encoding="utf-8")
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


def write_log(path: Path, meta: dict[str, Any], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_frontmatter(meta) + body.lstrip("\n"), encoding="utf-8", newline="\n")


def ensure_gitignore(log_root: Path, *, track: bool = False) -> bool:
    """Add the log directory to the containing work-tree's .gitignore.

    Returns True when an ignore rule was added or already existed. A custom
    log root outside Git is deliberately left untouched.
    """

    if track:
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

    entry = relative.as_posix().rstrip("/") + "/"
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
        if normalized.startswith(normalized_entry + "/"):
            return True

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
    return sorted(root.glob("**/*.md"), key=lambda item: (item.stat().st_mtime, str(item)), reverse=True)


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
    root = resolve_root(args.root)
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
    root = resolve_root(args.root)
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


def cmd_find(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    query = args.query.casefold()
    found = False
    for path in all_log_paths(root):
        content = path.read_text(encoding="utf-8")
        if query not in content.casefold():
            continue
        found = True
        print(path)
        for match in ID_RE.finditer(content):
            line_start = content.rfind("\n", 0, match.start()) + 1
            line_end = content.find("\n", match.end())
            print("  " + content[line_start : line_end if line_end >= 0 else len(content)].strip())
    return 0 if found else 1


def add_common(parser: argparse.ArgumentParser, *, include_status: bool = False) -> None:
    parser.add_argument("--root", help="记录根目录；默认使用 AGENT_WORK_LOG_DIR 或项目根目录下的 worklog")
    parser.add_argument("--summary", required=True, help="写入后整份日期文件的 YAML 摘要")
    parser.add_argument("--body", help="正文；省略时可从 stdin 读取")
    parser.add_argument("--body-file", help="从 UTF-8 文件读取正文")
    parser.add_argument("--track", action="store_true", help="显式保留日志在 Git 版本控制中，不自动修改 .gitignore")
    if include_status:
        parser.add_argument("--status", choices=("in_progress", "completed", "blocked", "cancelled"), default="in_progress")


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

    find = subparsers.add_parser("find", help="find IDs and matching files")
    find.add_argument("--query", required=True)
    find.add_argument("--root")
    find.set_defaults(func=cmd_find)
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
