# -*- coding: utf-8 -*-
"""
第1层: 检索层测试
- 从测试问题中抽样20题(每种类型4题)
- 运行检索流程(嵌入 + 路由 + FAISS/BM25混合检索)
- 缓存检索结果供第2层重排测试使用
- 评估路由命中率和检索召回率

前置条件: 索引已构建(chunked_json, faiss_index, bm25_index)

用法:
    python test_1_retrieval.py
    python test_1_retrieval.py --sample-size 10
"""

import json
import time
import argparse
from typing import List, Dict

from test_utils import (
    setup_pra_path, load_questions, stratified_sample,
    save_results, load_results, print_summary, generate_report,
)

setup_pra_path()

from retrieval import Retriever
from config import CHUNKED_JSON_DIR, FAISS_INDEX_DIR, BM25_INDEX_DIR


# 问题与预期来源文档的映射关系
# 用于评估路由命中率: 检索到的数据库是否包含答案所在文档
QUESTION_SOURCE_MAP = {
    "中芯国际": [
        "【上海证券】中芯国际深度研究报告：晶圆制造龙头，领航国产芯片新征程",
        "【东方证券】产能利用率提升，持续推进工艺迭代和产品性能升级",
        "【中原证券】产能利用率显著提升，持续推进工艺迭代升级——中芯国际(688981)季报点评",
        "【光大证券】中芯国际2025年一季度业绩点评：1Q突发生产问题，2Q业绩有望筑底，自主可控趋势不改",
        "【兴证国际】季度盈利低于预期，看好国产芯片长期空间",
        "【华泰证券】中芯国际（688981）：上调港股目标价到63港币，看好DeepSeek推动代工需求强劲增长",
        "【国信证券】工业与汽车触底反弹，良率影响短期营收",
        "【财报】中芯国际：中芯国际2024年年度报告",
        "中芯国际机构调研纪要",
    ],
    "迪士尼": [
        "全球迪士尼乐园的现状和启示",
        "迪士尼公司发展分析",
        "香港迪士尼乐园旅游攻略",
    ],
    "浦发": [
        "浦发上海浦东发展银行西安分行个金客户经理考核办法",
    ],
}


def get_expected_sources(question: str) -> List[str]:
    """根据问题关键词推断预期来源文档"""
    sources = []
    for keyword, docs in QUESTION_SOURCE_MAP.items():
        if keyword in question:
            sources.extend(docs)
    return sources


def check_route_hit(retrieved_docs: List[Dict], expected_sources: List[str]) -> bool:
    """检查检索结果中是否包含预期来源文档"""
    if not expected_sources:
        return True
    retrieved_sources = {doc.get("source", "") for doc in retrieved_docs}
    for exp in expected_sources:
        for ret in retrieved_sources:
            if exp in ret or ret in exp:
                return True
    return False


def run_retrieval_test(sample_size: int = 4) -> List[Dict]:
    """运行检索层测试"""
    print("=" * 60)
    print("  第1层: 检索层测试")
    print("=" * 60)

    questions = load_questions()
    sampled = stratified_sample(questions, n_per_type=sample_size)
    print(f"\n抽样 {len(sampled)} 个问题 (每种类型 {sample_size} 个)")

    print("\n初始化检索器 (加载索引)...")
    t_init = time.time()
    retriever = Retriever(
        chunked_json_dir=CHUNKED_JSON_DIR,
        faiss_dir=FAISS_INDEX_DIR,
        bm25_dir=BM25_INDEX_DIR,
    )
    print(f"检索器初始化完成 ({time.time() - t_init:.1f}s)")

    results = []
    for i, q_item in enumerate(sampled):
        question = q_item["question"]
        prompt_type = q_item.get("prompt_type", "text")
        qid = q_item.get("id", i)

        print(f"\n[{i+1}/{len(sampled)}] ID={qid} [{prompt_type}] {question[:60]}...")

        expected = get_expected_sources(question)
        print(f"  预期来源: {len(expected)} 个文档")

        t0 = time.time()
        try:
            retrieved = retriever.retrieve(query=question)
            elapsed = time.time() - t0

            route_hit = check_route_hit(retrieved, expected)
            result_count = len(retrieved)

            result = {
                "id": qid,
                "question": question,
                "prompt_type": prompt_type,
                "passed": route_hit,
                "route_hit": route_hit,
                "retrieved_count": result_count,
                "elapsed": round(elapsed, 2),
                "expected_sources": expected,
                "retrieved_docs": [
                    {
                        "source": doc.get("source", ""),
                        "page": doc.get("page", 0),
                        "score": doc.get("score", 0),
                        "text": doc.get("text", ""),
                    }
                    for doc in retrieved
                ],
            }

            status = "HIT" if route_hit else "MISS"
            print(f"  [{status}] 检索到 {result_count} 条, 耗时 {elapsed:.2f}s")

        except Exception as e:
            elapsed = time.time() - t0
            result = {
                "id": qid,
                "question": question,
                "prompt_type": prompt_type,
                "passed": False,
                "route_hit": False,
                "error": str(e),
                "elapsed": round(elapsed, 2),
            }
            print(f"  [ERROR] {e}")

        results.append(result)

    route_hits = sum(1 for r in results if r.get("route_hit", False))
    avg_retrieved = sum(r.get("retrieved_count", 0) for r in results) / max(len(results), 1)
    avg_elapsed = sum(r.get("elapsed", 0) for r in results) / max(len(results), 1)

    print(f"\n--- 检索层测试结果 ---")
    print(f"  路由命中率: {route_hits}/{len(results)} ({route_hits/len(results)*100:.1f}%)")
    print(f"  平均检索数量: {avg_retrieved:.1f}")
    print(f"  平均耗时: {avg_elapsed:.2f}s")

    save_results(results, "test_1_retrieval_cache.json")
    generate_report(
        results,
        "检索层测试",
        "test_1_results.json",
        extra_info={
            "route_hit_rate": f"{route_hits}/{len(results)}",
            "avg_retrieved_count": round(avg_retrieved, 1),
            "avg_elapsed": round(avg_elapsed, 2),
        },
    )

    return results


def main():
    parser = argparse.ArgumentParser(description="第1层: 检索层测试")
    parser.add_argument("--sample-size", type=int, default=4, help="每种类型抽样数量")
    args = parser.parse_args()

    run_retrieval_test(sample_size=args.sample_size)


if __name__ == "__main__":
    main()
