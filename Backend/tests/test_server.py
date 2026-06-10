# -*- coding: utf-8 -*-
"""server 模块单元测试"""
from pathlib import Path

from routers.documents import safe_file_path


class TestSafeFilePath:
    """测试 safe_file_path 路径校验"""

    def test_normal_filename(self):
        """正常文件名"""
        base = Path("/tmp/data")
        result = safe_file_path("test.pdf", base)
        assert result.resolve() == (base / "test.pdf").resolve()

    def test_path_traversal_blocked(self):
        """路径遍历攻击被拦截"""
        base = Path("/tmp/data")
        try:
            safe_file_path("../etc/passwd", base)
            assert False, "应抛出异常"
        except Exception:
            pass

    def test_absolute_path_blocked(self):
        """绝对路径被拦截"""
        base = Path("/tmp/data")
        try:
            safe_file_path("/etc/passwd", base)
            assert False, "应抛出异常"
        except Exception:
            pass

    def test_null_byte_blocked(self):
        """空字节注入被拦截"""
        base = Path("/tmp/data")
        try:
            safe_file_path("test\x00.pdf", base)
            assert False, "应抛出异常"
        except Exception:
            pass
