"""Review 进步面板与设置（SCHEMA §6.4）。

GET /progress      跨会话进步数据：band 轨迹（仅雅思方式 A）+ 流利度趋势（全模式）
                   + 目标差距（target − 最新各维；不做未来预测）
GET /settings      读用户目标 band（单 demo 用户单行）
PUT /settings      写 / 清除目标 band（null = 清除）

边界（FRONTEND §2）：band 只在雅思方式 A 有意义，方式 B 与情景对话只进流利度区。
"""

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import crud

router = APIRouter(tags=["review"])


class BandPoint(BaseModel):
    """band 轨迹一个点（仅雅思方式 A 的 completed 报告）。"""

    date: str                        # 会话 started_at（ISO 8601）
    overall_band: float
    fc_band: float | None            # judge 降级输出可能缺维度，可空兜底
    lr_band: float | None
    gra_band: float | None
    pron_band: float | None


class FluencyPoint(BaseModel):
    """流利度趋势一个点（全模式可比的客观信号）。"""

    date: str
    wpm: float
    silence_ratio: float | None
    filler_pm: float | None
    error_rate: float | None


class BandGap(BaseModel):
    """目标差距：target − 最新各维（正 = 还差多少；负 = 已超出目标）。"""

    overall_band: float
    fc_band: float | None
    lr_band: float | None
    gra_band: float | None
    pron_band: float | None


class ProgressResponse(BaseModel):
    band_series: list[BandPoint]         # 时间升序
    fluency_series: list[FluencyPoint]   # 时间升序
    target_band: float | None
    latest_bands: BandPoint | None       # band_series 最新一点（雷达 / 差距基准）
    gap: BandGap | None                  # 无目标或无方式 A 报告时为 null


class SettingsPayload(BaseModel):
    target_band: float | None


@router.get("/progress", response_model=ProgressResponse)
async def get_progress() -> ProgressResponse:
    rows = crud.list_completed_reports()
    band_series = [_band_point(r) for r in rows if _is_band_row(r)]
    fluency_series = [_fluency_point(r) for r in rows if r["wpm"] is not None]
    target_band = crud.get_target_band()
    latest_bands = band_series[-1] if band_series else None
    return ProgressResponse(
        band_series=band_series,
        fluency_series=fluency_series,
        target_band=target_band,
        latest_bands=latest_bands,
        gap=_gap(target_band, latest_bands),
    )


@router.get("/settings", response_model=SettingsPayload)
async def get_settings() -> SettingsPayload:
    return SettingsPayload(target_band=crud.get_target_band())


@router.put("/settings", response_model=SettingsPayload)
async def put_settings(body: SettingsPayload) -> SettingsPayload:
    band = body.target_band
    if band is not None and (not 0 <= band <= 9 or (band * 2) % 1 != 0):
        raise HTTPException(
            status_code=422,
            detail="target_band 须在 0–9 之间且为 0.5 的倍数（null 表示清除）",
        )
    crud.set_target_band(band)
    return SettingsPayload(target_band=band)


def _is_band_row(row: sqlite3.Row) -> bool:
    """只有雅思方式 A（sub_mode=exam）且 judge 真出了 overall band 的报告进轨迹。

    方式 B / 情景对话 band 恒 null（judge 层强制置空）；双重过滤防御历史脏行。
    """
    return (
        row["mode"] == "ielts"
        and row["sub_mode"] == "exam"
        and row["overall_band"] is not None
    )


def _band_point(row: sqlite3.Row) -> BandPoint:
    return BandPoint(
        date=row["started_at"],
        overall_band=row["overall_band"],
        fc_band=row["fc_band"],
        lr_band=row["lr_band"],
        gra_band=row["gra_band"],
        pron_band=row["pron_band"],
    )


def _fluency_point(row: sqlite3.Row) -> FluencyPoint:
    return FluencyPoint(
        date=row["started_at"],
        wpm=row["wpm"],
        silence_ratio=row["silence_ratio"],
        filler_pm=row["filler_pm"],
        error_rate=row["error_rate"],
    )


def _gap(target: float | None, latest: BandPoint | None) -> BandGap | None:
    """target − 最新各维；缺目标或缺方式 A 报告则整体 null，缺单维则该维 null。"""
    if target is None or latest is None:
        return None

    def diff(band: float | None) -> float | None:
        return None if band is None else round(target - band, 1)

    return BandGap(
        overall_band=round(target - latest.overall_band, 1),
        fc_band=diff(latest.fc_band),
        lr_band=diff(latest.lr_band),
        gra_band=diff(latest.gra_band),
        pron_band=diff(latest.pron_band),
    )
