"""Markdown-backed graph memory. The SQLite file is a disposable read model.

record.py injects its existing helpers through register(); this module never
imports the CLI entry point, including when that entry point is __main__.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

import yaml

import embed_backend as embedding

RELEVANCE_THRESHOLD = 0.5
SIMILARITY_THRESHOLD = 0.6
INDEX_VERSION = "1"
LINE_FIELDS = ("schema", "id", "title", "status", "situation", "method", "why",
               "path", "outcome", "relates", "created_at", "updated_at")
LINE_ID = re.compile(r"L-\d{8}-\d{3,}\Z")
ROLES = ("problem", "attempt", "decision", "evidence", "result")
TOKEN_RE = re.compile(
    r"[A-Za-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0003134f"
    r"\u3040-\u30ff\uac00-\ud7af]+"
)
HEADING_RE = re.compile(r"(?m)^#{3,4}[ \t]+([^\r\n]+)$")
CONCLUSION_RE = re.compile(r"(?m)^-[ \t]*(?:结果|本次完成|本次变更)[：:][ \t]*([^\r\n]*)$")
# Bookkeeping fields say nothing about what a node concluded, so the fallback skips them.
METADATA_RE = re.compile(
    r"-[ \t]*(?:状态|更新时间|记录时间|创建时间|目标|背景|目标/背景|讨论背景|验证|证据|验证/证据"
    r"|未完成|下一步|未完成/下一步|用户后续要求)[ \t]*[：:][ \t]*(.*)")


def tokens(text):
    """ASCII words and adjacent CJK characters, with punctuation as boundaries."""
    result = set()
    for match in TOKEN_RE.finditer(str(text)):
        part = match.group()
        if part.isascii():
            result.add(part.lower())
        elif len(part) == 1:
            result.add(part)
        else:
            result.update(part[n:n + 2] for n in range(len(part) - 1))
    return result


def timestamp(value):
    return datetime.fromisoformat(str(value)).astimezone().timestamp()


def now(args, helpers):
    if not args.now:
        return helpers.local_now()
    value = datetime.fromisoformat(args.now)
    return value if value.tzinfo else value.astimezone()


def read_line(path, helpers):
    with path.open(encoding="utf-8", newline="") as stream:
        source = stream.read()
    match = helpers.FRONTMATTER_RE.match(source)
    if not match:
        raise ValueError(f"线文件缺少 YAML：{path}")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict) or meta.get("id") != path.stem:
        raise ValueError(f"线编号与文件不一致：{path}")
    # Retain everything following the closing delimiter, including blank lines.
    end = match.end()
    if source[:end].endswith("\r\n"):
        end -= 2
    elif source[:end].endswith("\n"):
        end -= 1
    return meta, source[end:], source


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".graph-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_line(path, meta, body):
    ordered = {field: meta.get(field) for field in LINE_FIELDS}
    ordered.update({key: value for key, value in meta.items() if key not in ordered})
    atomic_text(path, "---\n" + yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False) + "---" + body)


class Graph:
    def __init__(self, root, helpers):
        self.root = root
        self.helpers = helpers
        self.index = root / ".index" / "graph.sqlite"

    def sources(self):
        paths = self.helpers.all_log_paths(self.root)
        paths += list((self.root / "lines").glob("L-*.md"))
        registry = self.root / "lines" / ".archived_nodes"
        if registry.exists():
            paths.append(registry)
        return sorted(paths, key=lambda path: path.relative_to(self.root).as_posix())

    def fingerprint(self):
        entries = []
        for path in self.sources():
            stat = path.stat()
            entries.append((path.relative_to(self.root).as_posix(), stat.st_mtime_ns, stat.st_size))
        return hashlib.sha256(json.dumps(entries, ensure_ascii=False).encode()).hexdigest()

    def archived_nodes(self):
        registry = self.root / "lines" / ".archived_nodes"
        return set(registry.read_text(encoding="utf-8").splitlines()) if registry.exists() else set()

    def rebuild(self, fingerprint=None):
        fingerprint = fingerprint or self.fingerprint()
        self.index.parent.mkdir(parents=True, exist_ok=True)
        self.helpers.ensure_gitignore(self.root)
        descriptor, name = tempfile.mkstemp(prefix="graph-", suffix=".sqlite", dir=self.index.parent)
        os.close(descriptor)
        try:
            with closing(sqlite3.connect(name)) as db:
                db.executescript("""
                    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE nodes (id TEXT PRIMARY KEY, title TEXT, conclusion TEXT,
                        content TEXT, source TEXT, source_line INTEGER, archived INTEGER NOT NULL);
                    CREATE TABLE lines (id TEXT PRIMARY KEY, status TEXT, updated_at TEXT,
                        archived INTEGER NOT NULL, metadata TEXT, source TEXT, content TEXT);
                    CREATE TABLE line_steps (line TEXT, seq INTEGER, node TEXT, role TEXT,
                        PRIMARY KEY (line, seq));
                    CREATE TABLE line_links (line TEXT, target TEXT, rel TEXT,
                        PRIMARY KEY (line, target, rel));
                    CREATE INDEX steps_node ON line_steps(node);
                    CREATE INDEX links_target ON line_links(target, rel);
                    CREATE VIEW visible_nodes AS SELECT * FROM nodes WHERE archived = 0;
                    CREATE VIEW visible_lines AS SELECT * FROM lines WHERE archived = 0;
                    CREATE VIEW visible_links AS SELECT link.* FROM line_links link
                        JOIN visible_lines a ON a.id = link.line
                        JOIN visible_lines b ON b.id = link.target;
                """)
                archived = self.archived_nodes()
                records, warnings = self.helpers.read_records(self.root)
                if warnings:
                    raise ValueError("；".join(warnings))
                node_ids = set()
                for record in records:
                    for number, section in enumerate(record.sections):
                        nid = record.record_id if number == 0 else f"{record.record_id}.u{number}"
                        if nid in node_ids:
                            raise ValueError(f"记录编号重复：{nid}，请核对来源")
                        node_ids.add(nid)
                        headings = self.helpers.structural_matches(HEADING_RE, section.text)
                        heading = headings[0] if headings else None
                        title = heading.group(1) if heading else nid
                        title = re.sub(r"\b\d{2}:\d{2}\b", "", title).strip(" —–-\t")
                        if number == 0:
                            title = title.split("|", 1)[-1].strip()
                        else:
                            title = re.sub(r"^更新\s*[—–-]?\s*", "", title)
                        body = section.text[heading.end():] if heading else section.text
                        conclusion = self.conclusion(body)
                        db.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?)", (
                            nid, title, conclusion[:80], section.text, str(record.path.relative_to(self.root)),
                            section.line, int(nid in archived),
                        ))
                for path in sorted((self.root / "lines").glob("L-*.md")):
                    meta, _, source = read_line(path, self.helpers)
                    lid = meta["id"]
                    db.execute("INSERT INTO lines VALUES (?,?,?,?,?,?,?)", (
                        lid, meta.get("status"), str(meta.get("updated_at", "")),
                        int(meta.get("status") == "archived"), json.dumps(meta, ensure_ascii=False, default=str),
                        str(path.relative_to(self.root)), source,
                    ))
                    for seq, step in enumerate(meta.get("path") or [], 1):
                        db.execute("INSERT INTO line_steps VALUES (?,?,?,?)", (lid, seq, step["node"], step.get("role", "")))
                    for link in meta.get("relates") or []:
                        db.execute("INSERT OR IGNORE INTO line_links VALUES (?,?,?)", (lid, link["line"], link["rel"]))
                db.executemany("INSERT INTO meta VALUES (?,?)", [("fingerprint", fingerprint), ("version", INDEX_VERSION)])
                db.commit()
            os.replace(name, self.index)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def conclusion(self, body):
        found = self.helpers.structural_matches(CONCLUSION_RE, body)
        if found:
            return found[0].group(1).strip()
        goal = ""
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("<!--"):
                continue
            meta = METADATA_RE.fullmatch(line)
            if meta is None:
                return line
            if not goal and line.lstrip("- \t").startswith("目标"):
                goal = meta.group(1).strip()
        return goal

    def connect(self):
        fingerprint = self.fingerprint()
        valid = False
        if self.index.exists():
            try:
                with closing(sqlite3.connect(self.index)) as db:
                    meta = dict(db.execute("SELECT key, value FROM meta"))
                    valid = meta.get("fingerprint") == fingerprint and meta.get("version") == INDEX_VERSION
            except sqlite3.DatabaseError:
                pass
        if not valid:
            self.rebuild(fingerprint)
        db = sqlite3.connect(self.index)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def row(db, kind, identifier, include_archived=False):
        table = kind if include_archived else "visible_" + kind
        return db.execute(f"SELECT * FROM {table} WHERE id = ? COLLATE NOCASE", (identifier,)).fetchone()

    def require(self, db, kind, identifier, include_archived=False):
        row = self.row(db, kind, identifier, include_archived)
        if row is None:
            raise ValueError(f"未找到{'线' if kind == 'lines' else '点'}：{identifier}")
        return row

    def l0(self, db, row, via=None):
        meta = json.loads(row["metadata"])
        return {**{key: meta.get(key, "") for key in ("id", "title", "status", "situation", "method", "outcome")},
                "branched_from": [link[0] for link in db.execute(
                    "SELECT target FROM visible_links WHERE line=? AND rel='branches_from' ORDER BY target", (row["id"],))],
                "via": via}

    def latest(self, db, row):
        seen = set()
        while row["status"] == "superseded":
            if row["id"] in seen:
                raise ValueError("取代关系存在环，请检查线文件")
            seen.add(row["id"])
            choices = list(db.execute("""SELECT l.* FROM visible_links link JOIN visible_lines l ON l.id=link.line
                WHERE link.target=? AND link.rel='supersedes'""", (row["id"],)))
            if not choices:
                return None
            row = sorted(choices, key=lambda item: (-timestamp(item["updated_at"]), item["id"]))[0]
        return row

    def fields(self, db, row):
        meta = json.loads(row["metadata"])
        content = [str(meta.get(key, "")) for key in ("title", "situation", "method", "why", "outcome")]
        content += [item[0] for item in db.execute("""SELECT n.title FROM line_steps s
            JOIN visible_nodes n ON n.id=s.node WHERE s.line=? ORDER BY s.seq""", (row["id"],))]
        return dict(situation=str(meta.get("situation", "")), method=str(meta.get("method", "")),
                    content=" ".join(content))

    def semantic_vectors(self, db, documents, query, dedup=False):
        backend = embedding.get_backend()
        if backend is None:
            return None, None, None
        cache = embedding.VectorCache(self.index.parent / "embeddings.sqlite", backend)
        try:
            # Cache all three views, including superseded lines, never archived lines
            # or node bodies. A source edit invalidates only the changed text hashes.
            texts = [text for fields in documents.values() for text in fields.values()]
            cached = dict(zip(texts, cache.vectors("passage", texts)))
            if dedup:
                passages = [fields["situation"] + " " + fields["method"] for fields in documents.values()]
                vectors = dict(zip(documents, cache.vectors("passage", passages)))
                qvector = cache.vectors("passage", [query])[0]
            else:
                vectors = {lid: {field: cached[text] for field, text in fields.items()}
                           for lid, fields in documents.items()}
                qvector = cache.vectors("query", [query])[0]
            compared = list(vectors.values()) if dedup else [v for fields in vectors.values() for v in fields.values()]
            embedding.validate([qvector, *compared], 1 + len(compared))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('embedding_model_id', ?)", (backend.model_id,))
            db.commit()
            return backend, vectors, qvector
        except (OSError, ValueError, KeyError, sqlite3.DatabaseError) as exc:
            embedding.fallback(os.environ.get("AGENT_WORK_LOG_EMBED", "auto"), exc)
            return None, None, None

    def recall(self, db, args):
        query = tokens(args.query)
        rows = list(db.execute("SELECT * FROM visible_lines"))
        documents = {row["id"]: self.fields(db, row) for row in rows}
        backend, vectors, qvector = self.semantic_vectors(db, documents, args.query)
        hits = []
        for row in rows:
            document = tokens(documents[row["id"]][args.by])
            lex = len(query & document) / len(query) if query else 0
            if backend:
                cos = embedding.cosine(qvector, vectors[row["id"]][args.by])
                score = 0.5 * lex + 0.5 * max(0., min(1., (cos - backend.floor) / (1 - backend.floor)))
                hit = lex >= embedding.LEX_THRESHOLD or cos >= backend.threshold
            else:
                score = lex
                hit = score > 0 and score >= RELEVANCE_THRESHOLD
            if hit:
                hits.append((score, row))
        hits.sort(key=lambda item: (-item[0], -timestamp(item[1]["updated_at"]), item[1]["id"]))
        redirected = {}
        for score, original in hits:
            final = self.latest(db, original)
            if final is not None and final["id"] not in redirected:
                via = original["id"] if original["id"] != final["id"] else None
                redirected[final["id"]] = (score, final, via)
        selected = sorted(redirected.values(), key=lambda item: (
            -item[0], -timestamp(item[1]["updated_at"]), item[1]["id"]))[:args.limit]
        counts = Counter()
        for _, row, _ in selected:
            counts.update({item[0] for item in db.execute("""SELECT n.id FROM line_steps s
                JOIN visible_nodes n ON n.id=s.node WHERE s.line=?""", (row["id"],))})
        return dict(query=args.query, by=args.by, lines=[self.l0(db, row, via) for _, row, via in selected],
                    hot_nodes=[dict(node=nid, count=count) for nid, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])) if count >= 2],
                    message=None if selected else "无相关历史")

    def expand(self, db, lid):
        row = self.require(db, "lines", lid, include_archived=True)
        if row["archived"]:
            return None
        line = self.l0(db, row)
        line["why"] = json.loads(row["metadata"]).get("why", "")
        steps = []
        for step in db.execute("SELECT * FROM line_steps WHERE line=? ORDER BY seq", (row["id"],)):
            node = self.row(db, "nodes", step["node"])
            if node is None:
                if self.row(db, "nodes", step["node"], True):
                    steps.append(dict(node=step["node"], archived=True))
                    continue
                raise ValueError(f"线引用的点不存在：{step['node']}")
            others = [item[0] for item in db.execute("""SELECT DISTINCT l.id FROM line_steps s
                JOIN visible_lines l ON l.id=s.line WHERE s.node=? AND l.id<>? ORDER BY l.id""", (node["id"], row["id"]))]
            steps.append(dict(seq=step["seq"], node=node["id"], role=step["role"], title=node["title"],
                              conclusion=node["conclusion"], also_in=others))
        return dict(line=line, steps=steps)


LINT_LABELS = dict(missing_why="缺少理由", missing_node="引用的点不存在", stale_open="长期未更新的开放思路",
                   empty_path="路径为空", missing_outcome="已关闭但缺少结果")


def recall_text(value):
    out = [value["message"]] if value["message"] else []
    for line in value["lines"]:
        out.append(f"{line['id']} | {line['title']} | {line['status']}")
        for key, label in (("situation", "问题"), ("method", "走法"), ("outcome", "结果"),
                           ("branched_from", "分支来源"), ("via", "经由")):
            data = line[key]
            if key in ("branched_from", "via") and not data:
                continue
            out.append(f"  {label}：{', '.join(data) if isinstance(data, list) else data or ''}")
    if value["hot_nodes"]:
        out.append("共同经过的点：")
        out += [f"  {node['node']}：{node['count']}" for node in value["hot_nodes"]]
    return out


def expand_text(value):
    line = value["line"]
    out = [f"{line['id']} | {line['title']} | {line['status']}"]
    for key, label in (("situation", "问题"), ("method", "走法"), ("why", "理由"), ("outcome", "结果"),
                       ("branched_from", "分支来源")):
        data = line[key]
        if data:
            out.append(f"  {label}：{', '.join(data) if isinstance(data, list) else data}")
    out.append("步骤：")
    for step in value["steps"]:
        if step.get("archived"):
            out.append(f"  - {step['node']}（已归档）")
            continue
        out.append(f"  {step['seq']}. [{step['role']}] {step['node']} {step['title']}")
        if step["conclusion"]:
            out.append(f"     结论：{step['conclusion']}")
        if step["also_in"]:
            out.append(f"     也在：{', '.join(step['also_in'])}")
    return out


def emit(value, as_json, text):
    """Print JSON with --json, otherwise the given text lines (or a callable producing them)."""
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    lines = text(value) if callable(text) else text
    print("\n".join([lines] if isinstance(lines, str) else lines))


def archived_error():
    print("该编号已归档；show 可加 --include-archived 读取原文", file=sys.stderr)
    return 4


def show(args, root, helpers):
    """Return None for ordinary records so their established output is preserved."""
    ordinary = not args.record_id.upper().startswith("L-") and ".u" not in args.record_id.lower()
    # A daily-only log has no graph archive state to consult. Keep its existing
    # read-only show behavior, including duplicate-ID and damaged-log reporting.
    if ordinary and not (root / "lines").exists():
        return None
    graph = Graph(root, helpers)
    with closing(graph.connect()) as db:
        kind = "lines" if args.record_id.upper().startswith("L-") else "nodes"
        row = graph.row(db, kind, args.record_id, True)
        if row is not None and row["archived"] and not args.include_archived:
            return archived_error()
        if ordinary:
            return None
        if row is None:
            print(f"未找到记录编号：{args.record_id}；日志目录：{root}")
            return 1
        if args.json:
            print(json.dumps(dict(log_dir=str(root), record=dict(record_id=row["id"], content=row["content"]), warnings=[]), ensure_ascii=False, indent=2))
        else:
            print(row["content"])
    return 0


def run(args, helpers):
    graph = Graph(helpers.args_root(args), helpers)
    if args.command == "reindex":
        graph.rebuild()
        emit(dict(message="索引已重建"), args.json, "索引已重建")
        return 0
    with closing(graph.connect()) as db:
        if args.command == "recall":
            if args.limit < 1:
                raise ValueError("--limit 必须为正整数")
            if args.expand:
                view = graph.expand(db, args.expand)
                if view is None:
                    return archived_error()
            else:
                if not args.query or not args.query.strip():
                    raise ValueError("请提供查询内容或 --expand 编号")
                view = graph.recall(db, args)
            emit(view, args.json, expand_text if args.expand else recall_text)
            return 0
        if args.command == "lint":
            cutoff = (now(args, helpers) - timedelta(days=args.stale_days)).timestamp()
            issues = []
            for row in db.execute("SELECT * FROM visible_lines ORDER BY id"):
                meta = json.loads(row["metadata"])
                codes = []
                if not str(meta.get("why") or "").strip():
                    codes.append("missing_why")
                if not meta.get("path"):
                    codes.append("empty_path")
                if any(graph.row(db, "nodes", step["node"], True) is None for step in meta.get("path") or []):
                    codes.append("missing_node")
                if row["status"] == "open" and timestamp(row["updated_at"]) < cutoff:
                    codes.append("stale_open")
                if row["status"] in ("worked", "abandoned") and not str(meta.get("outcome") or "").strip():
                    codes.append("missing_outcome")
                issues.extend(dict(line=row["id"], code=code) for code in codes)
            emit(dict(issues=issues), args.json, [f"发现 {len(issues)} 个问题："] + [
                f"  {item['line']}：{LINT_LABELS[item['code']]}（{item['code']}）" for item in issues]
                if issues else "未发现问题")
            return int(bool(issues))
        stamp_dt = now(args, helpers)
        stamp = helpers.iso_timestamp(stamp_dt)
        if args.command == "archive" and not args.identifier.upper().startswith("L-"):
            node = graph.require(db, "nodes", args.identifier, True)
            archived = graph.archived_nodes()
            archived.add(node["id"])
            helpers.ensure_gitignore(graph.root)
            atomic_text(graph.root / "lines" / ".archived_nodes", "\n".join(sorted(archived)) + "\n")
            emit(dict(id=node["id"]), args.json, f"已归档点：{node['id']}")
            return 0
        if args.command == "line" and args.action == "open":
            if not args.why.strip():
                raise ValueError("why 不能为空白，请说明理由")
            graph.require(db, "nodes", args.node)
            if args.branches_from:
                graph.require(db, "lines", args.branches_from)
            candidates = []
            new_text = args.situation + " " + args.method
            query = tokens(new_text)
            if not args.force_new:
                rows = list(db.execute("SELECT * FROM visible_lines WHERE status<>'superseded'"))
                documents = {row["id"]: graph.fields(db, row) for row in rows}
                backend, vectors, qvector = graph.semantic_vectors(db, documents, new_text, dedup=True)
                for row in rows:
                    fields = documents[row["id"]]
                    document = tokens(fields["situation"] + " " + fields["method"])
                    score = len(query & document) / len(query | document) if query | document else 0
                    similar = score > SIMILARITY_THRESHOLD
                    if backend:
                        cos = embedding.cosine(qvector, vectors[row["id"]])
                        similar = score >= embedding.JACCARD_THRESHOLD or cos >= backend.dedup_threshold
                        score = max(score, cos)
                    if similar:
                        meta = json.loads(row["metadata"])
                        candidates.append(dict(id=row["id"], title=meta.get("title", ""), score=score))
            if candidates:
                candidates.sort(key=lambda row: (-row["score"], row["id"]))
                emit(dict(candidates=candidates), args.json, ["已有相似思路："] + [
                    f"  {item['id']} | {item['title']} | 相似度 {item['score']:.2f}" for item in candidates])
                print("已有相似思路，请复用或使用 --force-new", file=sys.stderr)
                return 3
            lid = helpers.next_id([path.stem for path in (graph.root / "lines").glob("L-*.md")], "L", helpers.local_date(stamp_dt))
            meta = dict(schema="agent-work-log/line-v1", id=lid, title=args.title, status="open",
                        situation=args.situation, method=args.method, why=args.why,
                        path=[dict(node=args.node, role=args.role)], outcome="",
                        relates=[dict(line=args.branches_from, rel="branches_from")] if args.branches_from else [],
                        created_at=stamp, updated_at=stamp)
            body = "\n\n"
        else:
            lid = args.identifier
            if not LINE_ID.fullmatch(lid):
                raise ValueError(f"线编号无效：{lid}")
            graph.require(db, "lines", lid, True)
            meta, body, _ = read_line(graph.root / "lines" / f"{lid}.md", helpers)
            action = args.action if args.command == "line" else "archive"
            if action in ("extend", "close") and meta["status"] != "open":
                raise ValueError("线已关闭，不能追加或再次关闭")
            if action == "extend":
                graph.require(db, "nodes", args.node)
                if meta.get("path") and meta["path"][-1]["node"] == args.node:
                    raise ValueError("不能相邻重复同一个点")
                meta.setdefault("path", []).append(dict(node=args.node, role=args.role))
            elif action == "close":
                if not args.outcome.strip():
                    raise ValueError("outcome 不能为空白，请写明结果")
                meta.update(status=args.status, outcome=args.outcome)
            elif action == "archive":
                meta["status"] = "archived"
            elif action == "link":
                graph.require(db, "lines", args.to)
                if lid == args.to:
                    raise ValueError("线关系不能引用自己")
                if args.rel == "supersedes":
                    pending, seen = [args.to], set()
                    while pending:
                        current = pending.pop()
                        if current == lid:
                            raise ValueError("取代关系不能形成环")
                        if current in seen:
                            continue
                        seen.add(current)
                        pending.extend(row[0] for row in db.execute(
                            "SELECT target FROM line_links WHERE line=? AND rel='supersedes'", (current,)))
                relation = dict(line=args.to, rel=args.rel)
                if relation not in meta.setdefault("relates", []):
                    meta["relates"].append(relation)
                if args.rel == "supersedes":
                    path = graph.root / "lines" / f"{args.to}.md"
                    target, target_body, _ = read_line(path, helpers)
                    target.update(status="superseded", updated_at=stamp)
                    helpers.ensure_gitignore(graph.root)
                    write_line(path, target, target_body)
            meta["updated_at"] = stamp
        helpers.ensure_gitignore(graph.root)
        write_line(graph.root / "lines" / f"{lid}.md", meta, body)
        if args.command == "archive":
            message = f"已归档线：{lid}"
        elif args.action == "open":
            message = f"已新建思路：{lid}"
        elif args.action == "extend":
            message = f"已追加到 {lid}：{args.node}（{args.role}），共 {len(meta['path'])} 步"
        elif args.action == "close":
            message = f"已关闭 {lid}：{args.status}"
        elif args.rel == "supersedes":
            message = f"已关联：{lid} 取代 {args.to}（{args.to} 已标记为 superseded）"
        else:
            message = f"已关联：{lid} 分支自 {args.to}"
        emit(dict(id=lid), args.json, message)
        return 0


def register(subparsers, helpers):
    embedding.register(subparsers, helpers)
    def common(parser):
        helpers.add_location(parser)
        parser.add_argument("--json", action="store_true", help="输出 JSON")
        parser.add_argument("--now", help="指定 ISO8601 时间")
        parser.set_defaults(func=lambda args: run(args, helpers))

    line = subparsers.add_parser("line", help="创建、追加、关闭或关联思路")
    actions = line.add_subparsers(dest="action", required=True)
    opened = actions.add_parser("open", help="新建思路")
    for field in ("title", "situation", "method", "why"):
        opened.add_argument("--" + field, required=True)
    opened.add_argument("--from", dest="node", required=True)
    opened.add_argument("--role", choices=ROLES, default="problem")
    opened.add_argument("--branches-from")
    opened.add_argument("--force-new", action="store_true")
    common(opened)
    for action in ("extend", "close", "link"):
        parser = actions.add_parser(action)
        parser.add_argument("identifier")
        if action == "extend":
            parser.add_argument("--node", required=True)
            parser.add_argument("--role", choices=ROLES, required=True)
        elif action == "close":
            parser.add_argument("--status", choices=("worked", "abandoned"), required=True)
            parser.add_argument("--outcome", required=True)
        else:
            parser.add_argument("--rel", choices=("supersedes", "branches_from"), required=True)
            parser.add_argument("--to", required=True)
        common(parser)
    archive = subparsers.add_parser("archive", help="归档线或点")
    archive.add_argument("identifier")
    common(archive)
    common(subparsers.add_parser("reindex", help="从 Markdown 重建索引"))
    recall = subparsers.add_parser("recall", help="查找历史思路；默认只给摘要")
    recall.add_argument("query", nargs="?", help="要查找的问题或走法")
    recall.add_argument("--by", choices=("content", "situation", "method"), default="content",
                        help="content：线的字段与点标题；situation：问题；method：走法")
    recall.add_argument("--limit", type=int, default=5, help="最多返回条数（默认 5）")
    recall.add_argument("--expand", metavar="L-ID", help="展开一条线的理由和点摘要")
    common(recall)
    lint = subparsers.add_parser("lint", help="检查线记录缺漏及长期未更新的开放思路")
    lint.add_argument("--stale-days", type=int, default=14)
    common(lint)
