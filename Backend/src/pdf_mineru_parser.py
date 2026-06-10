# -*- coding: utf-8 -*-
"""
基于 MinerU 云端 API 的 PDF 文档解析脚本

功能：
1、调用云端 MinerU API 进行文档解析
2、API Key 通过 .env 文件中的 MINERU_KEY 获取
3、文档过大时自动切分成符合 MinerU 要求的分片后再解析
4、解析结果输出为 Markdown 格式
5、输出的 md 文件按源文件名命名
6、支持表格解析和图片 OCR 识别
7、解析结果保留源文件的页码信息
"""

import os
import sys
import time
import json
import tempfile
import zipfile
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests
from PyPDF2 import PdfReader, PdfWriter

from logger import setup_logger
from config import MINERU_POLL_INTERVAL, MINERU_POLL_MAX_RETRIES

_log = setup_logger(name="pra.pdf_parser")

# ---------- 常量 ----------
MINERU_API_HOST = "https://mineru.net"
BATCH_UPLOAD_URL = f"{MINERU_API_HOST}/api/v4/file-urls/batch"
BATCH_RESULT_URL = f"{MINERU_API_HOST}/api/v4/extract-results/batch"

# MinerU API 限制
MAX_FILE_SIZE_MB = 200       # 单文件最大 200MB
MAX_FILE_PAGES = 200         # 单文件最大 200 页（MinerU 默认只解析前 200 页）
MAX_BATCH_FILES = 200        # 单批次最大文件数


class MinerUPDFParser:
    """MinerU 云端 PDF 解析器"""

    def __init__(self, api_key: str, output_dir: Path):
        """
        初始化解析器

        Args:
            api_key: MinerU API Token
            output_dir: 解析结果输出目录
        """
        self.api_key = api_key
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        _log.info("[初始化] MinerU 解析器创建成功, API Host=%s, 输出目录=%s", MINERU_API_HOST, self.output_dir)

    # ==================== PDF 切分相关 ====================

    @staticmethod
    def get_pdf_page_count(pdf_path: Path) -> int:
        """获取 PDF 文件的页数"""
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)

    @staticmethod
    def needs_split(pdf_path: Path) -> Tuple[bool, str]:
        """
        判断 PDF 是否需要切分

        Returns:
            (是否需要切分, 原因描述)
        """
        file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
        _log.info("[文件检查] %s | 大小=%.2fMB, 限制=%dMB",
                  pdf_path.name, file_size_mb, MAX_FILE_SIZE_MB)

        if file_size_mb > MAX_FILE_SIZE_MB:
            reason = f"文件大小 {file_size_mb:.1f}MB 超过限制 {MAX_FILE_SIZE_MB}MB"
            _log.info("[文件检查] 需要切分 - %s", reason)
            return True, reason

        try:
            page_count = MinerUPDFParser.get_pdf_page_count(pdf_path)
            _log.info("[文件检查] %s | 页数=%d, 限制=%d",
                      pdf_path.name, page_count, MAX_FILE_PAGES)
        except Exception as e:
            _log.warning("[文件检查] 读取页数失败: %s, 错误=%s", pdf_path.name, e)
            return False, ""

        if page_count > MAX_FILE_PAGES:
            reason = f"页数 {page_count} 超过限制 {MAX_FILE_PAGES}"
            _log.info("[文件检查] 需要切分 - %s", reason)
            return True, reason

        _log.info("[文件检查] %s 无需切分 (大小=%.2fMB, 页数=%d)",
                  pdf_path.name, file_size_mb, page_count)
        return False, ""

    @staticmethod
    def split_pdf(pdf_path: Path, temp_dir: Path, max_pages: int = MAX_FILE_PAGES) -> List[Path]:
        """
        将 PDF 按最大页数切分为多个分片

        Args:
            pdf_path: 原始 PDF 路径
            temp_dir: 临时目录（存放分片）
            max_pages: 每个分片的最大页数

        Returns:
            切分后的 PDF 文件路径列表
        """
        start_time = time.time()
        reader = PdfReader(str(pdf_path))
        total_pages = len(reader.pages)
        total_size_mb = pdf_path.stat().st_size / (1024 * 1024)
        stem = pdf_path.stem

        _log.info("[切分开始] %s (总页数=%d, 总大小=%.2fMB, 每片最大%d页)",
                  pdf_path.name, total_pages, total_size_mb, max_pages)

        chunks = []
        for start in range(0, total_pages, max_pages):
            end = min(start + max_pages, total_pages)
            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])

            chunk_name = f"{stem}_part{len(chunks) + 1}_p{start + 1}-{end}.pdf"
            chunk_path = temp_dir / chunk_name
            with open(chunk_path, "wb") as f:
                writer.write(f)

            chunk_size_mb = chunk_path.stat().st_size / (1024 * 1024)
            _log.info("[切分] 分片 %d: %s (页 %d-%d, 大小=%.2fMB)",
                      len(chunks) + 1, chunk_name, start + 1, end, chunk_size_mb)
            chunks.append(chunk_path)

        elapsed = time.time() - start_time
        _log.info("[切分完成] %s 共 %d 个分片, 耗时=%.2fs", pdf_path.name, len(chunks), elapsed)
        return chunks

    # ==================== 文件上传 ====================

    def _request_upload_urls(self, files_info: List[dict]) -> dict:
        """
        向 MinerU 申请批量上传 URL

        Args:
            files_info: 文件信息列表，每项包含 name

        Returns:
            API 响应中的 data 字段
        """
        start_time = time.time()
        payload = {
            "files": files_info,
            "enable_formula": True,
            "enable_table": True,
            "language": "ch",
            "model_version": "pipeline",
        }

        _log.info("[API-上传URL] 请求参数: %d 个文件, enable_formula=True, enable_table=True, language=ch",
                  len(files_info))

        try:
            resp = requests.post(BATCH_UPLOAD_URL, headers=self._headers, json=payload, timeout=60)
            elapsed = time.time() - start_time
            _log.info("[API-上传URL] 响应: HTTP %d, 耗时=%.2fs", resp.status_code, elapsed)

            if elapsed > 5:
                _log.warning("[API-上传URL] 响应超时 (>5s): %.2fs", elapsed)

            resp.raise_for_status()
            result = resp.json()
        except requests.Timeout:
            elapsed = time.time() - start_time
            _log.error("[API-上传URL] 请求超时 (%.2fs)", elapsed)
            raise
        except requests.RequestException as e:
            elapsed = time.time() - start_time
            _log.error("[API-上传URL] 请求失败: %s (耗时=%.2fs)", e, elapsed)
            raise

        if result.get("code") != 0:
            _log.error("[API-上传URL] 错误: %s", result.get("msg", "未知错误"))
            raise RuntimeError(f"申请上传 URL 失败: {result.get('msg', '未知错误')}")

        batch_id = result.get("data", {}).get("batch_id", "unknown")
        _log.info("[API-上传URL] 成功, batch_id=%s, 耗时=%.2fs", batch_id, elapsed)
        return result["data"]

    def _upload_files(self, upload_urls: List[str], file_paths: List[Path]) -> int:
        """
        将文件上传到预签名 URL

        Returns:
            成功上传的文件数
        """
        total = len(file_paths)
        success = 0
        failed = 0

        for idx, (url, path) in enumerate(zip(upload_urls, file_paths)):
            start_time = time.time()
            file_size_mb = path.stat().st_size / (1024 * 1024)

            try:
                with open(path, "rb") as f:
                    resp = requests.put(url, data=f, timeout=300)

                elapsed = time.time() - start_time
                if resp.status_code in (200, 201):
                    success += 1
                    _log.info("[上传] [%d/%d] %s (%.2fMB) | HTTP %d, 耗时=%.2fs",
                              idx + 1, total, path.name, file_size_mb, resp.status_code, elapsed)
                else:
                    failed += 1
                    _log.error("[上传] [%d/%d] %s (%.2fMB) | HTTP %d, 耗时=%.2fs, 响应=%s",
                               idx + 1, total, path.name, file_size_mb, resp.status_code,
                               elapsed, resp.text[:200] if hasattr(resp, 'text') else '')
            except Exception as e:
                elapsed = time.time() - start_time
                failed += 1
                _log.error("[上传] [%d/%d] %s (%.2fMB) | 异常: %s, 耗时=%.2fs",
                           idx + 1, total, path.name, file_size_mb, e, elapsed)

        _log.info("[上传汇总] 成功 %d/%d, 失败 %d, 总计=%.2fMB",
                  success, total, failed, sum(p.stat().st_size for p in file_paths) / (1024 * 1024))
        return success

    # ==================== 结果轮询 ====================

    def _poll_batch_result(self, batch_id: str) -> List[dict]:
        """
        轮询批量解析结果直到全部完成

        Returns:
            解析结果列表，每项包含 state, file_name, full_zip_url 等
        """
        start_time = time.time()
        url = f"{BATCH_RESULT_URL}/{batch_id}"
        _log.info("[轮询开始] batch_id=%s, 超时=%ds", batch_id, MINERU_POLL_MAX_RETRIES * MINERU_POLL_INTERVAL)

        for attempt in range(1, MINERU_POLL_MAX_RETRIES + 1):
            try:
                resp = requests.get(url, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=30)
                resp.raise_for_status()
                result = resp.json()
            except Exception as e:
                _log.warning("[轮询] 第 %d 次请求失败: %s", attempt, e)
                time.sleep(MINERU_POLL_INTERVAL)
                continue

            if result.get("code") != 0:
                _log.warning("[轮询] 第 %d 次: API 异常=%s", attempt, result.get("msg", "未知"))
                time.sleep(MINERU_POLL_INTERVAL)
                continue

            extract_result = result.get("data", {}).get("extract_result", [])
            if not extract_result:
                _log.info("[轮询] 第 %d 次: 结果为空，继续等待...", attempt)
                time.sleep(MINERU_POLL_INTERVAL)
                continue

            # 统计各状态数量
            states = {}
            done_count = 0
            failed_items = []
            for item in extract_result:
                s = item.get("state", "unknown")
                states[s] = states.get(s, 0) + 1
                if s == "done":
                    done_count += 1
                elif s == "failed":
                    failed_items.append((item.get("file_name", "unknown"), item.get("err_msg", "unknown")))

            elapsed = time.time() - start_time
            _log.info("[轮询] 第 %d 次 (耗时=%.2fs): %s, done=%d/%d",
                      attempt, elapsed, states, done_count, len(extract_result))

            # 显示失败详情
            if failed_items:
                for fname, err in failed_items[:5]:  # 最多显示前5个
                    _log.error("[轮询] 失败文件: %s - %s", fname, err)

            # 全部完成（done 或 failed）
            all_finished = all(
                item.get("state") in ("done", "failed")
                for item in extract_result
            )
            if all_finished:
                total_time = time.time() - start_time
                _log.info("[轮询完成] batch_id=%s, 总耗时=%.2fs, done=%d, 失败=%d",
                          batch_id, total_time, done_count, len(failed_items))
                return extract_result

            time.sleep(MINERU_POLL_INTERVAL)

        total_time = time.time() - start_time
        _log.error("[轮询超时] batch_id=%s, 总耗时=%.2fs, 仍有 %d/%d 文件未完成",
                   batch_id, total_time,
                   len(extract_result) - done_count if 'extract_result' in locals() else 0,
                   len(extract_result) if 'extract_result' in locals() else 0)
        raise TimeoutError(f"批次 {batch_id} 轮询超时（{MINERU_POLL_MAX_RETRIES * MINERU_POLL_INTERVAL}s）")

    # ==================== 结果下载与保存 ====================

    def _download_and_save(self, extract_result: List[dict], source_name_map: Dict[str, str]):
        """
        下载解析结果 zip，结合 content_list.json 重建带页码信息的 Markdown 并保存

        对于切分文件，会将同一源文件的所有分片结果合并为一个 MD 文件。
        合并策略：收集所有分片的 content_list.json，按各自 page_idx 重建完整页码序列。

        Args:
            extract_result: 轮询返回的解析结果列表
            source_name_map: 上传文件名 -> 源文件名 的映射
        """
        _log.info("[下载] 开始处理 %d 个解析结果", len(extract_result))

        # 按源文件名分组，构建 temp storage
        source_stems: Dict[str, List[dict]] = {}  # source_name -> list of (file_name, content_list_data)
        success_count = 0
        skip_count = 0
        fail_count = 0

        for item in extract_result:
            state = item.get("state")
            file_name = item.get("file_name", "unknown")
            source_name = source_name_map.get(file_name, file_name)

            if state == "failed":
                fail_count += 1
                _log.error("[解析失败] %s - %s", source_name, item.get("err_msg", "未知错误"))
                continue

            zip_url = item.get("full_zip_url")
            if not zip_url:
                skip_count += 1
                _log.warning("[跳过] %s 没有返回下载链接", source_name)
                continue

            # 下载结果
            try:
                start_time = time.time()
                resp = requests.get(zip_url, timeout=600)
                zip_size_mb = len(resp.content) / (1024 * 1024)
                elapsed = time.time() - start_time
                _log.info("[下载] %s (%.2fMB, %.2fs)", source_name, zip_size_mb, elapsed)

                if elapsed > 30:
                    _log.warning("[下载] 耗时较长 (%.2fs)，可能是大文件", elapsed)
            except Exception as e:
                fail_count += 1
                _log.error("[下载失败] %s - %s", source_name, e)
                continue

            # 解压到临时目录
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    zip_path = tmp_path / "result.zip"
                    with open(zip_path, "wb") as f:
                        f.write(resp.content)

                    extract_dir = tmp_path / "extracted"
                    extract_dir.mkdir(exist_ok=True)
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        zf.extractall(extract_dir)

                    content_list_file = self._find_content_list_json(extract_dir)
                    content_list_data = None
                    if content_list_file is not None:
                        content_list_data = json.loads(content_list_file.read_text(encoding="utf-8"))
                        _log.info("[解析] %s 找到 content_list.json (项目数=%d)",
                                  source_name, len(content_list_data) if isinstance(content_list_data, list) else 0)

                    if content_list_data is not None:
                        if source_name not in source_stems:
                            source_stems[source_name] = []
                        source_stems[source_name].append({
                            "content_list": content_list_data,
                            "file_name": file_name,
                        })
                        success_count += 1
                        continue

                    # 降级：使用 full.md（无页码信息）
                    md_file = self._find_full_md(extract_dir)
                    if md_file is not None:
                        md_content = md_file.read_text(encoding="utf-8")
                        output_stem = Path(source_name).stem
                        output_path = self.output_dir / f"{output_stem}.md"
                        output_path.write_text(md_content, encoding="utf-8")
                        skip_count += 1
                        _log.warning("[保存] 已保存(无页码): %s (%d 字符)", output_path.name, len(md_content))
                        continue

                    fail_count += 1
                    _log.warning("[跳过] 未找到任何可用的解析结果，跳过: %s", source_name)
            except Exception as e:
                fail_count += 1
                _log.error("[解压/保存失败] %s - %s", source_name, e)

        _log.info("[下载汇总] 成功=%d, 跳过(无页码)=%d, 失败=%d",
                  success_count, skip_count, fail_count)

        # 合并同一源文件的所有分片结果
        self._save_merged_files(source_stems)

    def _save_merged_files(self, source_stems: Dict[str, List[dict]]):
        """
        保存合并后的文件

        Args:
            source_stems: 按源文件名分组的 chunks
        """
        _log.info("[合并] 开始处理 %d 个源文件的分片", len(source_stems))

        merged_count = 0
        for source_name, chunks in source_stems.items():
            output_stem = Path(source_name).stem
            output_path = self.output_dir / f"{output_stem}.md"

            try:
                if len(chunks) == 1:
                    # 单文件（未切分），直接保存
                    md_content = self._build_page_aware_md_from_data(chunks[0]["content_list"])
                    output_path.write_text(md_content, encoding="utf-8")
                    merged_count += 1
                    _log.info("[保存] %s (%d 字符, %d 个分片)",
                              output_path.name, len(md_content), len(chunks))
                else:
                    # 多分片，合并所有 content_list
                    combined = self._merge_content_lists(chunks)
                    if combined:
                        md_content = self._build_page_aware_md_from_data(combined)
                        output_path.write_text(md_content, encoding="utf-8")
                        merged_count += 1
                        _log.info("[保存] 合并 %d 个分片 -> %s (%d 字符)",
                                  len(chunks), output_path.name, len(md_content))
                    else:
                        _log.error("[合并失败] 合并结果为空: %s", source_name)
            except Exception as e:
                _log.error("[保存失败] %s - %s", source_name, e)

        _log.info("[合并汇总] 成功保存 %d 个文件", merged_count)

    @staticmethod
    def _find_full_md(extract_dir: Path) -> Optional[Path]:
        """在解压目录中递归查找 full.md"""
        for root, _, files in os.walk(extract_dir):
            for f in files:
                if f.endswith("full.md") or f == "full.md":
                    return Path(root) / f
        return None

    @staticmethod
    def _find_content_list_json(extract_dir: Path) -> Optional[Path]:
        """在解压目录中递归查找 content_list.json"""
        for root, _, files in os.walk(extract_dir):
            for f in files:
                if f.endswith("_content_list.json") or f == "content_list.json":
                    return Path(root) / f
        return None

    @staticmethod
    def _build_page_aware_md(content_list_path: Path) -> str:
        """
        基于 content_list.json 重建带页码标记的 Markdown

        content_list.json 结构示例:
        [
            {"type": "text", "text": "## 标题", "page_idx": 0, "bbox": [...]},
            {"type": "table", "text": "<table>...</table>", "page_idx": 1, "bbox": [...]},
            ...
        ]

        page_idx 从 0 开始计数，对应 PDF 第 1 页。

        Returns:
            包含 <!-- 第N页 --> 页码标记的 Markdown 字符串
        """
        content_list = json.loads(content_list_path.read_text(encoding="utf-8"))

        if not isinstance(content_list, list) or len(content_list) == 0:
            _log.warning("[MD生成] content_list.json 为空或格式异常")
            return ""

        lines = []
        prev_page = -1
        page_set = set()

        for item in content_list:
            page_idx = item.get("page_idx", -1)
            item_type = item.get("type", "")
            text = item.get("text", "")

            if not text:
                continue

            # 页码变化时插入页码标记（page_idx 从 0 开始，显示为第 page_idx+1 页）
            if page_idx != prev_page and page_idx >= 0:
                lines.append(f"\n\n<!-- 第{page_idx + 1}页 -->\n\n")
                page_set.add(page_idx)
                prev_page = page_idx

            # 表格类型：确保前后有换行便于阅读
            if item_type == "table":
                lines.append("\n" + text.strip() + "\n")
            else:
                lines.append(text)

        result = "\n".join(lines)
        # 清理多余的连续空行
        result = re.sub(r'\n{4,}', '\n\n\n', result)
        return result.strip()

    @staticmethod
    def _merge_content_lists(chunks: List[dict]) -> List[dict]:
        """
        合并同一源文件的所有 content_list.json 为一个完整列表

        关键逻辑：通过分片文件名（如 part2_p201-400）提取起始页码，
        对所有 item 的 page_idx 加上对应偏移量，确保页码连续。

        Args:
            chunks: 各分片的 content_list 数据列表

        Returns:
            合并后的完整 content_list
        """
        # 从分片文件名提取起始页码
        def get_page_offset(file_name: str) -> int:
            # 文件名格式如: 财报_part2_p201-400.pdf
            # 匹配 _p<N>- 模式
            match = re.search(r'_p(\d+)-', file_name)
            if match:
                return int(match.group(1)) - 1  # page_idx 从 0 开始
            return 0

        start_time = time.time()
        all_items = []

        for chunk in chunks:
            offset = get_page_offset(chunk["file_name"])
            chunk_size = len(chunk["content_list"])
            _log.info("[合并] 分片 %s (page_idx 偏移=%d, 项目数=%d)",
                      chunk["file_name"], offset, chunk_size)

            for item in chunk["content_list"]:
                # 调整页码：page_idx + 起始页码偏移
                adjusted_item = dict(item)
                page_idx = adjusted_item.get("page_idx", -1)
                if page_idx >= 0:
                    adjusted_item["page_idx"] = page_idx + offset
                all_items.append(adjusted_item)

        # 按 page_idx 排序
        all_items.sort(key=lambda x: x.get("page_idx", 0))

        # 统计页码范围
        if all_items:
            min_page = min(item.get("page_idx", 0) for item in all_items)
            max_page = max(item.get("page_idx", 0) for item in all_items)
            elapsed = time.time() - start_time
            _log.info("[合并完成] 共 %d 个项目, 页码范围=[%d, %d], 耗时=%.2fs",
                      len(all_items), min_page, max_page, elapsed)
        else:
            _log.warning("[合并完成] 结果为空")

        return all_items

    @staticmethod
    def _build_page_aware_md_from_data(content_list: List[dict]) -> str:
        """
        基于 content_list.json 数据重建带页码标记的 Markdown

        Args:
            content_list: content_list.json 解析后的列表数据

        Returns:
            包含 <!-- 第N页 --> 页码标记的 Markdown 字符串
        """
        if not isinstance(content_list, list) or len(content_list) == 0:
            _log.warning("[MD生成] content_list 为空或格式异常")
            return ""

        start_time = time.time()
        lines = []
        prev_page = -1
        type_counts = {}
        page_set = set()

        for item in content_list:
            page_idx = item.get("page_idx", -1)
            item_type = item.get("type", "")
            text = item.get("text", "")

            if not text:
                continue

            type_counts[item_type] = type_counts.get(item_type, 0) + 1

            # 页码变化时插入页码标记（page_idx 从 0 开始，显示为第 page_idx+1 页）
            if page_idx != prev_page and page_idx >= 0:
                lines.append(f"\n\n<!-- 第{page_idx + 1}页 -->\n\n")
                page_set.add(page_idx)
                prev_page = page_idx

            # 表格类型：确保前后有换行便于阅读
            if item_type == "table":
                lines.append("\n" + text.strip() + "\n")
            else:
                lines.append(text)

        result = "\n".join(lines)
        # 清理多余的连续空行
        result = re.sub(r'\n{4,}', '\n\n\n', result)

        elapsed = time.time() - start_time
        _log.info("[MD生成] %d 个项目 -> %d 字符, %d 页, 类型分布=%s, 耗时=%.2fs",
                  len(content_list), len(result), len(page_set),
                  json.dumps(type_counts), elapsed)
        return result.strip()

    # ==================== 主流程 ====================

    def parse_pdfs(self, pdf_paths: List[Path]):
        """
        解析所有 PDF 文件

        Args:
            pdf_paths: PDF 文件路径列表
        """
        overall_start = time.time()

        if not pdf_paths:
            _log.warning("没有需要处理的 PDF 文件")
            return

        _log.info("=" * 70)
        _log.info("开始处理 %d 个 PDF 文件", len(pdf_paths))
        _log.info("=" * 70)

        # ==================== 第一阶段：文件检查与切分 ====================
        phase1_start = time.time()
        _log.info("[阶段1/3] 文件检查与切分")

        all_upload_files: List[Path] = []          # 实际上传的文件路径
        all_upload_infos: List[dict] = []          # API 请求中的文件信息
        source_name_map: Dict[str, str] = {}       # 上传文件名 -> 源文件名
        temp_files_to_cleanup: List[Path] = []     # 需要清理的临时文件

        for pdf_path in pdf_paths:
            needs, reason = self.needs_split(pdf_path)

            if needs:
                _log.info("[切分判断] %s 需要切分: %s", pdf_path.name, reason)
                split_dir = pdf_path.parent / ".temp_splits"
                split_dir.mkdir(parents=True, exist_ok=True)
                chunks = self.split_pdf(pdf_path, split_dir)
                for chunk in chunks:
                    # 上传文件名用切分后的名字
                    upload_name = chunk.name
                    all_upload_files.append(chunk)
                    all_upload_infos.append({
                        "name": upload_name,
                        "is_ocr": True,
                    })
                    source_name_map[upload_name] = pdf_path.name
                    temp_files_to_cleanup.append(chunk)
            else:
                all_upload_files.append(pdf_path)
                all_upload_infos.append({
                    "name": pdf_path.name,
                    "is_ocr": True,
                })
                source_name_map[pdf_path.name] = pdf_path.name

        _log.info("[阶段1完成] 共 %d 个原始文件, 切分后总计 %d 个上传文件",
                  len(pdf_paths), len(all_upload_files))
        phase1_elapsed = time.time() - phase1_start
        _log.info("[阶段1耗时] %.2fs", phase1_elapsed)

        # ==================== 第二阶段：上传并解析 ====================
        phase2_start = time.time()
        _log.info("[阶段2/3] 上传文件并等待解析")

        # 按批次处理（每批最多 MAX_BATCH_FILES 个）
        total = len(all_upload_files)
        batch_count = (total + MAX_BATCH_FILES - 1) // MAX_BATCH_FILES
        processed = 0
        extract_result = []

        for batch_num in range(batch_count):
            batch_start = batch_num * MAX_BATCH_FILES
            batch_end = min(batch_start + MAX_BATCH_FILES, total)
            batch_files = all_upload_files[batch_start:batch_end]
            batch_infos = all_upload_infos[batch_start:batch_end]

            _log.info("-" * 50)
            _log.info("[批次 %d/%d] %d 个文件",
                      batch_num + 1, batch_count, len(batch_files))

            # 申请上传 URL
            data = self._request_upload_urls(batch_infos)
            batch_id = data["batch_id"]
            upload_urls = data["file_urls"]

            if len(upload_urls) != len(batch_files):
                # 清理临时文件
                self._cleanup_temp_files(temp_files_to_cleanup)
                raise RuntimeError(
                    f"上传 URL 数量 ({len(upload_urls)}) 与文件数量 ({len(batch_files)}) 不匹配"
                )

            # 上传文件
            success_count = self._upload_files(upload_urls, batch_files)
            if success_count == 0:
                # 清理临时文件
                self._cleanup_temp_files(temp_files_to_cleanup)
                raise RuntimeError("所有文件上传失败")

            # 等待结果
            batch_result = self._poll_batch_result(batch_id)
            extract_result.extend(batch_result)
            processed += len(batch_files)
            _log.info("[批次进度] 已处理 %d/%d 个文件", processed, total)

        _log.info("[阶段2完成] 所有文件解析完成")
        phase2_elapsed = time.time() - phase2_start
        _log.info("[阶段2耗时] %.2fs", phase2_elapsed)

        # ==================== 第三阶段：下载并保存 ====================
        phase3_start = time.time()
        _log.info("[阶段3/3] 下载解析结果并保存")

        self._download_and_save(extract_result, source_name_map)

        phase3_elapsed = time.time() - phase3_start
        _log.info("[阶段3耗时] %.2fs", phase3_elapsed)

        # 清理临时文件
        self._cleanup_temp_files(temp_files_to_cleanup)

        overall_elapsed = time.time() - overall_start
        _log.info("=" * 70)
        _log.info("全部完成!")
        _log.info("  原始文件: %d 个", len(pdf_paths))
        _log.info("  最终文件: %d 个", len(list(self.output_dir.glob("*.md"))))
        _log.info("  总耗时: %.2fs (%.2f分钟)", overall_elapsed, overall_elapsed / 60)
        _log.info("  输出目录: %s", self.output_dir)
        _log.info("=" * 70)

    @staticmethod
    def _cleanup_temp_files(temp_files: List[Path]):
        """清理临时文件"""
        if not temp_files:
            return
        _log.info("[清理] 开始删除 %d 个临时切片文件", len(temp_files))
        for temp_file in temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                    _log.info("[清理] 已删除: %s", temp_file.name)
            except Exception as e:
                _log.warning("[清理] 删除失败: %s - %s", temp_file.name, e)
        # 尝试删除空的临时目录
        temp_dir = temp_files[0].parent if temp_files else None
        if temp_dir and temp_dir.name == ".temp_splits" and temp_dir.exists():
            try:
                if not any(temp_dir.iterdir()):
                    temp_dir.rmdir()
                    _log.info("[清理] 已删除空临时目录: %s", temp_dir)
            except Exception as e:
                _log.warning("[清理] 删除临时目录失败: %s - %s", temp_dir, e)
