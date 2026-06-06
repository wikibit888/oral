"""SQLite 持久化：连接管理与建表。

单写死 demo 用户，无账号 / 多用户。表结构见同目录 `schema.sql`，
换结构只改该数据文件，不在代码里硬编码 DDL。
"""

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import settings

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# SQL 标识符白名单（_ensure_columns 用）：仅字母/下划线，掐死注入面。
_IDENT_RE = re.compile(r"^[A-Za-z_]+$")


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
    """按 schema.sql 建表（全部 IF NOT EXISTS，可安全重复执行）。

    IF NOT EXISTS 不会给已存在的表加新列——对旧库幂等补列（demo 无迁移体系，
    schema.sql 永远是目标态，这里把存量库拉齐）。
    """
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn:
        # 注意 executescript 会先隐式 COMMIT 当前事务——init_db 必须独占连接调用。
        conn.executescript(schema)
        _ensure_columns(
            conn,
            "turns",
            {"transcript_json": "TEXT", "file_uri": "TEXT"},
        )


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """给存量表幂等补列（新列只能是可空列，旧行取 NULL）。

    标识符无法参数化绑定，只能拼 SQL——白名单校验把守，本函数只接受代码内
    硬编码的表名/列名，禁止传入任何外部输入。
    """
    if not _IDENT_RE.match(table):
        raise ValueError(f"非法表名: {table!r}")
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns.items():
        if not _IDENT_RE.match(name) or not _IDENT_RE.match(ddl.replace(" ", "_")):
            raise ValueError(f"非法列定义: {name!r} {ddl!r}")
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
