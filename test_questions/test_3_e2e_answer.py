# -*- coding: utf-8 -*-
"""
第3层: 端到端答案测试
- 从260题中分层抽样40题(每种类型8题)
- 运行完整RAG流程(检索 -> 重排 -> LLM生成)
- 对boolean/number类型自动评估精确匹配
- 对name类型做包含匹配
- 对list类型计算集合召回率
- 对text类型输出结果供人工评分
- 生成评估报告

前置条件:
  - 索引已构建
  - DashScope API Key 已配置
  - (可选) 标准答案文件 test_3_expected_answers.json

用法:
    python test_3_e2e_answer.py
    python test_3_e2e_answer.py --sample-size 8
"""

import json
import time
import argparse
from typing import List, Dict, Optional, Any

from test_utils import (
    setup_pra_path, load_questions, stratified_sample,
    save_results, load_results, print_summary, generate_report,
    RESULTS_DIR,
)

setup_pra_path()

from questions_processing import QuestionProcessor
from config import CHUNKED_JSON_DIR, FAISS_INDEX_DIR, BM25_INDEX_DIR, LLM_MODEL, EMBEDDING_MODEL


EXPECTED_ANSWERS_FILE = RESULTS_DIR / "test_3_expected_answers.json"


def load_expected_answers() -> Dict[int, Any]:
    """加载人工标注的标准答案"""
    if EXPECTED_ANSWERS_FILE.exists():
        with open(EXPECTED_ANSWERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {item["id"]: item["expected_answer"] for item in data}
    return {}


def evaluate_boolean(answer: Any, expected: Any) -> bool:
    """评估boolean类型: 精确匹配"""
    if isinstance(expected, bool):
        return answer == expected
    expected_str = str(expected).lower().strip()
    answer_str = str(answer).lower().strip()
    return answer_str == expected_str


def evaluate_number(answer: Any, expected: Any) -> bool:
    """评估number类型: 数值匹配(容差1%)"""
    try:
        a = float(str(answer).replace(",", "").replace("亿", "00000000").replace("万", "0000"))
        e = float(str(expected).replace(",", "").replace("亿", "00000000").replace("万", "0000"))
        if e == 0:
            return a == 0
        return abs(a - e) / abs(e) < 0.01
    except (ValueError, TypeError):
        return str(answer).strip() == str(expected).strip()


def evaluate_name(answer: Any, expected: Any) -> bool:
    """评估name类型: 包含匹配"""
    answer_str = str(answer).strip()
    expected_str = str(expected).strip()
    return expected_str in answer_str or answer_str in expected_str


def evaluate_list(answer: Any, expected: Any) -> float:
    """评估list类型: 集合召回率"""
    if not isinstance(answer, list):
        answer = [str(answer)]
    if not isinstance(expected, list):
        expected = [str(expected)]

    answer_set = {str(a).strip() for a in answer}
    expected_set = {str(e).strip() for e in expected}

    if not expected_set:
        return 1.0

    hits = sum(1 for e in expected_set if any(e in a or a in e for a in answer_set))
    return hits / len(expected_set)


def evaluate_answer(answer: Any, expected: Any, prompt_type: str) -> Dict:
    """根据类型评估答案"""
    if answer is None or str(answer).strip().upper() == "N/A":
        return {"score": 0.0, "method": "N/A回答", "match": False}

    if prompt_type == "boolean":
        match = evaluate_boolean(answer, expected)
        return {"score": 1.0 if match else 0.0, "method": "精确匹配", "match": match}
    elif prompt_type == "number":
        match = evaluate_number(answer, expected)
        return {"score": 1.0 if match else 0.0, "method": "数值匹配(1%容差)", "match": match}
    elif prompt_type == "name":
        match = evaluate_name(answer, expected)
        return {"score": 1.0 if match else 0.0, "method": "包含匹配", "match": match}
    elif prompt_type == "list":
        recall = evaluate_list(answer, expected)
        return {"score": recall, "method": "集合召回率", "match": recall >= 0.8}
    else:
        return {"score": -1.0, "method": "需人工评估", "match": False}


def init_expected_answers_template(sampled: List[Dict]):
    """为抽样问题生成标准答案模板文件(供人工填写)"""
    template = []
    for q in sampled:
        template.append({
            "id": q["id"],
            "question": q["question"],
            "prompt_type": q.get("prompt_type", "text"),
            "expected_answer": "",
        })

    RESULTS_DIR.mkdir(exist_ok=True)
    if not EXPECTED_ANSWERS_FILE.exists():
        with open(EXPECTED_ANSWERS_FILE, "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        print(f"\n标准答案模板已生成: {EXPECTED_ANSWERS_FILE}")
        print("请填写 expected_answer 字段后重新运行测试")
    else:
        print(f"\n标准答案文件已存在: {EXPECTED_ANSWERS_FILE}")


def run_e2e_test(sample_size: int = 8, skip_if_no_answers: bool = False) -> List[Dict]:
    """运行端到端答案测试"""
    print("=" * 60)
    print("  第3层: 端到端答案测试")
    print("=" * 60)

    questions = load_questions()
    sampled = stratified_sample(questions, n_per_type=sample_size)
    print(f"\n抽样 {len(sampled)} 个问题 (每种类型 {sample_size} 个)")

    # 加载标准答案
    expected = load_expected_answers()
    has_answers = len(expected) > 0

    if not has_answers:
        init_expected_answers_template(sampled)
        if skip_if_no_answers:
            print("未填写标准答案，跳过测试")
            return []

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

    results = []
    for i, q_item in enumerate(sampled):
        question = q_item["question"]
        prompt_type = q_item.get("prompt_type", "text")
        qid = q_item.get("id", i)

        print(f"\n[{i+1}/{len(sampled)}] ID={qid} [{prompt_type}] {question[:60]}...")

        t0 = time.time()
        try:
            result = processor.answer(
                question=question,
                prompt_type=prompt_type,
            )
            elapsed = time.time() - t0

            final_answer = result.get("final_answer")
            relevant_pages = result.get("relevant_pages", [])
            context_docs = result.get("context_docs", [])

            # 评估
            eval_result = {"score": -1.0, "method": "无标准答案", "match": False}
            if qid in expected:
                eval_result = evaluate_answer(final_answer, expected[qid], prompt_type)

            result_item = {
                "id": qid,
                "question": question,
                "prompt_type": prompt_type,
                "final_answer": final_answer,
                "relevant_pages": relevant_pages,
                "context_doc_count": len(context_docs),
                "elapsed": round(elapsed, 2),
                "eval_score": eval_result["score"],
                "eval_method": eval_result["method"],
                "eval_match": eval_result["match"],
                "passed": eval_result["score"] > 0 if eval_result["score"] >= 0 else None,
            }

            if qid in expected:
                result_item["expected_answer"] = expected[qid]

            eval_str = f"score={eval_result['score']:.2f}" if eval_result["score"] >= 0 else "待人工评估"
            print(f"  答案: {str(final_answer)[:80]}")
            print(f"  评估: {eval_str}, 耗时 {elapsed:.2f}s")

        except Exception as e:
            elapsed = time.time() - t0
            result_item = {
                "id": qid,
                "question": question,
                "prompt_type": prompt_type,
                "passed": False,
                "error": str(e),
                "elapsed": round(elapsed, 2),
                "eval_score": 0.0,
            }
            print(f"  [ERROR] {e}")

        results.append(result_item)

    # 汇总统计
    auto_eval = [r for r in results if r.get("eval_score", -1) >= 0]
    manual_eval = [r for r in results if r.get("eval_score", -1) < 0]

    if auto_eval:
        avg_score = sum(r["eval_score"] for r in auto_eval) / len(auto_eval)
        match_count = sum(1 for r in auto_eval if r.get("eval_match", False))
        print(f"\n--- 端到端测试结果 ---")
        print(f"  自动评估: {len(auto_eval)} 题, 平均分 {avg_score:.2f}, 匹配 {match_count}/{len(auto_eval)}")
        print(f"  待人工评估: {len(manual_eval)} 题")

        by_type = {}
        for r in auto_eval:
            pt = r.get("prompt_type", "unknown")
            by_type.setdefault(pt, []).append(r)
        for pt, items in by_type.items():
            avg = sum(r["eval_score"] for r in items) / len(items)
            matches = sum(1 for r in items if r.get("eval_match", False))
            print(f"    {pt:8s}: 平均分 {avg:.2f}, 匹配 {matches}/{len(items)}")

    generate_report(
        results,
        "端到端答案测试",
        "test_3_results.json",
        extra_info={
            "auto_eval_count": len(auto_eval),
            "manual_eval_count": len(manual_eval),
        } if auto_eval else {},
    )

    save_results(results, "test_3_e2e_cache.json")
    return results


def main():
    parser = argparse.ArgumentParser(description="第3层: 端到端答案测试")
    parser.add_argument("--sample-size", type=int, default=8, help="每种类型抽样数量")
    parser.add_argument("--skip-if-no-answers", action="store_true", help="无标准答案时跳过")
    args = parser.parse_args()

    run_e2e_test(sample_size=args.sample_size, skip_if_no_answers=args.skip_if_no_answers)


if __name__ == "__main__":
    main()
