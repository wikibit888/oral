"""用户音频 tee：上行 16k PCM 分叉缓冲，按轮次边界切片喂增量流水线（SCHEMA §3）。

时钟 = 累计用户音频字节推导的流位置（16k/16-bit/mono → 32000 B/s）：上行帧
到达即推进流位置，轮次事件发生时记当前位置切片——全程一个时钟，免转码直写 WAV。
切片落地即后台 whisper 转写（持锁串行）+ Files API 预上传（脱锁并发），end_session
后 finalize 只剩一次 judge——这正是 live 会话报告 ≤5s 的前提。

地板（floor）状态机决定哪些帧进切片（与 merge_transcripts 语义对齐：考官说话
时段不在任何切片里，切片内静默 = 用户真实犹豫）：
- 初始用户持地板（考官先开口时首切片为空，被最短时长过滤掉）；
- 下行出现考官音频 → 地板易手，封当前切片；
- turn_complete → 地板归还用户，开新切片；
- interrupted（barge-in）→ 地板归还用户，并把预缓冲（考官说话期间的近段
  麦克风帧）接回切片头——用户打断的起头发生在事件到达之前，不回补会掉词。

钩子全部在事件循环内同步调用、只动内存；阻塞活经 asyncio.to_thread 后台执行：
写盘 + whisper 转写持 _ingest_lock 串行（whisper 模型是进程内单例，不并发喂），
Files API 上传脱锁并发（多切片网络往返不再串在 whisper 之后）。
"""

import asyncio
import logging
from collections import deque

from app import crud
from app.models import Transcript
from app.pipeline import finalize_clip, transcribe_clip
from app.storage import save_clip, save_examiner_clip

logger = logging.getLogger(__name__)

BYTES_PER_SECOND = 32000          # 16kHz × 16-bit × mono（用户上行）
EXAMINER_BYTES_PER_SECOND = 48000  # 24kHz × 16-bit × mono（考官/AI 下行，dialog 回看）
MIN_CLIP_SECONDS = 0.4     # 短于此的切片丢弃（VAD 毛刺 / 空地板，不值一次 whisper）
MIN_EXAMINER_CLIP_SECONDS = 0.2   # 考官切片下限（更小：纯回放、短促应答也保留）
PREBUFFER_SECONDS = 2.0    # barge-in 回补的预缓冲上限


class UserAudioTee:
    """单连接的用户音频分叉器；由 bridge 钩子驱动，live_ws 负责 finish/drain。"""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        # 当前切片：用户持地板时无上限累积——上限即用户单回合说话时长，
        # demo 量级（分钟级 ≈ 每分钟 1.9MB）可接受，不做滚动截断
        self._buf = bytearray()
        self._clip_start = 0.0                  # 当前切片起点（流位置秒）
        self._pos = 0.0                         # 流位置：累计收到的用户音频秒数
        self._user_has_floor = True
        self._prebuf: deque[bytes] = deque()    # 地板不在手时的近段帧（barge-in 回补用）
        self._prebuf_bytes = 0
        self._clip_seq = 0
        self._finished = False
        self._ingest_tasks: list[asyncio.Task] = []
        self._ingest_lock = asyncio.Lock()      # 切片串行 ingest：whisper 单例不并发喂
        # —— 考官/AI 下行音频按轮捕获（dialog 回看，纯回放、绝不进评测）——
        # 独立缓冲，不复用用户 _buf/_clip_seq/_ingest_tasks：否则污染评测切片与孤儿判定。
        self._examiner_buf = bytearray()
        self._examiner_clip_start = 0.0         # 本考官轮起点（用户 _pos 时钟，与用户轮同轴）
        self._examiner_text: list[str] = []     # 本考官轮的 output 转写增量
        self._examiner_seq = 0
        self._examiner_tasks: list[asyncio.Task] = []   # fire-and-forget；drain 不等它

    @property
    def clip_count(self) -> int:
        """已切出的切片数。为 0 说明从未发起任何 ingest（孤儿会话判定用，无 DB 竞态）。"""
        return self._clip_seq

    # ---- bridge 钩子（事件循环内同步调用） ----
    # finish() 后全部失效：end_session 之后、下行泵被取消之前，Live 已缓冲的
    # turn_complete / 音频仍可能再走一拍钩子——若不挡住，会翻转地板再切出
    # drain 快照之外的新切片，finalize 就会漏掉它（review W1/W2）。

    def on_user_frame(self, data: bytes) -> None:
        """每个上行音频帧：持地板进切片，否则进预缓冲（环形，最多 2s）。"""
        if self._finished:
            return
        if self._user_has_floor:
            self._buf += data
        else:
            self._prebuf.append(data)
            self._prebuf_bytes += len(data)
            while self._prebuf_bytes > PREBUFFER_SECONDS * BYTES_PER_SECOND:
                self._prebuf_bytes -= len(self._prebuf.popleft())
        self._pos += len(data) / BYTES_PER_SECOND

    def on_model_audio(self, data: bytes | None = None) -> None:
        """下行考官音频帧：首帧即地板易手、封当前用户切片；并按轮累积考官音频（dialog 回看）。

        data = 该帧 24k PCM 字节（bridge 传入）；None 时只作边界信号（旧调用方/测试假体）。
        考官音频只回放、不进评测——独立缓冲，不碰用户切片链路。
        """
        if self._finished:
            return
        if self._user_has_floor:
            self._user_has_floor = False
            self._cut_clip()
            # 考官开口 = 本考官轮起点（用 _pos 用户时钟，与用户轮同一时间轴 → dialog 正确交错）
            self._examiner_clip_start = self._pos
            self._examiner_buf = bytearray()
            self._examiner_text = []
        if data is not None:
            self._examiner_buf += data

    def on_examiner_transcript(self, text: str) -> None:
        """考官 output 转写增量：考官持地板期间累积进当前考官轮文本（dialog 显示用）。"""
        if self._finished:
            return
        if not self._user_has_floor and text:
            self._examiner_text.append(text)

    def on_turn_complete(self) -> None:
        if self._finished:
            return
        self._cut_examiner_clip()           # 考官轮结束 → 封考官切片
        self._take_floor(with_prebuffer=False)

    def on_interrupted(self) -> None:
        if self._finished:
            return
        self._cut_examiner_clip()           # barge-in 打断考官 → 封（可能残段，纯回放可接受）
        self._take_floor(with_prebuffer=True)

    def finish(self) -> None:
        """end_session：封最后一个切片（用户末轮没有后续考官音频来切它）。

        幂等；置 _finished 后所有钩子失效，保证 drain 的任务快照完整。
        """
        if self._finished:
            return
        self._finished = True
        if self._user_has_floor:
            self._user_has_floor = False
            self._cut_clip()
        else:
            # 末轮考官还在说（用户没等 turn_complete 直接 End）：封最后一个考官切片
            self._cut_examiner_clip()

    async def drain(self) -> None:
        """等全部切片 ingest 落库——finalize 前必须，否则末轮切片会被漏掉。

        finish() 已封口（钩子失效、不再有新切片），此处快照即全集。
        """
        if self._ingest_tasks:
            await asyncio.gather(*self._ingest_tasks, return_exceptions=True)

    # ---- 内部 ----

    def _take_floor(self, *, with_prebuffer: bool) -> None:
        # interrupted 与 turn_complete 可能相继到达：只第一个生效，第二个不能
        # 重置已经开始累积的新切片
        if self._user_has_floor:
            return
        self._user_has_floor = True
        self._buf = bytearray()
        self._clip_start = self._pos
        if with_prebuffer:
            joined = b"".join(self._prebuf)
            self._buf += joined
            self._clip_start = self._pos - len(joined) / BYTES_PER_SECOND
        self._prebuf.clear()
        self._prebuf_bytes = 0

    def _cut_clip(self) -> None:
        pcm = bytes(self._buf)
        self._buf = bytearray()
        if len(pcm) < MIN_CLIP_SECONDS * BYTES_PER_SECOND:
            return
        start = self._clip_start
        end = start + len(pcm) / BYTES_PER_SECOND   # 切片内帧连续，end 即起点+时长
        seq = self._clip_seq
        self._clip_seq += 1
        task = asyncio.create_task(self._ingest(pcm, seq, start, end))
        self._ingest_tasks.append(task)
        task.add_done_callback(self._ingest_tasks.remove)  # 完成即回收句柄

    async def _ingest(self, pcm: bytes, seq: int, start_ts: float, end_ts: float) -> None:
        """一个切片的完整生命周期（转写 → 上传 → 收口）都在本 task 内 await——drain 才能
        等齐（绝不把上传甩成 fire-and-forget，否则末轮 file_uri 漏空）。whisper 单例只
        串行「转写段」（持锁）；「上传/收口段」脱锁、多切片可并发。任一段失败只损失该
        回合素材，不拖垮会话/其余切片。
        """
        transcribed = await self._transcribe_locked(pcm, seq, start_ts, end_ts)
        if transcribed is None:                       # 转写段已失败（已记日志）
            return
        turn_id, path, transcript = transcribed
        try:
            await asyncio.to_thread(finalize_clip, turn_id, path, transcript)
        except Exception:
            logger.exception(
                "tee 切片上传/收口失败: session=%s seq=%s", self.session_id, seq
            )

    async def _transcribe_locked(
        self, pcm: bytes, seq: int, start_ts: float, end_ts: float
    ) -> tuple[int, str, Transcript] | None:
        """转写段：whisper 单例不并发喂——写盘 + create_turn + 转写全程持 _ingest_lock
        串行。create_turn 在锁内按 seq 顺序分配 turns.id（merge_transcripts 依赖 id 序），
        不被并发打乱。失败返回 None（已记日志），上层跳过上传段。
        """
        async with self._ingest_lock:
            try:
                return await asyncio.to_thread(
                    self._transcribe_sync, pcm, seq, start_ts, end_ts
                )
            except Exception:
                logger.exception(
                    "tee 切片转写失败: session=%s seq=%s", self.session_id, seq
                )
                return None

    def _transcribe_sync(
        self, pcm: bytes, seq: int, start_ts: float, end_ts: float
    ) -> tuple[int, str, Transcript]:
        path = save_clip(self.session_id, seq, pcm)
        turn_id, transcript = transcribe_clip(
            self.session_id,
            path,
            start_ts=round(start_ts, 3),
            end_ts=round(end_ts, 3),
        )
        return turn_id, path, transcript

    # ---- 考官/AI 音频按轮捕获（dialog 回看，纯回放、不进评测）----

    def _cut_examiner_clip(self) -> None:
        """封当前考官轮：写 24k WAV + 落一条 assistant turn 行（绝不走 ingest_clip）。

        fire-and-forget：任务进 _examiner_tasks（独立于 _ingest_tasks），drain 不等它，
        保报告 ≤5s。音频太短且无文本则丢（barge-in 毛刺 / 空轮），不留噪声回合。
        """
        if self._user_has_floor:
            return                          # 当前不是考官在说，无可封
        pcm = bytes(self._examiner_buf)
        self._examiner_buf = bytearray()
        text = "".join(self._examiner_text).strip()
        self._examiner_text = []
        if len(pcm) < MIN_EXAMINER_CLIP_SECONDS * EXAMINER_BYTES_PER_SECOND and not text:
            return
        start = round(self._examiner_clip_start, 3)
        end = round(self._pos, 3)
        seq = self._examiner_seq
        self._examiner_seq += 1
        task = asyncio.create_task(self._save_examiner(pcm, seq, start, end, text))
        self._examiner_tasks.append(task)
        task.add_done_callback(self._examiner_tasks.remove)

    async def _save_examiner(
        self, pcm: bytes, seq: int, start_ts: float, end_ts: float, text: str
    ) -> None:
        # 写盘 + 一次 DB 插入都在线程里跑（DB/IO 阻塞活），不阻塞事件循环。
        await asyncio.to_thread(self._save_examiner_sync, pcm, seq, start_ts, end_ts, text)

    def _save_examiner_sync(
        self, pcm: bytes, seq: int, start_ts: float, end_ts: float, text: str
    ) -> None:
        try:
            clip_path = save_examiner_clip(self.session_id, seq, pcm) if pcm else None
            crud.create_turn(
                session_id=self.session_id,
                role="assistant",
                clip_path=clip_path,
                start_ts=start_ts,
                end_ts=end_ts,
                text=text or None,
            )
        except Exception:
            logger.exception(
                "考官切片落盘失败: session=%s seq=%s", self.session_id, seq
            )
