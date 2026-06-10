# -*- coding: utf-8 -*-
"""
CLI 命令行入口
提供统一的命令行接口，支持各阶段单独执行和全流程一键运行。

使用示例:
  # PDF 解析
  python main.py parse-pdfs

  # 文本分块
  python main.py chunk

  # 构建索引
  python main.py build-index

  # 元信息注册
  python main.py register-metadata --company "中芯国际" --type "研报"

  # 单个问题问答
  python main.py answer --question "中芯国际2025年Q1营收是多少？" --type number

  # 批量问答
  python main.py batch-answer --questions questions.json --output answers.json

  # 一键全流程
  python main.py full-pipeline --skip-parse
"""

import json
import sys
import uuid
from pathlib import Path
from typing import Optional

import click

from config import RunConfig
from pipeline import Pipeline
from logger import setup_logger, set_trace_id

_log = setup_logger(name="pra.cli")


# ==================== 主命令组 ====================

@click.group()
@click.version_option(version="1.0.0", prog_name="PRA-RAG")
def cli():
    """PRA RAG 企业知识库问答系统命令行工具"""
    # 为每次 CLI 执行分配 trace_id
    tid = uuid.uuid4().hex[:12]
    set_trace_id(tid)
    _log.info("[CLI] 会话开始 trace_id=%s", tid)


# ==================== PDF 解析 ====================

@cli.command("parse-pdfs")
@click.option(
    "--pdf-dir", "-d",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="PDF 文件目录，默认读取 pdf_data 目录",
)
def parse_pdfs(pdf_dir: Optional[Path]):
    """解析 PDF 文件为带页码标记的 Markdown"""
    pipeline = Pipeline()
    pipeline.parse_pdfs(pdf_dir=pdf_dir)


# ==================== 文本分块 ====================

@cli.command("chunk")
@click.option(
    "--chunk-size", "-s",
    type=int,
    default=None,
    help="每个分块的 token 数，默认 300",
)
@click.option(
    "--chunk-overlap", "-o",
    type=int,
    default=None,
    help="分块之间的重叠 token 数，默认 50",
)
def chunk(chunk_size: Optional[int], chunk_overlap: Optional[int]):
    """将 Markdown 按页码和 token 进行分块"""
    run_config = RunConfig()
    if chunk_size is not None:
        run_config.chunk_size = chunk_size
    if chunk_overlap is not None:
        run_config.chunk_overlap = chunk_overlap

    pipeline = Pipeline(run_config=run_config)
    pipeline.chunk_reports()


# ==================== 索引构建 ====================

@cli.command("build-index")
def build_index():
    """构建 BM25 和 FAISS 索引"""
    pipeline = Pipeline()
    pipeline.build_indices()


# ==================== 元信息注册 ====================

@cli.command("register-metadata")
@click.option(
    "--company", "-c",
    type=str,
    default="",
    help="公司名称，为空则从文件名推断",
)
@click.option(
    "--type", "-t",
    "report_type",
    type=str,
    default="",
    help="报告类型（研报/年报/调研纪要）",
)
@click.option(
    "--year", "-y",
    type=str,
    default="",
    help="报告年份",
)
def register_metadata(company: str, report_type: str, year: str):
    """注册 PDF 文档的元信息"""
    pipeline = Pipeline()
    pipeline.register_metadata(
        company_name=company,
        report_type=report_type,
        report_year=year,
    )


# ==================== 单个问答 ====================

@cli.command("answer")
@click.option(
    "--question", "-q",
    type=str,
    required=True,
    help="用户问题",
)
@click.option(
    "--type", "-t",
    "prompt_type",
    type=click.Choice(["number", "name", "boolean", "list"]),
    default="number",
    help="答案类型",
)
@click.option(
    "--top-k",
    type=int,
    default=None,
    help="路由匹配的数据库数",
)
@click.option(
    "--retrieve-n",
    type=int,
    default=None,
    help="检索返回数量",
)
@click.option(
    "--rerank-top-n",
    type=int,
    default=None,
    help="重排后保留数量",
)
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="答案输出 JSON 文件路径",
)
def answer_question(
    question: str,
    prompt_type: str,
    top_k: Optional[int],
    retrieve_n: Optional[int],
    rerank_top_n: Optional[int],
    output: Optional[Path],
):
    """对单个问题进行 RAG 问答"""
    run_config = RunConfig()
    if top_k is not None:
        run_config.route_top_k = top_k
    if retrieve_n is not None:
        run_config.retrieve_top_n = retrieve_n
    if rerank_top_n is not None:
        run_config.rerank_top_n = rerank_top_n

    pipeline = Pipeline(run_config=run_config)
    result = pipeline.answer_question(question=question, prompt_type=prompt_type)

    # 输出
    _log.info("=" * 60)
    _log.info("问题: %s", result['question'])
    _log.info("答案: %s", result['final_answer'])
    _log.info("推理摘要: %s", result['reasoning_summary'])
    _log.info("引用页码: %s", result['relevant_pages'])
    _log.info("上下文来源: %s", [d['source'] for d in result['context_docs']])
    _log.info("=" * 60)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        _log.info("答案已保存到: %s", output)


# ==================== 批量问答 ====================

@cli.command("batch-answer")
@click.option(
    "--questions", "-q",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="问题 JSON 文件路径",
)
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="答案输出 JSON 文件路径",
)
@click.option(
    "--top-k",
    type=int,
    default=None,
    help="路由匹配的数据库数",
)
def batch_answer(
    questions: Path,
    output: Optional[Path],
    top_k: Optional[int],
):
    """批量处理问题文件"""
    run_config = RunConfig()
    if top_k is not None:
        run_config.route_top_k = top_k

    pipeline = Pipeline(run_config=run_config)
    results = pipeline.batch_answer(
        questions_file=questions,
        output_file=output,
    )

    # 输出摘要
    _log.info("=" * 60)
    _log.info("批量问答完成，共处理 %d 个问题", len(results))
    for i, r in enumerate(results):
        answer = r.get("final_answer", r.get("sub_answers", "比较类问题"))
        _log.info("  [%d] %s... => %s", i+1, r['question'][:50], answer)
    _log.info("=" * 60)


# ==================== 一键全流程 ====================

@cli.command("full-pipeline")
@click.option(
    "--skip-parse",
    is_flag=True,
    default=False,
    help="跳过 PDF 解析阶段",
)
@click.option(
    "--skip-chunk",
    is_flag=True,
    default=False,
    help="跳过文本分块阶段",
)
@click.option(
    "--skip-index",
    is_flag=True,
    default=False,
    help="跳过索引构建阶段",
)
@click.option(
    "--skip-metadata",
    is_flag=True,
    default=False,
    help="跳过元信息注册阶段",
)
@click.option(
    "--company", "-c",
    type=str,
    default="",
    help="公司名称（用于元信息注册）",
)
@click.option(
    "--questions", "-q",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="问题 JSON 文件路径（可选）",
)
@click.option(
    "--question",
    type=str,
    default=None,
    help="直接输入问题（支持 # 号分隔多问，如 '问题1#问题2#问题3'）",
)
@click.option(
    "--interactive", "-i",
    is_flag=True,
    default=False,
    help="交互模式：在终端逐条输入问题，按回车继续，输入 q 退出",
)
def full_pipeline(
    skip_parse: bool,
    skip_chunk: bool,
    skip_index: bool,
    skip_metadata: bool,
    company: str,
    questions: Optional[Path],
    question: Optional[str],
    interactive: bool,
):
    """一键执行完整 RAG 流程"""
    pipeline = Pipeline()

    # 先注册元信息
    pipeline.register_metadata(company_name=company)

    # 确定问答方式
    questions_file = questions
    if question:
        # --question 输入的问题写入临时 JSON 文件
        import tempfile
        questions_list = [q.strip() for q in question.split("#") if q.strip()]
        parsed = []
        for q in questions_list:
            question_text = q
            prompt_type = "number"
            for ttype in ["name", "boolean", "list", "number"]:
                if q.lower().endswith(f":{ttype}"):
                    question_text = q[: -len(f":{ttype}")].strip()
                    prompt_type = ttype
                    break
            parsed.append({"question": question_text, "prompt_type": prompt_type})
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="pra_questions_", delete=False
        )
        with tmp as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)
        questions_file = Path(tmp.name)

    # 执行各阶段
    pipeline.run_full_pipeline(
        skip_parse=skip_parse,
        skip_chunk=skip_chunk,
        skip_index=skip_index,
        skip_metadata=skip_metadata,
        questions_file=questions_file,
        interactive=interactive,
    )


# ==================== 查看配置 ====================

@cli.command("info")
def info():
    """查看当前项目配置和索引状态"""
    from config import RunConfig, PipelinePaths

    paths = PipelinePaths()

    click.echo("=" * 50)
    click.echo("PRA RAG 项目信息")
    click.echo("=" * 50)

    click.echo(f"\n项目根目录: {paths.project_root}")

    click.echo("\n--- 数据目录 ---")
    click.echo(f"  PDF 源文件:   {paths.pdf_data} ({_count_files(paths.pdf_data, '*.pdf')} 个文件)")
    click.echo(f"  解析 MD:       {paths.parsed_md} ({_count_files(paths.parsed_md, '*.md')} 个文件)")
    click.echo(f"  分块 JSON:     {paths.chunked_json} ({_count_files(paths.chunked_json, '*.json')} 个文件)")
    click.echo(f"  FAISS 索引:   {paths.faiss_index} ({_count_files(paths.faiss_index, '*.faiss')} 个文件)")
    click.echo(f"  BM25 索引:    {paths.bm25_index} ({_count_files(paths.bm25_index, '*.pkl')} 个文件)")

    click.echo("\n--- 默认配置 ---")
    config = RunConfig()
    click.echo(f"  LLM 模型:     {config.llm_model}")
    click.echo(f"  Embedding:    {config.embedding_model}")
    click.echo(f"  分块大小:     {config.chunk_size} tokens")
    click.echo(f"  路由 Top-K:   {config.route_top_k}")
    click.echo(f"  检索 Top-N:   {config.retrieve_top_n}")
    click.echo(f"  重排 Top-N:   {config.rerank_top_n}")


def _count_files(directory: Path, pattern: str) -> int:
    """统计目录下匹配模式的文件数量"""
    if not directory.exists():
        return 0
    return len(list(directory.glob(pattern)))



# ==================== 入口 ====================

if __name__ == "__main__":
    cli()