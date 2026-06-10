# -*- coding: utf-8 -*-
"""
第2层: 重排层测试
- 加载第1层缓存的检索结果
- 对检索结果执行LLM重排序
- 对比重排前后的排序变化(MRR指标)
- 评估重排是否提升了相关文档的排名

前置条件:
  - 第1层测试已完成 (test_1_retrieval_cache.json)
  - DashScope API Key 已配置

用法:
    python test_2_reranking.py
    python test_2_reranking.py --re-run-retrieval
"""

import json
import time
import argparse
from typing import List, Dict, Optional

from test_utils import (
    setup_pra_path, load_questions, stratified_sample,
    save_results, load_results, print_summary, generate_report,
)

setup_pra_path()

from retrieval import Retriever
from reranking import Reranker
from config import CHUNKED_JSON_DIR, FAISS_INDEX_DIR, BM25_INDEX_DIR, LLM_MODEL


def compute_mrr(reranked_docs: List[Dict], expected_sources: List[str]) -> float:
    """
    计算MRR(Mean Reciprocal Rank)
    第一个相关文档出现位置的倒数
    """
    if not expected_sources:
        return 1.0
    for rank, doc in enumerate(reranked_docs, 1):
        source = doc.get("source", "")
        for exp in expected_sources:
            if exp in source or source in exp:
                return 1.0 / rank
    return 0.0


def run_reranking_test(re_run_retrieval: bool = False, sample_size: int = 4) -> List[Dict]:
    """运行重排层测试"""
    print("=" * 60)
    print("  第2层: 重排层测试")
    print("=" * 60)

    # 加载第1层缓存的检索结果
    cached = load_results("test_1_retrieval_cache.json") if not re_run_retrieval else None

    if cached is None:
        print("\n未找到第1层缓存，重新运行检索...")
        from test_1_retrieval import run_retrieval_test, get_expected_sources
        retrieval_results = run_retrieval_test(sample_size=sample_size)
    else:
        print(f"\n加载第1层缓存: {len(cached)} 条检索结果")
        retrieval_results = cached

    # 初始化组件
    retriever = None
    reranker = Reranker(model=LLM_MODEL)

    if re_run_retrieval or any("retrieved_docs" not in r for r in retrieval_results):
        retriever = Retriever(
            chunked_json_dir=CHUNKED_JSON_DIR,
            faiss_dir=FAISS_INDEX_DIR,
            bm25_dir=BM25_INDEX_DIR,
        )

    results = []
    for i, item in enumerate(retrieval_results):
        question = item["question"]
        prompt_type = item.get("prompt_type", "text")
        qid = item.get("id", i)
        expected_sources = item.get("expected_sources", [])

        print(f"\n[{i+1}/{len(retrieval_results)}] ID={qid} [{prompt_type}] {question[:60]}...")

        # 获取检索结果(缓存中必须有text字段才能用于重排)
        cached_docs = item.get("retrieved_docs", [])
        has_text = cached_docs and all("text" in d for d in cached_docs)
        if has_text and not re_run_retrieval:
            retrieved = cached_docs
        else:
            if cached_docs and not has_text:
                print(f"  缓存缺少text字段, 重新检索...")
            try:
                if retriever is None:
                    retriever = Retriever(
                        chunked_json_dir=CHUNKED_JSON_DIR,
                        faiss_dir=FAISS_INDEX_DIR,
                        bm25_dir=BM25_INDEX_DIR,
                    )
                retrieved = retriever.retrieve(query=question)
            except Exception as e:
                print(f"  [ERROR] 检索失败: {e}")
                results.append({
                    "id": qid,
                    "question": question,
                    "prompt_type": prompt_type,
                    "passed": False,
                    "error": f"检索失败: {e}",
                })
                continue

        if not retrieved:
            print(f"  [SKIP] 无检索结果")
            results.append({
                "id": qid,
                "question": question,
                "prompt_type": prompt_type,
                "passed": False,
                "detail": "无检索结果",
            })
            continue

        # 计算重排前MRR
        mrr_before = compute_mrr(retrieved, expected_sources)

        # 执行重排
        t0 = time.time()
        try:
            reranked = reranker.rerank(
                query=question,
                documents=retrieved,
                batch_size=4,
                llm_weight=0.7,
                top_n=10,
            )
            elapsed = time.time() - t0

            # 计算重排后MRR
            mrr_after = compute_mrr(reranked, expected_sources)
            improved = mrr_after >= mrr_before

            result = {
                "id": qid,
                "question": question,
                "prompt_type": prompt_type,
                "passed": improved,
                "mrr_before": round(mrr_before, 4),
                "mrr_after": round(mrr_after, 4),
                "mrr_delta": round(mrr_after - mrr_before, 4),
                "elapsed": round(elapsed, 2),
                "reranked_docs": [
                    {
                        "source": doc.get("source", ""),
                        "page": doc.get("page", 0),
                        "score": doc.get("score", 0),
                        "relevance_score": doc.get("relevance_score", 0),
                        "combined_score": doc.get("combined_score", 0),
                    }
                    for doc in reranked
                ],
            }

            arrow = "+" if mrr_after > mrr_before else ("=" if mrr_after == mrr_before else "-")
            print(f"  MRR: {mrr_before:.4f} -> {mrr_after:.4f} ({arrow}{abs(mrr_after-mrr_before):.4f}), 耗时 {elapsed:.2f}s")

        except Exception as e:
            elapsed = time.time() - t0
            result = {
                "id": qid,
                "question": question,
                "prompt_type": prompt_type,
                "passed": False,
                "error": str(e),
                "elapsed": round(elapsed, 2),
            }
            print(f"  [ERROR] 重排失败: {e}")

        results.append(result)

    # 汇总统计
    valid_results = [r for r in results if "mrr_before" in r]
    if valid_results:
        avg_mrr_before = sum(r["mrr_before"] for r in valid_results) / len(valid_results)
        avg_mrr_after = sum(r["mrr_after"] for r in valid_results) / len(valid_results)
        improved_count = sum(1 for r in valid_results if r["mrr_after"] > r["mrr_before"])
        same_count = sum(1 for r in valid_results if r["mrr_after"] == r["mrr_before"])
        degraded_count = sum(1 for r in valid_results if r["mrr_after"] < r["mrr_before"])

        print(f"\n--- 重排层测试结果 ---")
        print(f"  平均MRR: {avg_mrr_before:.4f} -> {avg_mrr_after:.4f}")
        print(f"  排名提升: {improved_count}, 持平: {same_count}, 下降: {degraded_count}")

        generate_report(
            results,
            "重排层测试",
            "test_2_results.json",
            extra_info={
                "avg_mrr_before": round(avg_mrr_before, 4),
                "avg_mrr_after": round(avg_mrr_after, 4),
                "improved": improved_count,
                "same": same_count,
                "degraded": degraded_count,
            },
        )
    else:
        print("\n无有效重排结果")
        generate_report(results, "重排层测试", "test_2_results.json")

    save_results(results, "test_2_reranking_cache.json")
    return results


def main():
    parser = argparse.ArgumentParser(description="第2层: 重排层测试")
    parser.add_argument("--re-run-retrieval", action="store_true", help="重新运行检索(不使用缓存)")
    parser.add_argument("--sample-size", type=int, default=4, help="每种类型抽样数量(仅重新检索时生效)")
    args = parser.parse_args()

    run_reranking_test(re_run_retrieval=args.re_run_retrieval, sample_size=args.sample_size)


if __name__ == "__main__":
    main()
