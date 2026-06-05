"""SQLite 持久化：连接管理与建表。

单写死 demo 用户，无账号 / 多用户。表结构见同目录 `schema.sql`，
换结构只改该数据文件，不在代码里硬编码 DDL。
"""

import sqlite3
from pathlib import Path

from app.config import settings

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    """打开一个连接：开启外键约束、按列名访问行（sqlite3.Row）。"""
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """按 schema.sql 建表（全部 IF NOT EXISTS，可安全重复执行）。"""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn:
        conn.executescript(schema)
