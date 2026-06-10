# -*- coding: utf-8 -*-
"""metadata 模块单元测试"""
import tempfile
from pathlib import Path

from metadata import MetadataManager


class TestMetadataManager:
    """测试 MetadataManager"""

    def _make_manager(self, tmp_dir):
        """创建使用临时目录的 manager"""
        mgr = MetadataManager(metadata_path=Path(tmp_dir) / "metadata.csv")
        return mgr

    def test_register_pdf_and_get(self):
        """注册单个 PDF 并查询"""
        with tempfile.TemporaryDirectory() as tmp:
            # 创建一个临时 PDF 文件
            pdf_dir = Path(tmp) / "pdfs"
            pdf_dir.mkdir()
            pdf_path = pdf_dir / "test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake content")

            mgr = self._make_manager(tmp)
            sha1 = mgr.register_pdf(pdf_path, company_name="测试公司", report_type="年报", report_year="2024")

            record = mgr.get_by_file_name("test.pdf")
            assert record is not None
            assert record["company_name"] == "测试公司"
            assert record["sha1"] == sha1

    def test_dedup_by_sha1(self):
        """SHA-1 去重"""
        with tempfile.TemporaryDirectory() as tmp:
            pdf_dir = Path(tmp) / "pdfs"
            pdf_dir.mkdir()
            pdf_path = pdf_dir / "test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake content")

            mgr = self._make_manager(tmp)
            sha1_1 = mgr.register_pdf(pdf_path, company_name="公司A")
            sha1_2 = mgr.register_pdf(pdf_path, company_name="公司A")
            # 相同文件应返回相同 sha1，且只保留一条记录
            assert sha1_1 == sha1_2
            assert len(mgr._records) == 1

    def test_get_by_file_name_not_found(self):
        """查询不存在的文件"""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._make_manager(tmp)
            result = mgr.get_by_file_name("nonexistent.pdf")
            assert result is None

    def test_get_company_names(self):
        """获取公司名列表"""
        with tempfile.TemporaryDirectory() as tmp:
            pdf_dir = Path(tmp) / "pdfs"
            pdf_dir.mkdir()
            pdf1 = pdf_dir / "a.pdf"
            pdf2 = pdf_dir / "b.pdf"
            pdf1.write_bytes(b"%PDF-1.4 content A")
            pdf2.write_bytes(b"%PDF-1.4 content B")

            mgr = self._make_manager(tmp)
            mgr.register_pdf(pdf1, company_name="公司A")
            mgr.register_pdf(pdf2, company_name="公司B")

            names = mgr.get_company_names()
            assert "公司A" in names
            assert "公司B" in names
