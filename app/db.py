"""SQLite 持久化：连接管理与建表。

单写死 demo 用户，无账号 / 多用户。表结构见同目录 `schema.sql`，
换结构只改该数据文件，不在代码里硬编码 DDL。
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import settings

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """连接的上下文管理器：开外键约束、按列名取行、成功提交/异常回滚、总是关闭。

    读写都走这里，退出即关闭——报告页会高频轮询 GET /reports，连接不关会泄漏。
    """
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """按 schema.sql 建表（全部 IF NOT EXISTS，可安全重复执行）。"""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn:
        conn.executescript(schema)
