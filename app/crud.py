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


def create_turn(
    *,
    session_id: str,
    role: str,
    clip_path: str | None,
    start_ts: float | None = None,
    end_ts: float | None = None,
) -> int:
    """插入一个回合（切片落地时建行，转写结果稍后回填），返回自增 id。"""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO turns (session_id, role, clip_path, start_ts, end_ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, clip_path, start_ts, end_ts),
        )
        return cur.lastrowid


def finish_turn(
    turn_id: int,
    *,
    text: str,
    transcript_json: str,
    file_uri: str | None,
) -> None:
    """回填一个回合的增量流水线产物（转写文本 + 词时间戳 + Files API URI）。"""
    with get_connection() as conn:
        conn.execute(
            "UPDATE turns SET text = ?, transcript_json = ?, file_uri = ? WHERE id = ?",
            (text, transcript_json, file_uri, turn_id),
        )


def list_processed_user_turns(session_id: str) -> list[sqlite3.Row]:
    """取一个会话已完成转写的用户回合（finalize 合并信号 + 选切片用），按落地顺序。"""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM turns "
            "WHERE session_id = ? AND role = 'user' AND transcript_json IS NOT NULL "
            "ORDER BY id",
            (session_id,),
        ).fetchall()


def delete_turns(session_id: str) -> None:
    """清空一个会话的全部回合（一次性入口重跑流水线时保证幂等）。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))


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
