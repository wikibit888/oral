"""用户音频 tee：上行 16k PCM 分叉缓冲，按轮次边界切片喂增量流水线（SCHEMA §3）。

时钟 = 累计用户音频字节推导的流位置（16k/16-bit/mono → 32000 B/s）：上行帧
到达即推进流位置，轮次事件发生时记当前位置切片——全程一个时钟，免转码直写 WAV。
切片落地即后台 whisper 转写 + Files API 预上传（ingest_clip），end_session 后
finalize 只剩一次 judge——这正是 live 会话报告 ≤5s 的前提。

地板（floor）状态机决定哪些帧进切片（与 merge_transcripts 语义对齐：考官说话
时段不在任何切片里，切片内静默 = 用户真实犹豫）：
- 初始用户持地板（考官先开口时首切片为空，被最短时长过滤掉）；
- 下行出现考官音频 → 地板易手，封当前切片；
- turn_complete → 地板归还用户，开新切片；
- interrupted（barge-in）→ 地板归还用户，并把预缓冲（考官说话期间的近段
  麦克风帧）接回切片头——用户打断的起头发生在事件到达之前，不回补会掉词。

钩子全部在事件循环内同步调用、只动内存；阻塞活（写盘 + whisper + 上传）经
asyncio.to_thread 后台串行执行（whisper 模型是进程内单例，不并发喂）。
"""

import asyncio
import logging
from collections import deque

from app.pipeline import ingest_clip
from app.storage import save_clip

logger = logging.getLogger(__name__)

BYTES_PER_SECOND = 32000   # 16kHz × 16-bit × mono
MIN_CLIP_SECONDS = 0.4     # 短于此的切片丢弃（VAD 毛刺 / 空地板，不值一次 whisper）
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

    def on_model_audio(self) -> None:
        """下行考官音频帧：首帧即地板易手，封当前用户切片（后续帧无操作）。"""
        if self._finished:
            return
        if self._user_has_floor:
            self._user_has_floor = False
            self._cut_clip()

    def on_turn_complete(self) -> None:
        if self._finished:
            return
        self._take_floor(with_prebuffer=False)

    def on_interrupted(self) -> None:
        if self._finished:
            return
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
        async with self._ingest_lock:
            await asyncio.to_thread(self._ingest_sync, pcm, seq, start_ts, end_ts)

    def _ingest_sync(self, pcm: bytes, seq: int, start_ts: float, end_ts: float) -> None:
        # 单个切片失败只损失该回合的评测素材，不拖垮会话/其余切片
        try:
            path = save_clip(self.session_id, seq, pcm)
            ingest_clip(
                self.session_id,
                path,
                start_ts=round(start_ts, 3),
                end_ts=round(end_ts, 3),
            )
        except Exception:
            logger.exception(
                "tee 切片 ingest 失败: session=%s seq=%s", self.session_id, seq
            )
