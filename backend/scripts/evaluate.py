from __future__ import annotations

"""离线评测 runner：黄金 SQL 校验/快照与 Schema 检索召回评测。

用法（在 backend 目录下）：
    python scripts/evaluate.py golden [--check]
    python scripts/evaluate.py recall [--k 20]

golden 与单测零 LLM 成本；recall 每题 1 次 embed + 1 次 rerank 小额调用。
数据目录由 CURATED_DATA_ROOT 决定，指向冻结快照可保证结果可复现。
"""

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.querying.duckdb_engine import DuckDbEngine  # noqa: E402
from eval.dataset import load_cases  # noqa: E402
from eval.scoring import (  # noqa: E402
    compare_result_sets,
    field_recall,
    mrr,
    table_hit_rate,
)

DATASET_PATH = BACKEND_ROOT / "eval" / "dataset.json"
REPORTS_DIR = BACKEND_ROOT / "eval" / "reports"
DATABASE_ID = "trade_data"


def run_golden(check: bool) -> int:
    cases = [case for case in load_cases(DATASET_PATH) if case.get("golden_sql")]
    if not cases:
        print("数据集中没有包含 golden_sql 的用例")
        return 0
    engine = DuckDbEngine()
    failures = 0
    for case in cases:
        execution = engine.execute(DATABASE_ID, case["golden_sql"])
        if not execution.success:
            failures += 1
            print(f"[失败] {case['id']}：黄金 SQL 未通过校验或执行：{execution.error}")
            continue
        result = {"columns": execution.columns, "rows": execution.rows}
        if check:
            expected = case.get("expected_result")
            if not expected:
                failures += 1
                print(f"[失败] {case['id']}：缺少 expected_result，请先运行 golden 生成快照")
                continue
            ok, reason = compare_result_sets(expected, result)
            status = "通过" if ok else "失败"
            if not ok:
                failures += 1
            print(f"[{status}] {case['id']}（{len(result['rows'])} 行）{reason}")
        else:
            case["expected_result"] = result
            print(f"[快照] {case['id']}：{len(result['rows'])} 行 × {len(result['columns'])} 列")
    if not check:
        payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        payload["cases"] = [
            next((updated for updated in cases if updated["id"] == case["id"]), case)
            for case in payload["cases"]
        ]
        DATASET_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"已写回 {DATASET_PATH}")
    return 1 if failures else 0


def run_recall(top_k: int) -> int:
    from app.model_client import ModelClient
    from app.retrieval import SchemaIndex

    cases = [case for case in load_cases(DATASET_PATH) if case.get("expected_fields")]
    if not cases:
        print("数据集中没有包含 expected_fields 的用例")
        return 0
    index = SchemaIndex(ModelClient())
    rows: list[dict[str, object]] = []
    for case in cases:
        started_at = time.perf_counter()
        retrieval = index.retrieve(case["query"], retrieval_terms=case["retrieval_terms"])
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        hits = retrieval["hits"][:top_k]
        rows.append({
            "id": case["id"],
            "category": case["category"],
            "field_recall": round(field_recall(case["expected_fields"], hits), 4),
            "table_hit_rate": round(table_hit_rate(case["expected_tables"], hits), 4),
            "mrr": round(mrr(case["expected_fields"], hits), 4),
            "selected_count": retrieval["selected_count"],
            "elapsed_ms": elapsed_ms,
        })
        print(
            f"{case['id']} [{case['category']}] "
            f"字段召回 {rows[-1]['field_recall']:.2f} "
            f"表命中 {rows[-1]['table_hit_rate']:.2f} "
            f"MRR {rows[-1]['mrr']:.2f} "
            f"（候选 {retrieval['rrf_count']} → 入选 {retrieval['selected_count']}，{elapsed_ms}ms）"
        )
    count = len(rows)
    summary = {
        "cases": count,
        "field_recall": round(sum(float(row["field_recall"]) for row in rows) / count, 4),
        "table_hit_rate": round(sum(float(row["table_hit_rate"]) for row in rows) / count, 4),
        "mrr": round(sum(float(row["mrr"]) for row in rows) / count, 4),
    }
    print(
        f"\n汇总（{count} 题）：字段召回 {summary['field_recall']:.4f} "
        f"表命中 {summary['table_hit_rate']:.4f} MRR {summary['mrr']:.4f}"
    )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (REPORTS_DIR / f"recall-{stamp}.json").write_text(
        json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"报告已写入 {REPORTS_DIR / f'recall-{stamp}.json'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FinQuery 离线评测 runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    golden_parser = subparsers.add_parser("golden", help="执行黄金 SQL 并生成/校验结果快照")
    golden_parser.add_argument(
        "--check", action="store_true", help="校验模式：与已有快照比对而不写回"
    )
    recall_parser = subparsers.add_parser("recall", help="Schema 检索召回评测（小额 API 调用）")
    recall_parser.add_argument("--k", type=int, default=20, help="参与评分的 hits 上限")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "golden":
        return run_golden(args.check)
    return run_recall(args.k)


if __name__ == "__main__":
    sys.exit(main())
