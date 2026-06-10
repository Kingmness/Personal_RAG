# -*- coding: utf-8 -*-
"""
测试公共工具模块
- 加载测试问题
- 分层抽样
- 结果保存与报告生成
"""

import json
import time
import sys
from pathlib import Path
from typing import List, Dict, Optional
from collections import Counter

PRA_DIR = Path(__file__).resolve().parent.parent / "Backend"
TEST_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = TEST_DIR / "rag_test_questions.md"
RESULTS_DIR = TEST_DIR / "results"

VALID_TYPES = ["boolean", "number", "name", "list", "text"]


def setup_pra_path():
    """将 PRA 目录加入 sys.path，使测试脚本可以导入项目模块"""
    pra_str = str(PRA_DIR)
    if pra_str not in sys.path:
        sys.path.insert(0, pra_str)


def load_questions(path: Path = QUESTIONS_FILE) -> List[Dict]:
    """从 JSON 文件加载测试问题"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def stratified_sample(
    questions: List[Dict],
    n_per_type: int = 4,
    seed: int = 42,
) -> List[Dict]:
    """按 prompt_type 分层抽样，每种类型取 n_per_type 个"""
    import random
    rng = random.Random(seed)

    by_type: Dict[str, List[Dict]] = {}
    for q in questions:
        pt = q.get("prompt_type", "text")
        by_type.setdefault(pt, []).append(q)

    sampled = []
    for pt in VALID_TYPES:
        pool = by_type.get(pt, [])
        if len(pool) <= n_per_type:
            sampled.extend(pool)
        else:
            sampled.extend(rng.sample(pool, n_per_type))

    return sampled


def save_results(data: dict, filename: str):
    """保存测试结果到 results 目录"""
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {path}")
    return path


def load_results(filename: str) -> Optional[dict]:
    """从 results 目录加载测试结果"""
    path = RESULTS_DIR / filename
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_summary(results: List[Dict], title: str = "测试摘要"):
    """打印测试结果摘要"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

    total = len(results)
    passed = sum(1 for r in results if r.get("passed", False))
    failed = total - passed

    print(f"  总数: {total}")
    print(f"  通过: {passed}")
    print(f"  失败: {failed}")
    if total > 0:
        print(f"  通过率: {passed/total*100:.1f}%")

    by_type = {}
    for r in results:
        pt = r.get("prompt_type", "unknown")
        by_type.setdefault(pt, []).append(r)

    print(f"\n  按类型统计:")
    for pt in VALID_TYPES:
        items = by_type.get(pt, [])
        if not items:
            continue
        p = sum(1 for x in items if x.get("passed", False))
        print(f"    {pt:8s}: {p}/{len(items)} 通过")

    print(f"{'='*60}\n")


def generate_report(
    results: List[Dict],
    title: str,
    filename: str,
    extra_info: Optional[Dict] = None,
):
    """生成可读的测试报告并保存"""
    report = {
        "title": title,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "passed": sum(1 for r in results if r.get("passed", False)),
        "by_type": {},
    }

    if extra_info:
        report.update(extra_info)

    by_type: Dict[str, List[Dict]] = {}
    for r in results:
        pt = r.get("prompt_type", "unknown")
        by_type.setdefault(pt, []).append(r)

    for pt, items in by_type.items():
        p = sum(1 for x in items if x.get("passed", False))
        report["by_type"][pt] = {
            "total": len(items),
            "passed": p,
            "rate": f"{p/len(items)*100:.1f}%" if items else "0%",
        }

    report["details"] = results
    save_results(report, filename)
    return report
