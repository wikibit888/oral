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
# 列 DDL 白名单：允许字母/数字/下划线/空格（如 "INTEGER NOT NULL DEFAULT 0"）
_DDL_RE = re.compile(r"^[A-Za-z0-9_ ]+$")


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
        _ensure_columns(
            conn,
            "sessions",
            {"is_seed": "INTEGER NOT NULL DEFAULT 0"},
        )
        _migrate_status_enum_once(conn)


# 数据迁移版本（PRAGMA user_version）：每个一次性迁移占一个版本号，只升不降。
_DATA_VERSION = 2


def _migrate_status_enum_once(conn: sqlite3.Connection) -> None:
    """status 枚举一次性迁移（SCHEMA §5.1），按 PRAGMA user_version 分步门控。

    **绝不能每次启动重跑**（review C1）：会话化接口之后 recording 是方式 B
    录音中的活跃态，重跑 v1 会把活跃行误迁成 live。每步只在低版本库上执行
    一次，落版本号后永久跳过；版本号与 UPDATE 同事务原子提交。
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        # v1（P4b）：done→completed；recording→live（当时 recording 全来自 Live 会话）
        conn.execute("UPDATE sessions SET status='completed' WHERE status='done'")
        conn.execute("UPDATE sessions SET status='live' WHERE status='recording'")
    if version < 2:
        # v2（P4c）：旧 POST /recordings 已移除，卡在 uploaded 的行（上传了但
        # 流水线从未跑完）永远无人处理——诚实置 failed，不留前端无法渲染的死态
        conn.execute("UPDATE sessions SET status='failed' WHERE status='uploaded'")
    if version < _DATA_VERSION:
        conn.execute(f"PRAGMA user_version = {_DATA_VERSION}")


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """给存量表幂等补列（新列只能是可空列，旧行取 NULL）。

    标识符无法参数化绑定，只能拼 SQL——白名单校验把守，本函数只接受代码内
    硬编码的表名/列名，禁止传入任何外部输入。
    """
    if not _IDENT_RE.match(table):
        raise ValueError(f"非法表名: {table!r}")
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns.items():
        if not _IDENT_RE.match(name) or not _DDL_RE.match(ddl):
            raise ValueError(f"非法列定义: {name!r} {ddl!r}")
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
