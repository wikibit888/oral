"""报告查询入口：处理页轮询状态、报告页取完整结果。

GET /reports/{id} —— 返回会话状态；status=completed 时附完整报告 JSON（SCHEMA §5.2）。
课后流水线在后台异步跑，前端据 status 决定继续轮询还是渲染报告。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import crud
from app.report import Report

router = APIRouter(tags=["reports"])


class ReportResponse(BaseModel):
    id: str
    mode: str
    # SCHEMA §5.1 枚举: live | recording | processing | completed | failed
    # （uploaded 为旧 POST /recordings 过渡态，会话化接口取代后移除）
    status: str
    report: Report | None = None     # 仅 status=completed 且报告已落库时有值


@router.get("/reports/{session_id}", response_model=ReportResponse)
async def get_report(session_id: str) -> ReportResponse:
    session = crud.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session 不存在")

    report: Report | None = None
    if session["status"] == "completed":
        row = crud.get_report(session_id)
        if row is not None:
            report = Report.model_validate_json(row["report_json"])

    return ReportResponse(
        id=session_id,
        mode=session["mode"],
        status=session["status"],
        report=report,
    )
