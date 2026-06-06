"""录音上传入口：方式 B / 情景对话录音 → 落库 sessions（不依赖 Live）。

POST /recordings — multipart WAV + {mode, sub_mode, scenario_case}
上传落库后即在后台触发课后流水线（whisper → 信号 → judge → 报告），
前端轮询 GET /reports/{id} 看进度与结果。
"""

import io
import wave
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import crud
from app.pipeline import process_session
from app.storage import save_recording

router = APIRouter(tags=["recordings"])

VALID_MODES = {"ielts", "scenario"}
VALID_SUB_MODES = {"exam", "module_p1", "module_p2", "module_p3"}
VALID_SCENARIO_CASES = {"ordering", "meeting"}

# 固定音频契约（CLAUDE.md：mic in 16kHz / 16-bit / 单声道 PCM，无转码）
EXPECTED_SAMPLE_RATE = 16000
EXPECTED_CHANNELS = 1
EXPECTED_SAMPLE_WIDTH = 2  # 字节，= 16-bit


class RecordingCreated(BaseModel):
    id: str
    mode: str
    sub_mode: str | None
    scenario_case: str | None
    duration_s: float | None
    status: str


def _wav_duration_seconds(data: bytes) -> float:
    """解析 WAV 头、强制固定音频契约（16kHz / 单声道 / 16-bit），返回时长（秒）。

    非合法 WAV 或违约格式一律抛 422。契约是「固定、无转码」——不在上传层做隐式重采样，
    把不合规音频挡在流水线之外（否则只能靠 whisper 内部兜底解码，属契约漂移、信号不可控）。
    """
    # 非 PCM（mu-law/A-law/float 等压缩编码）会被 wave.open 当 "unknown format" 抛出，下面一并 422。
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            channels = w.getnchannels()
            width = w.getsampwidth()
    except (wave.Error, EOFError):
        raise HTTPException(status_code=422, detail="audio 必须是合法的 WAV 文件")
    if rate != EXPECTED_SAMPLE_RATE:
        raise HTTPException(
            status_code=422, detail=f"采样率必须是 {EXPECTED_SAMPLE_RATE}Hz（收到 {rate}Hz）"
        )
    if channels != EXPECTED_CHANNELS:
        raise HTTPException(
            status_code=422, detail=f"必须是单声道 mono（收到 {channels} 声道）"
        )
    if width != EXPECTED_SAMPLE_WIDTH:
        raise HTTPException(
            status_code=422, detail=f"必须是 16-bit PCM（收到 {width * 8}-bit）"
        )
    if frames == 0:
        raise HTTPException(status_code=422, detail="音频不能为空（0 帧）")
    return round(frames / rate, 3)


@router.post("/recordings", response_model=RecordingCreated, status_code=201)
async def create_recording(
    background_tasks: BackgroundTasks,
    audio: Annotated[UploadFile, File(description="16kHz/16-bit/单声道 PCM WAV")],
    mode: Annotated[str, Form()],
    sub_mode: Annotated[str | None, Form()] = None,
    scenario_case: Annotated[str | None, Form()] = None,
) -> RecordingCreated:
    # 校验 mode 及其子类一致性（雅思走 sub_mode，情景走 scenario_case，互斥）
    if mode not in VALID_MODES:
        raise HTTPException(status_code=422, detail=f"mode 必须是 {sorted(VALID_MODES)} 之一")
    if mode == "ielts":
        if sub_mode not in VALID_SUB_MODES:
            raise HTTPException(
                status_code=422,
                detail=f"ielts 模式需 sub_mode ∈ {sorted(VALID_SUB_MODES)}",
            )
        scenario_case = None
    else:  # scenario
        if scenario_case not in VALID_SCENARIO_CASES:
            raise HTTPException(
                status_code=422,
                detail=f"scenario 模式需 scenario_case ∈ {sorted(VALID_SCENARIO_CASES)}",
            )
        sub_mode = None

    data = await audio.read()
    duration_s = _wav_duration_seconds(data)  # 同时充当 WAV 合法性校验

    session_id = uuid4().hex
    audio_path = save_recording(session_id, data)
    crud.create_session(
        session_id=session_id,
        mode=mode,
        sub_mode=sub_mode,
        scenario_case=scenario_case,
        audio_path=audio_path,
        duration_s=duration_s,
        status="uploaded",
    )
    # 响应返回后在后台跑课后流水线（whisper 阻塞活，Starlette 丢线程池执行）。
    background_tasks.add_task(process_session, session_id)

    return RecordingCreated(
        id=session_id,
        mode=mode,
        sub_mode=sub_mode,
        scenario_case=scenario_case,
        duration_s=duration_s,
        status="uploaded",
    )
