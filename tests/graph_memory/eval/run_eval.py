#!/usr/bin/env python3
"""Evaluate CLI recall against a temporary copy of invented work logs."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml

TESTS = Path(__file__).resolve().parents[2]
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from graph_memory._base import FIXTURE, SCRIPT, cli_env, graph_available

QUERIES = Path(__file__).with_name("queries.yaml")


def load_queries(path=QUERIES):
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def evaluate(queries, k=5, embed="none"):
    """Recall@k counts a hit when ANY expected line occurs in the first k rows.

    For kind=negative a "hit" means recall returned nothing at all.
    Each forbidden ID returned for one query counts as one violation. Both query
    kinds are reported separately; paraphrase results are not a P1 pass/fail gate.
    CLI or JSON errors raise rather than being converted into retrieval misses.
    """
    groups = {}
    results = []
    with tempfile.TemporaryDirectory(prefix="worklog-graph-eval-") as folder:
        project = Path(folder)
        logs = project / "worklog"
        shutil.copytree(FIXTURE, logs)
        for case in queries:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "recall", case["query"], "--by", case["by"],
                 "--limit", str(k), "--log-dir", str(logs), "--json"],
                cwd=project, env={**cli_env(), "AGENT_WORK_LOG_EMBED": embed}, text=True, capture_output=True,
            )
            if result.returncode:
                raise RuntimeError(f'{case["id"]}: CLI 退出 {result.returncode}: {result.stderr}')
            view = json.loads(result.stdout)
            returned = [row["id"] for row in view["lines"]]
            if len(returned) > k:
                raise RuntimeError(f'{case["id"]}: recall 返回条数超过 limit={k}')
            if case["kind"] == "negative":
                hit = not returned  # 负例：任何返回都算失败（隔离被破坏）
            else:
                hit = bool(set(returned) & set(case["expect_any_of"]))
            forbidden = sorted(set(returned) & set(case["forbid"]))
            results.append(dict(id=case["id"], kind=case["kind"], returned=returned,
                                hit=hit, forbidden=forbidden))
            group = groups.setdefault(case["kind"], dict(queries=0, hits=0, forbid_violations=0))
            group["queries"] += 1
            group["hits"] += int(hit)
            group["forbid_violations"] += len(forbidden)
    for group in groups.values():
        group["recall_at_k"] = group["hits"] / group["queries"]
    return dict(k=k, groups=groups, results=results)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed", default="auto", help="embedding 后端")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--queries", default=str(QUERIES), help="查询集 YAML 路径")
    args = parser.parse_args(argv)
    if args.k < 1:
        parser.error("--k 必须为正整数")
    if not graph_available():
        print("graph memory 尚未实现")
        return 0
    report = evaluate(load_queries(args.queries), k=args.k, embed=args.embed)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for kind, group in sorted(report["groups"].items()):
            print(f'{kind}: recall@{args.k}={group["recall_at_k"]:.3f} '
                  f'({group["hits"]}/{group["queries"]}), '
                  f'forbid 违规数={group["forbid_violations"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
