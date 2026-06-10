# -*- coding: utf-8 -*-
"""
元信息管理
为每个源文档生成唯一标识，记录公司名、报告类型、关键字标签等元信息。
使用 SQLite 存储，支持并发安全读写。
"""

import csv
import hashlib
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from config import PDF_DATA_DIR, PARSED_MD_DIR, CHUNKED_JSON_DIR, FAISS_INDEX_DIR, BM25_INDEX_DIR, METADATA_FILE, METADATA_DB
from logger import setup_logger

_log = setup_logger(name="pra.metadata")

# SQLite 数据库路径（位于 src 目录下）
_METADATA_DB = METADATA_DB

# 建表 SQL
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    sha256 TEXT PRIMARY KEY,
    file_name TEXT NOT NULL DEFAULT '',
    company_name TEXT NOT NULL DEFAULT '',
    report_type TEXT NOT NULL DEFAULT '',
    report_year TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'registered'
)
"""

# 旧表迁移 SQL（sha1 列名 -> sha256）
_MIGRATE_SHA1_TO_SHA256_SQL = [
    "ALTER TABLE metadata RENAME COLUMN sha1 TO sha256",
]


class MetadataManager:
    """源文档元信息管理器（SQLite 存储）"""

    def __init__(self, metadata_path: Optional[Path] = None):
        """
        初始化元信息管理器

        Args:
            metadata_path: 原始 metadata.csv 文件路径（仅用于自动迁移），默认在项目根目录下
        """
        self._csv_path = Path(metadata_path) if metadata_path else METADATA_FILE
        self._db_path = _METADATA_DB
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()

        # 自动迁移旧表 sha1 列名为 sha256
        self._migrate_sha1_column()

        # 自动迁移 CSV 数据到 SQLite（仅当 CSV 存在且 SQLite 为空时）
        self._migrate_from_csv()

    def _migrate_sha1_column(self):
        """若表中存在 sha1 列但不存在 sha256 列，执行列名迁移"""
        try:
            columns = [row[1] for row in self._conn.execute("PRAGMA table_info(metadata)").fetchall()]
            if "sha1" in columns and "sha256" not in columns:
                _log.info("[迁移] 检测到旧表 sha1 列，开始迁移为 sha256...")
                for sql in _MIGRATE_SHA1_TO_SHA256_SQL:
                    self._conn.execute(sql)
                self._conn.commit()
                _log.info("[迁移] sha1 列已迁移为 sha256")
        except Exception as e:
            _log.warning("[迁移] sha1 -> sha256 列迁移失败: %s", e)

    def _migrate_from_csv(self):
        """若 CSV 存在且 SQLite 为空，自动迁移数据"""
        if not self._csv_path.exists():
            return

        # 检查 SQLite 是否已有数据
        count = self._conn.execute("SELECT COUNT(*) FROM metadata").fetchone()[0]
        if count > 0:
            return

        _log.info("[迁移] 检测到 metadata.csv，开始迁移到 SQLite...")
        with open(self._csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # 兼容 CSV 中 sha1 和 sha256 两种列名
                sha256 = row.get("sha256", "").strip() or row.get("sha1", "").strip()
                if sha256:
                    rows.append((
                        sha256,
                        row.get("file_name", "").strip(),
                        row.get("company_name", "").strip(),
                        row.get("report_type", "").strip(),
                        row.get("report_year", "").strip(),
                        row.get("keywords", "").strip(),
                        row.get("status", "registered").strip(),
                    ))
            if rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO metadata (sha256, file_name, company_name, report_type, report_year, keywords, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                self._conn.commit()
                _log.info("[迁移] 已迁移 %d 条记录到 SQLite", len(rows))

        # 迁移完成后重命名 CSV 为备份
        backup_path = self._csv_path.with_suffix(".csv.bak")
        self._csv_path.rename(backup_path)
        _log.info("[迁移] 原 CSV 已备份为 %s", backup_path.name)

    def _compute_sha256(self, file_path: Path) -> str:
        """计算文件的 SHA-256 哈希值"""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()

    def _row_to_dict(self, row) -> dict:
        """将数据库行转为字典"""
        if row is None:
            return None
        return {
            "sha256": row[0],
            "file_name": row[1],
            "company_name": row[2],
            "report_type": row[3],
            "report_year": row[4],
            "keywords": row[5],
            "status": row[6],
        }

    def register_pdf(self, pdf_path: Path, company_name: str = "", report_type: str = "", report_year: str = "", keywords: str = ""):
        """
        注册一个 PDF 文件的元信息

        Args:
            pdf_path:     PDF 文件路径
            company_name: 公司名称
            report_type:  报告类型（研报/年报/调研纪要）
            report_year:  报告年份
            keywords:     关键字标签（逗号分隔）
        """
        sha256 = self._compute_sha256(pdf_path)
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (sha256, file_name, company_name, report_type, report_year, keywords, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sha256, pdf_path.name, company_name, report_type, report_year, keywords, "registered"),
        )
        self._conn.commit()
        return sha256

    def update_status(self, file_name: str, status: str):
        """
        更新文档的处理状态

        Args:
            file_name: 文件名
            status:    状态值，可选: uploaded / parsed / chunked / indexed / registered
        """
        valid_statuses = {"uploaded", "parsed", "chunked", "indexed", "registered"}
        if status not in valid_statuses:
            raise ValueError(f"无效的状态值: {status}，有效值为: {valid_statuses}")
        cursor = self._conn.execute(
            "UPDATE metadata SET status = ? WHERE file_name = ?",
            (status, file_name),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"未找到文档: {file_name}")

    def get_status(self, file_name: str) -> Optional[str]:
        """获取文档的处理状态"""
        row = self._conn.execute(
            "SELECT status FROM metadata WHERE file_name = ?",
            (file_name,),
        ).fetchone()
        if row is None:
            return None
        return row[0]

    def register_batch(
        self,
        pdf_dir: Path,
        company_name: str = "",
        report_type: str = "",
        report_year: str = "",
        keywords: str = "",
    ) -> List[str]:
        """
        批量注册目录下所有 PDF 文件的元信息

        Args:
            pdf_dir:      PDF 文件目录
            company_name: 公司名称（所有文件共用，也可按具体规则推断）
            report_type:  报告类型
            report_year:  报告年份
            keywords:     关键字标签（逗号分隔，所有文件共用）

        Returns:
            sha256 列表
        """
        pdf_files = sorted(pdf_dir.glob("*.pdf"))
        if not pdf_files:
            return []

        sha256_list = []
        rows = []
        for pdf_path in pdf_files:
            sha256 = self._compute_sha256(pdf_path)
            rows.append((sha256, pdf_path.name, company_name, report_type, report_year, keywords, "registered"))
            sha256_list.append(sha256)
            _log.info("已注册: %s -> sha256=%s...", pdf_path.name, sha256[:12])

        self._conn.executemany(
            "INSERT OR REPLACE INTO metadata (sha256, file_name, company_name, report_type, report_year, keywords, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return sha256_list

    def get_by_sha256(self, sha256: str) -> Optional[dict]:
        """通过 sha256 获取元信息"""
        row = self._conn.execute(
            "SELECT sha256, file_name, company_name, report_type, report_year, keywords, status FROM metadata WHERE sha256 = ?",
            (sha256,),
        ).fetchone()
        return self._row_to_dict(row)

    def get_by_file_name(self, file_name: str) -> Optional[dict]:
        """通过文件名获取元信息"""
        row = self._conn.execute(
            "SELECT sha256, file_name, company_name, report_type, report_year, keywords, status FROM metadata WHERE file_name = ?",
            (file_name,),
        ).fetchone()
        return self._row_to_dict(row)

    def get_company_names(self) -> List[str]:
        """获取所有已注册的公司名列表"""
        rows = self._conn.execute(
            "SELECT DISTINCT company_name FROM metadata WHERE company_name != '' ORDER BY company_name"
        ).fetchall()
        return [r[0] for r in rows]

    def get_by_company(self, company_name: str) -> List[dict]:
        """获取指定公司的所有元信息"""
        rows = self._conn.execute(
            "SELECT sha256, file_name, company_name, report_type, report_year, keywords, status FROM metadata WHERE company_name = ?",
            (company_name,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_keywords(self, file_name: str, keywords: str):
        """
        更新文档的关键字标签

        Args:
            file_name: 文件名
            keywords:  关键字标签（逗号分隔）
        """
        cursor = self._conn.execute(
            "UPDATE metadata SET keywords = ? WHERE file_name = ?",
            (keywords, file_name),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            _log.warning("未找到文档: %s，无法更新关键字", file_name)
            return
        _log.info("已更新关键字: %s -> %s", file_name, keywords)

    def update_metadata(self, file_name: str, company_name: str = "", report_type: str = "", report_year: str = "", keywords: str = ""):
        """
        批量更新文档的元信息字段（仅更新非空字段）

        Args:
            file_name:    文件名
            company_name: 公司名称（空字符串表示不更新）
            report_type:  报告类型
            report_year:  报告年份
            keywords:     关键字标签
        """
        updates = []
        params = []
        updated = []
        if company_name:
            updates.append("company_name = ?")
            params.append(company_name)
            updated.append(f"company={company_name}")
        if report_type:
            updates.append("report_type = ?")
            params.append(report_type)
            updated.append(f"type={report_type}")
        if report_year:
            updates.append("report_year = ?")
            params.append(report_year)
            updated.append(f"year={report_year}")
        if keywords:
            updates.append("keywords = ?")
            params.append(keywords)
            updated.append(f"keywords={keywords[:30]}...")

        if not updates:
            return

        params.append(file_name)
        cursor = self._conn.execute(
            f"UPDATE metadata SET {', '.join(updates)} WHERE file_name = ?",
            params,
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            _log.warning("未找到文档: %s，无法更新元信息", file_name)
            return
        _log.info("已更新元信息: %s -> %s", file_name, ", ".join(updated))

    def get_keywords_map(self) -> Dict[str, str]:
        """
        获取文件名stem -> keywords 的映射

        Returns:
            {"中芯国际深度研究报告": "中芯国际,晶圆制造,芯片,...", ...}
        """
        rows = self._conn.execute(
            "SELECT file_name, keywords FROM metadata"
        ).fetchall()
        return {Path(r[0]).stem: r[1] for r in rows}

    def list_all(self) -> List[dict]:
        """列出所有元信息"""
        rows = self._conn.execute(
            "SELECT sha256, file_name, company_name, report_type, report_year, keywords, status FROM metadata"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_file_name_to_sha256_map(self) -> Dict[str, str]:
        """获取文件名(不含扩展名) -> sha256 的映射"""
        rows = self._conn.execute(
            "SELECT file_name, sha256 FROM metadata"
        ).fetchall()
        return {Path(r[0]).stem: r[1] for r in rows}

    @property
    def _records(self) -> Dict[str, dict]:
        """兼容旧代码中对 _records 的直接访问（如 server.py 中的删除操作）"""
        rows = self._conn.execute(
            "SELECT sha256, file_name, company_name, report_type, report_year, keywords, status FROM metadata"
        ).fetchall()
        return {r[0]: self._row_to_dict(r) for r in rows}

    def _save(self):
        """兼容旧代码中的 _save() 调用（SQLite 已自动提交，无需额外操作）"""
        pass

    def delete_by_file_name(self, file_name: str) -> bool:
        """通过文件名删除元信息记录"""
        cursor = self._conn.execute(
            "DELETE FROM metadata WHERE file_name = ?",
            (file_name,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def validate_consistency(self) -> Dict[str, List[str]]:
        """
        校验索引一致性，检查各类文件是否存在缺失或不匹配

        Returns:
            {"ok": [...], "missing_pdf": [...], "missing_md": [...], "missing_json": [...], "missing_faiss": [...], "missing_bm25": [...]}
        """
        result = {
            "ok": [],
            "missing_pdf": [],
            "missing_md": [],
            "missing_json": [],
            "missing_faiss": [],
            "missing_bm25": [],
        }

        for record in self.list_all():
            file_name = record["file_name"]
            stem = Path(file_name).stem
            issues = []

            if not (PDF_DATA_DIR / file_name).exists():
                issues.append("missing_pdf")
            if not (PARSED_MD_DIR / f"{stem}.md").exists():
                issues.append("missing_md")
            if not (CHUNKED_JSON_DIR / f"{stem}.json").exists():
                issues.append("missing_json")
            if not (FAISS_INDEX_DIR / f"{stem}.faiss").exists():
                issues.append("missing_faiss")
            if not (BM25_INDEX_DIR / f"{stem}.pkl").exists():
                issues.append("missing_bm25")

            if issues:
                for issue in issues:
                    result[issue].append(file_name)
            else:
                result["ok"].append(file_name)

        return result
