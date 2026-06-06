"""SQLite 读写（单写死 demo 用户）。表结构见 schema.sql。

本层只搬数据、不懂报告 schema：正规化列由上层（pipeline）从 Report 抽好后传入。
"""

import sqlite3

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


def get_session(session_id: str) -> sqlite3.Row | None:
    """取一条会话；不存在返回 None。"""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()


def update_session_status(session_id: str, status: str) -> None:
    """推进会话状态机：uploaded → processing → done | failed。"""
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET status = ? WHERE id = ?", (status, session_id)
        )


def create_report(
    *,
    session_id: str,
    mode: str,
    overall_band: float | None,
    fc_band: float | None,
    lr_band: float | None,
    gra_band: float | None,
    pron_band: float | None,
    wpm: float | None,
    silence_ratio: float | None,
    filler_pm: float | None,
    ttr: float | None,
    error_rate: float | None,
    report_json: str,
) -> None:
    """落一份课后报告：正规化列（跨会话曲线用）+ 完整 report_json blob。

    INSERT OR REPLACE 让重跑流水线幂等（一会话一份报告）。
    """
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reports "
            "(session_id, mode, overall_band, fc_band, lr_band, gra_band, pron_band, "
            " wpm, silence_ratio, filler_pm, ttr, error_rate, report_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, mode, overall_band, fc_band, lr_band, gra_band, pron_band,
                wpm, silence_ratio, filler_pm, ttr, error_rate, report_json,
            ),
        )


def get_report(session_id: str) -> sqlite3.Row | None:
    """取一份报告；不存在返回 None。"""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM reports WHERE session_id = ?", (session_id,)
        ).fetchone()
