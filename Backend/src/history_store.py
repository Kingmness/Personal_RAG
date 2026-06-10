# -*- coding: utf-8 -*-
"""
历史查询记录存储
使用 SQLite 存储查询历史，支持自动清理三天前的记录
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Any

from config import PROJECT_ROOT
from logger import setup_logger

_log = setup_logger(name="pra.history")


@dataclass
class QueryHistory:
    """查询历史记录"""
    id: Optional[int] = None
    question: str = ""
    answer_type: str = "text"
    answer: str = ""
    sources: List[str] = None
    elapsed: float = 0.0
    created_at: Optional[str] = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = []
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class HistoryStore:
    """历史记录存储管理器"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = PROJECT_ROOT / "data" / "history.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer_type TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    sources TEXT NOT NULL,
                    elapsed REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON query_history(created_at)
            """)
        _log.info("历史记录数据库初始化完成")

    def add_record(self, record: QueryHistory) -> int:
        """添加一条查询记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO query_history (question, answer_type, answer, sources, elapsed, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                record.question,
                record.answer_type,
                record.answer,
                json.dumps(record.sources, ensure_ascii=False),
                record.elapsed,
                record.created_at
            ))
            record_id = cursor.lastrowid
        _log.info(f"添加查询记录: id={record_id}, question={record.question[:30]}...")
        return record_id

    def get_records(self, limit: int = 100, offset: int = 0) -> List[QueryHistory]:
        """获取查询历史记录，按时间倒序排列"""
        records = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, question, answer_type, answer, sources, elapsed, created_at
                FROM query_history
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            for row in cursor:
                records.append(QueryHistory(
                    id=row[0],
                    question=row[1],
                    answer_type=row[2],
                    answer=row[3],
                    sources=json.loads(row[4]),
                    elapsed=row[5],
                    created_at=row[6]
                ))
        return records

    def delete_record(self, record_id: int) -> bool:
        """删除一条记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM query_history WHERE id = ?", (record_id,))
            deleted = cursor.rowcount > 0
        if deleted:
            _log.info(f"删除查询记录: id={record_id}")
        return deleted

    def clear_all(self) -> int:
        """清空所有记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM query_history")
            count = cursor.rowcount
        _log.info(f"清空所有查询记录: count={count}")
        return count

    def cleanup_old_records(self, days: int = 3) -> int:
        """清理指定天数前的旧记录"""
        cutoff_time = datetime.now() - timedelta(days=days)
        cutoff_iso = cutoff_time.isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM query_history WHERE created_at < ?", (cutoff_iso,))
            count = cursor.rowcount
        
        if count > 0:
            _log.info(f"清理{days}天前的旧记录: count={count}")
        
        return count

    def to_dict(self, record: QueryHistory) -> dict:
        """将记录转换为字典，用于API响应"""
        data = asdict(record)
        # 格式化时间显示
        if data.get("created_at"):
            try:
                dt = datetime.fromisoformat(data["created_at"])
                data["created_at_formatted"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                data["created_at_formatted"] = data["created_at"]
        return data


# 全局实例
_history_store: Optional[HistoryStore] = None


def get_history_store() -> HistoryStore:
    """获取历史记录存储管理器单例"""
    global _history_store
    if _history_store is None:
        _history_store = HistoryStore()
    return _history_store
