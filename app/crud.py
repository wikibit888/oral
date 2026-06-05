"""SQLite 读写（单写死 demo 用户）。表结构见 schema.sql。"""

from app.db import get_connection


def create_session(
    *,
    session_id: str,
    mode: str,
    sub_mode: str | None,
    scenario_case: str | None,
    audio_path: str | None,
    duration_s: float | None,
    status: str,
) -> str:
    """插入一条会话记录，返回其 id。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions "
            "(id, mode, sub_mode, scenario_case, audio_path, duration_s, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, mode, sub_mode, scenario_case, audio_path, duration_s, status),
        )
    return session_id
