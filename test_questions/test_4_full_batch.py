# -*- coding: utf-8 -*-
"""
第4层: 全量测试
- 对全部260个问题运行完整RAG流程
- 保存所有答案供后续分析
- 生成综合质量报告
- 支持断点续跑(跳过已完成的问题)

前置条件:
  - 索引已构建
  - DashScope API Key 已配置

用法:
    python test_4_full_batch.py
    python test_4_full_batch.py --resume
    python test_4_full_batch.py --start-from 50
"""

import json
import time
import argparse
from typing import List, Dict
from collections import Counter

from test_utils import (
    setup_pra_path, load_questions,
    save_results, load_results, generate_report,
    RESULTS_DIR,
)

setup_pra_path()

from questions_processing import QuestionProcessor
from config import CHUNKED_JSON_DIR, FAISS_INDEX_DIR, BM25_INDEX_DIR, LLM_MODEL, EMBEDDING_MODEL

BATCH_CACHE_FILE = "test_4_batch_cache.json"


def run_full_batch(start_from: int = 0, resume: bool = False) -> List[Dict]:
    """运行全量测试"""
    print("=" * 60)
    print("  第4层: 全量测试")
    print("=" * 60)

    questions = load_questions()
    print(f"\n共 {len(questions)} 个问题")

    # 断点续跑: 加载已有结果
    existing_results: Dict[int, Dict] = {}
    if resume:
        cached = load_results(BATCH_CACHE_FILE)
        if cached:
            existing_results = {r["id"]: r for r in cached if "id" in r}
            print(f"已加载 {len(existing_results)} 条缓存结果")

    # 确定待处理问题
    if start_from > 0:
        questions = questions[start_from:]
        print(f"从第 {start_from} 题开始")

    if resume and existing_results:
        questions = [q for q in questions if q.get("id") not in existing_results]
        print(f"跳过已完成的 {len(existing_results)} 题, 剩余 {len(questions)} 题")

    if not questions:
        print("所有问题已处理完毕")
        all_results = list(existing_results.values())
        generate_report(all_results, "全量测试", "test_4_results.json")
        return all_results

    # 初始化处理器
    print("\n初始化 QuestionProcessor...")
    t_init = time.time()
    processor = QuestionProcessor(
        chunked_json_dir=CHUNKED_JSON_DIR,
        faiss_dir=FAISS_INDEX_DIR,
        bm25_dir=BM25_INDEX_DIR,
        embedding_model=EMBEDDING_MODEL,
        llm_model=LLM_MODEL,
    )
    print(f"初始化完成 ({time.time() - t_init:.1f}s)")

    results = list(existing_results.values())
    total_start = time.time()

    for i, q_item in enumerate(questions):
        question = q_item["question"]
        prompt_type = q_item.get("prompt_type", "text")
        qid = q_item.get("id", len(results) + 1)

        print(f"\n[{len(results)+1}] ID={qid} [{prompt_type}] {question[:60]}...")

        t0 = time.time()
        try:
            result = processor.answer(
                question=question,
                prompt_type=prompt_type,
            )
            elapsed = time.time() - t0

            result_item = {
                "id": qid,
                "question": question,
                "prompt_type": prompt_type,
                "final_answer": result.get("final_answer"),
                "relevant_pages": result.get("relevant_pages", []),
                "context_doc_count": len(result.get("context_docs", [])),
                "elapsed": round(elapsed, 2),
            }

            print(f"  答案: {str(result_item['final_answer'])[:80]}, 耗时 {elapsed:.2f}s")

        except Exception as e:
            elapsed = time.time() - t0
            result_item = {
                "id": qid,
                "question": question,
                "prompt_type": prompt_type,
                "error": str(e),
                "elapsed": round(elapsed, 2),
            }
            print(f"  [ERROR] {e}")

        results.append(result_item)

        # 每20题保存一次缓存
        if (i + 1) % 20 == 0:
            save_results(results, BATCH_CACHE_FILE)
            avg_elapsed = sum(r.get("elapsed", 0) for r in results) / len(results)
            eta = avg_elapsed * (len(questions) - i - 1)
            print(f"\n  [进度] {i+1}/{len(questions)}, 平均耗时 {avg_elapsed:.1f}s/题, 预计剩余 {eta/60:.1f}min")

    # 保存最终结果
    total_elapsed = time.time() - total_start
    save_results(results, BATCH_CACHE_FILE)

    # 统计
    type_counter = Counter(r.get("prompt_type", "unknown") for r in results)
    error_count = sum(1 for r in results if "error" in r)
    avg_elapsed = sum(r.get("elapsed", 0) for r in results) / max(len(results), 1)

    print(f"\n--- 全量测试结果 ---")
    print(f"  总数: {len(results)}")
    print(f"  错误: {error_count}")
    print(f"  平均耗时: {avg_elapsed:.2f}s/题")
    print(f"  总耗时: {total_elapsed/60:.1f}min")
    print(f"  类型分布: {dict(type_counter)}")

    generate_report(
        results,
        "全量测试",
        "test_4_results.json",
        extra_info={
            "total_questions": len(results),
            "error_count": error_count,
            "avg_elapsed_per_question": round(avg_elapsed, 2),
            "total_elapsed_minutes": round(total_elapsed / 60, 1),
            "type_distribution": dict(type_counter),
        },
    )

    return results


def main():
    parser = argparse.ArgumentParser(description="第4层: 全量测试")
    parser.add_argument("--start-from", type=int, default=0, help="从第N题开始(0-based)")
    parser.add_argument("--resume", action="store_true", help="断点续跑(跳过已完成的题)")
    args = parser.parse_args()

    run_full_batch(start_from=args.start_from, resume=args.resume)


if __name__ == "__main__":
    main()
