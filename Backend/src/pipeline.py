# -*- coding: utf-8 -*-
"""
Pipeline 中枢调度器
串联 PDF 解析、文本分块、索引构建、问答处理的完整流程。
通过 RunConfig 灵活控制各阶段参数，支持单步执行和全流程一键运行。
"""

import json
import sys
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass

from config import (
    RunConfig,
    PipelinePaths,
)
from logger import setup_logger

_log = setup_logger(name="src.pipeline")


class Pipeline:
    """
    RAG 全流程调度器
    串联以下阶段:
      1. PDF 解析       -> pdf_mineru_parser.py
      2. 文本分块        -> text_chunker.py
      3. 索引构建        -> ingestion.py (BM25 + FAISS)
      4. 元信息注册      -> metadata.py
      5. 问答处理        -> questions_processing.py
    """

    def __init__(
        self,
        run_config: Optional[RunConfig] = None,
        paths: Optional[PipelinePaths] = None,
    ):
        """
        初始化 Pipeline

        Args:
            run_config: 运行参数配置，None 则使用默认配置
            paths:     路径配置，None 则使用默认路径
        """
        self.config = run_config or RunConfig()
        self.paths = paths or PipelinePaths()
        self.paths.ensure_dirs()
        self._question_processor = None

    @property
    def question_processor(self):
        """懒加载并缓存 QuestionProcessor 实例，避免每次请求重新加载索引"""
        if self._question_processor is None:
            from questions_processing import QuestionProcessor
            self._question_processor = QuestionProcessor(
                chunked_json_dir=self.paths.chunked_json,
                faiss_dir=self.paths.faiss_index,
                bm25_dir=self.paths.bm25_index,
                embedding_model=self.config.embedding_model,
                llm_model=self.config.llm_model,
            )
        return self._question_processor

    # ==================== 阶段1: PDF 解析 ====================

    def parse_pdfs(self, pdf_dir: Optional[Path] = None, pdf_files: Optional[List[Path]] = None):
        """
        解析 PDF 文件为带页码标记的 Markdown

        Args:
            pdf_dir: PDF 文件目录，默认使用配置中的 pdf_data
            pdf_files: 可选，指定要处理的 PDF 文件列表，如果不指定则处理整个目录
        """
        from pdf_mineru_parser import MinerUPDFParser
        from config import MINERU_KEY

        if pdf_files is not None:
            # 使用指定的文件列表
            if not pdf_files:
                _log.error("未提供 PDF 文件")
                return
            # 检查文件是否都存在
            valid_files = []
            for f in pdf_files:
                if f.exists():
                    valid_files.append(f)
                else:
                    _log.warning("文件不存在，跳过: %s", f)
            pdf_files = valid_files
        else:
            # 使用目录下所有文件
            pdf_dir = pdf_dir or self.paths.pdf_data
            if not pdf_dir.exists():
                _log.error("PDF 目录不存在: %s", pdf_dir)
                return
            pdf_files = sorted(pdf_dir.glob("*.pdf"))
            if not pdf_files:
                _log.error("未在 %s 中找到 PDF 文件", pdf_dir)
                return

        api_key = MINERU_KEY
        if not api_key:
            _log.error("未在 .env 文件中找到 MINERU_KEY，请在 Backend/.env 中配置")
            return

        _log.info("=" * 60)
        _log.info("阶段1: PDF 解析")
        _log.info("处理 %d 个 PDF 文件", len(pdf_files))
        for f in pdf_files:
            _log.info("  - %s", f.name)
        _log.info("=" * 60)

        parser = MinerUPDFParser(api_key=api_key, output_dir=self.paths.parsed_md)
        parser.parse_pdfs(pdf_files)

        _log.info("PDF 解析完成，结果保存在: %s", self.paths.parsed_md)

    def parse_single_pdf(self, pdf_path: Path):
        """
        增量解析单个 PDF 文件

        Args:
            pdf_path: PDF 文件路径
        """
        self.parse_pdfs(pdf_files=[pdf_path])

    # ==================== 阶段2: 文本分块 ====================

    def chunk_reports(self, md_files: Optional[List[Path]] = None):
        """将 Markdown 文件按页码和 token 进行分块，输出为 JSON

        Args:
            md_files: 可选，指定要处理的 Markdown 文件列表，如果不指定则处理整个目录

        Raises:
            ValueError: 没有可处理的 Markdown 文件
        """
        from text_chunker import TextChunker

        if md_files is not None:
            if not md_files:
                raise ValueError("未提供 Markdown 文件")
            valid_files = []
            for f in md_files:
                if f.exists():
                    valid_files.append(f)
                else:
                    _log.warning("文件不存在，跳过: %s", f)
            md_files = valid_files
        else:
            md_dir = self.paths.parsed_md
            if not md_dir.exists() or not list(md_dir.glob("*.md")):
                raise ValueError("未找到解析后的 MD 文件，请先执行 PDF 解析")
            md_files = sorted(md_dir.glob("*.md"))

        if not md_files:
            raise ValueError("没有可处理的 Markdown 文件")

        _log.info("=" * 60)
        _log.info("阶段2: 文本分块")
        _log.info("处理 %d 个文件", len(md_files))
        _log.info("=" * 60)

        chunker = TextChunker(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )

        output_dir = self.paths.chunked_json
        output_dir.mkdir(parents=True, exist_ok=True)

        success_count = 0
        fail_count = 0
        for md_path in md_files:
            _log.info("处理: %s", md_path.name)
            try:
                chunks = chunker.chunk_file(md_path)
                result = {
                    "source_file": md_path.name,
                    "chunk_count": len(chunks),
                    "chunks": chunks,
                }
                output_path = output_dir / f"{md_path.stem}.json"
                output_path.write_text(
                    json.dumps(result, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                _log.info("  -> %s (%d 个 chunk)", output_path.name, len(chunks))
                success_count += 1
            except Exception as e:
                fail_count += 1
                _log.error("  -> 分块失败: %s, 错误: %s", md_path.name, e)

        _log.info("文本分块完成，成功 %d 个，失败 %d 个，结果保存在: %s",
                   success_count, fail_count, self.paths.chunked_json)

    def chunk_single_report(self, md_path: Path):
        """
        增量分块单个 Markdown 文件

        Args:
            md_path: Markdown 文件路径
        """
        self.chunk_reports(md_files=[md_path])

    # ==================== 阶段3: 索引构建 ====================

    def build_indices(self, json_files: Optional[List[Path]] = None):
        """构建 BM25 和 FAISS 索引

        Args:
            json_files: 可选，指定要处理的 JSON 文件列表，如果不指定则处理整个目录
        """
        from ingestion import BM25Ingestor, VectorDBIngestor

        if json_files is not None:
            # 使用指定的文件列表
            if not json_files:
                _log.error("未提供 JSON 文件")
                return
            # 检查文件是否都存在
            valid_files = []
            for f in json_files:
                if f.exists():
                    valid_files.append(f)
                else:
                    _log.warning("文件不存在，跳过: %s", f)
            json_files = valid_files
        else:
            # 使用目录下所有文件
            input_dir = self.paths.chunked_json
            if not input_dir.exists() or not list(input_dir.glob("*.json")):
                _log.error("未找到分块后的 JSON 文件，请先执行 chunk_reports")
                return
            json_files = sorted(input_dir.glob("*.json"))

        _log.info("=" * 60)
        _log.info("阶段3: 索引构建")
        _log.info("处理 %d 个文件", len(json_files))
        _log.info("=" * 60)

        # BM25 索引
        _log.info("构建 BM25 索引...")
        bm25 = BM25Ingestor()
        for json_path in json_files:
            _log.info("构建 BM25 索引: %s", json_path.name)
            bm25.process_single(json_path, self.paths.bm25_index)
        _log.info("BM25 索引构建完成: %s", self.paths.bm25_index)

        # FAISS 向量库
        _log.info("构建 FAISS 向量库...")
        vector_db = VectorDBIngestor(embedding_model=self.config.embedding_model)
        for json_path in json_files:
            _log.info("构建 FAISS 向量库: %s", json_path.name)
            vector_db.process_single(json_path, self.paths.faiss_index)
        _log.info("FAISS 向量库构建完成: %s", self.paths.faiss_index)

        # 关键字提取与 metadata 更新
        _log.info("提取文档关键字标签...")
        from ingestion import KeywordIngestor
        keyword_ingestor = KeywordIngestor(use_llm=self.config.keyword_use_llm)
        for json_path in json_files:
            keyword_ingestor.process_single(json_path)
        _log.info("文档关键字提取完成")

    def build_single_index(self, json_path: Path):
        """
        增量为单个文档构建索引

        Args:
            json_path: 分块后的 JSON 文件路径
        """
        self.build_indices(json_files=[json_path])

    # ==================== 阶段4: 元信息注册 ====================

    def register_metadata(
        self,
        company_name: str = "",
        report_type: str = "",
        report_year: str = "",
        pdf_files: Optional[List[Path]] = None,
    ):
        """
        注册 PDF 元信息到 metadata.csv

        Args:
            company_name: 公司名称（为空则从文件名推断）
            report_type:  报告类型
            report_year:  报告年份
            pdf_files:    可选，指定要处理的 PDF 文件列表，如果不指定则处理整个目录
        """
        from metadata import MetadataManager

        if pdf_files is not None:
            # 使用指定的文件列表
            if not pdf_files:
                _log.error("未提供 PDF 文件")
                return
            # 检查文件是否都存在
            valid_files = []
            for f in pdf_files:
                if f.exists():
                    valid_files.append(f)
                else:
                    _log.warning("文件不存在，跳过: %s", f)
            pdf_files = valid_files
        else:
            # 使用目录下所有文件
            pdf_dir = self.paths.pdf_data
            if not pdf_dir.exists():
                _log.error("PDF 目录不存在: %s", pdf_dir)
                return
            pdf_files = sorted(pdf_dir.glob("*.pdf"))

        _log.info("=" * 60)
        _log.info("阶段4: 元信息注册")
        _log.info("处理 %d 个文件", len(pdf_files))
        _log.info("=" * 60)

        manager = MetadataManager()

        for pdf_path in pdf_files:
            name = pdf_path.name
            # 从文件名推断公司名（硬编码回退，KeywordIngestor 会用 LLM 覆盖）
            if not company_name:
                from keyword_extractor import KeywordExtractor
                company = KeywordExtractor._infer_company_name(name) or "未知"
            else:
                company = company_name

            # 从文件名推断报告类型（硬编码回退）
            if not report_type:
                from keyword_extractor import KeywordExtractor
                rtype = KeywordExtractor._infer_report_type(name) or "其他"
            else:
                rtype = report_type

            manager.register_pdf(
                pdf_path,
                company_name=company,
                report_type=rtype,
                report_year=report_year,
            )
            _log.info("已注册: %s -> %s [%s]", pdf_path.name, company, rtype)

        # 输出统计
        _log.info("共注册 %d 个文档", len(manager.list_all()))

    def register_single_metadata(
        self,
        pdf_path: Path,
        company_name: str = "",
        report_type: str = "",
        report_year: str = "",
    ):
        """
        增量注册单个文档的元信息，并尝试提取关键字

        Args:
            pdf_path: PDF 文件路径
            company_name: 公司名称（为空则从文件名推断）
            report_type:  报告类型
            report_year:  报告年份
        """
        self.register_metadata(
            company_name=company_name,
            report_type=report_type,
            report_year=report_year,
            pdf_files=[pdf_path],
        )

        # 如果已有 chunked JSON，则提取关键字和元信息
        json_path = self.paths.chunked_json / f"{pdf_path.stem}.json"
        if json_path.exists():
            from ingestion import KeywordIngestor
            keyword_ingestor = KeywordIngestor(use_llm=self.config.keyword_use_llm)
            keyword_ingestor.process_single(json_path)
            _log.info("已提取关键字: %s", pdf_path.name)

    # ==================== 阶段5: 问答处理 ====================

    def answer_question(self, question: str, prompt_type: str = "number") -> Dict:
        """
        对单个问题进行 RAG 问答

        Args:
            question:    用户问题
            prompt_type: 答案类型 number/name/boolean/list

        Returns:
            RAG 问答结果字典
        """
        _log.info("=" * 60)
        _log.info("阶段5: 问答处理（单个问题）")
        _log.info("=" * 60)

        processor = self.question_processor

        result = processor.answer(
            question=question,
            prompt_type=prompt_type,
            route_top_k=self.config.route_top_k,
            retrieve_top_n=self.config.retrieve_top_n,
            rerank_batch_size=self.config.rerank_batch_size,
            rerank_top_n=self.config.rerank_top_n,
            llm_weight=self.config.llm_weight,
        )

        return result

    def batch_answer(
        self,
        questions_file: Optional[Path] = None,
        output_file: Optional[Path] = None,
    ) -> List[Dict]:
        """
        批量处理问题文件

        问题文件为 JSON 数组格式:
        [
            {"question": "中芯国际2025年Q1营收是多少？", "prompt_type": "number"},
            ...
        ]

        Args:
            questions_file: 问题 JSON 文件路径
            output_file:    答案输出 JSON 文件路径

        Returns:
            所有问题的答案列表
        """
        from question_rewriter import QuestionRewriter
        from keyword_extractor import KeywordExtractor

        # 确定输入文件路径
        if questions_file is None:
            if self.config.questions_file:
                questions_file = Path(self.config.questions_file)
            else:
                questions_file = self.paths.project_root / "questions.json"

        if not questions_file.exists():
            _log.error("问题文件不存在: %s", questions_file)
            return []

        _log.info("=" * 60)
        _log.info("阶段5: 批量问答处理")
        _log.info("问题文件: %s", questions_file)
        _log.info("=" * 60)

        # 加载问题
        with open(questions_file, "r", encoding="utf-8") as f:
            questions = json.load(f)

        _log.info("共 %d 个问题", len(questions))

        # 初始化各组件
        processor = self.question_processor
        rewriter = QuestionRewriter()
        extractor = KeywordExtractor(use_llm=False)

        results = []

        for i, q_item in enumerate(questions):
            question_text = q_item["question"]
            prompt_type = q_item.get("prompt_type", "number")

            _log.info("[%d/%d] 处理: %s", i + 1, len(questions), question_text[:60])

            # 提取关键字（用于日志记录，不影响核心流程）
            keywords = extractor.extract_keywords_only(question_text)
            _log.info("  关键字: %s", keywords)

            # 判断是否为比较类问题，若是则拆解
            if rewriter.needs_rewrite(question_text):
                sub_questions = rewriter.rewrite(question_text)
                _log.info("  比较类问题，已拆解为 %d 个子问题", len(sub_questions))

                # 对每个子问题分别回答（简化处理：取第一个问题类型）
                sub_answers = []
                for sq in sub_questions:
                    sub_result = processor.answer(
                        question=sq["question"],
                        prompt_type=prompt_type,
                        route_top_k=self.config.route_top_k,
                        retrieve_top_n=self.config.retrieve_top_n,
                        rerank_batch_size=self.config.rerank_batch_size,
                        rerank_top_n=self.config.rerank_top_n,
                        llm_weight=self.config.llm_weight,
                    )
                    sub_answers.append({
                        "company": sq["company_name"],
                        "answer": sub_result["final_answer"],
                        "pages": sub_result["relevant_pages"],
                    })

                results.append({
                    "question": question_text,
                    "prompt_type": prompt_type,
                    "sub_answers": sub_answers,
                    "keywords": keywords,
                })
                _log.info("[%d] %s", i + 1, question_text)
                _log.info("  答案（拆解）: %s", sub_answers)
            else:
                # 普通问题，直接回答
                result = processor.answer(
                    question=question_text,
                    prompt_type=prompt_type,
                    route_top_k=self.config.route_top_k,
                    retrieve_top_n=self.config.retrieve_top_n,
                    rerank_batch_size=self.config.rerank_batch_size,
                    rerank_top_n=self.config.rerank_top_n,
                    llm_weight=self.config.llm_weight,
                )
                results.append({
                    "question": question_text,
                    "prompt_type": prompt_type,
                    "final_answer": result["final_answer"],
                    "reasoning_summary": result["reasoning_summary"],
                    "relevant_pages": result["relevant_pages"],
                    "keywords": keywords,
                })
                _log.info("[%d] %s", i + 1, question_text)
                _log.info("  答案: %s", result['final_answer'])
                _log.info("  推理摘要: %s", result['reasoning_summary'])
                _log.info("  引用页码: %s", result['relevant_pages'])
                _log.info("  上下文来源: %s", [d['source'] for d in result['context_docs']])

        # 保存结果
        if output_file is None:
            if self.config.answers_file:
                output_file = Path(self.config.answers_file)
            else:
                output_file = self.paths.project_root / "answers.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        _log.info("答案已保存到: %s (%d 条)", output_file, len(results))
        return results

    # ==================== 交互问答 ====================

    def _batch_answer_interactive(self):
        """从终端逐条读取用户输入的问题并返回答案"""
        from question_rewriter import QuestionRewriter
        from keyword_extractor import KeywordExtractor

        _log.info("=" * 60)
        _log.info("阶段5: 交互问答模式（输入 q 退出）")
        _log.info("=" * 60)

        processor = self.question_processor
        rewriter = QuestionRewriter()
        extractor = KeywordExtractor(use_llm=False)

        while True:
            try:
                user_input = input("\n[?] 请输入问题（输入 q 退出）:\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                _log.info("交互式问答退出")
                return

            if not user_input:
                continue
            if user_input.lower() in ("q", "quit", "exit"):
                _log.info("交互式问答退出")
                return

            prompt_type = "number"
            # 解析 :number/:name/:boolean/:list 后缀
            for ttype in ["name", "boolean", "list", "number"]:
                if user_input.lower().endswith(f":{ttype}"):
                    user_input = user_input[: -len(f":{ttype}")].strip()
                    prompt_type = ttype
                    break

            _log.info("处理问题: %s", user_input)

            # 提取关键字
            keywords = extractor.extract_keywords_only(user_input)
            _log.info("  关键字: %s", keywords)

            # 判断是否为比较类问题
            if rewriter.needs_rewrite(user_input):
                sub_questions = rewriter.rewrite(user_input)
                _log.info("  比较类问题，已拆解为 %d 个子问题", len(sub_questions))

                sub_answers = []
                for sq in sub_questions:
                    sub_result = processor.answer(
                        question=sq["question"],
                        prompt_type=prompt_type,
                        route_top_k=self.config.route_top_k,
                        retrieve_top_n=self.config.retrieve_top_n,
                        rerank_batch_size=self.config.rerank_batch_size,
                        rerank_top_n=self.config.rerank_top_n,
                        llm_weight=self.config.llm_weight,
                    )
                    sub_answers.append({
                        "company": sq["company_name"],
                        "answer": sub_result["final_answer"],
                        "pages": sub_result["relevant_pages"],
                    })

                _log.info("[%s]", user_input)
                _log.info("  答案（拆解）: %s", sub_answers)
            else:
                result = processor.answer(
                    question=user_input,
                    prompt_type=prompt_type,
                    route_top_k=self.config.route_top_k,
                    retrieve_top_n=self.config.retrieve_top_n,
                    rerank_batch_size=self.config.rerank_batch_size,
                    rerank_top_n=self.config.rerank_top_n,
                    llm_weight=self.config.llm_weight,
                )
                _log.info("[%s]", user_input)
                _log.info("  答案: %s", result['final_answer'])
                _log.info("  推理摘要: %s", result['reasoning_summary'])
                _log.info("  引用页码: %s", result['relevant_pages'])
                _log.info("  上下文来源: %s", [d['source'] for d in result['context_docs']])


    # ==================== 一键全流程 ====================

    def run_full_pipeline(
        self,
        skip_parse: bool = False,
        skip_chunk: bool = False,
        skip_index: bool = False,
        skip_metadata: bool = False,
        questions_file: Optional[Path] = None,
        interactive: bool = False,
    ):
        """
        一键执行完整 RAG 流程

        Args:
            skip_parse:      跳过 PDF 解析（如果已有 parsed_md）
            skip_chunk:      跳过文本分块（如果已有 chunked_json）
            skip_index:      跳过索引构建（如果已有 faiss_index/bm25_index）
            skip_metadata:   跳过元信息注册（如果已有元信息数据）
            questions_file:  问题文件路径（可选）
            interactive:     是否在终端逐条输入问题
        """
        _log.info("=" * 60)
        _log.info("开始执行全流程 RAG Pipeline")
        _log.info("=" * 60)

        # 阶段4: 元信息注册（可选）
        if not skip_metadata:
            self.register_metadata()
        else:
            _log.info("跳过元信息注册阶段")

        # 阶段1: PDF 解析
        if not skip_parse:
            self.parse_pdfs()
        else:
            _log.info("跳过 PDF 解析阶段")

        # 阶段2: 分块
        if not skip_chunk:
            self.chunk_reports()
        else:
            _log.info("跳过文本分块阶段")

        # 阶段3: 索引构建
        if not skip_index:
            self.build_indices()
        else:
            _log.info("跳过索引构建阶段")

        # 阶段5: 问答
        if interactive:
            self._batch_answer_interactive()
        elif questions_file:
            self.batch_answer(questions_file=questions_file)

        _log.info("=" * 60)
        _log.info("全流程执行完毕!")
        _log.info("=" * 60)

