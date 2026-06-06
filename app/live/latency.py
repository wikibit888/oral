"""考官响应延迟测量（延迟徽章，FRONTEND §5 latency_ms 事件）。

延迟 = 用户停止说话 → 考官第一帧音频到达。停说时刻按轮次模式取：
- ptt：turn_end 控制消费瞬间——显式信号，精确；
- natural：最后一个**非静音**上行帧的到达时刻近似——VAD 断轮没有显式信号，
  尾部静音帧不算（用户已停说，只是 VAD 还没判完）。

相位机（与 tee 地板同构但独立——延迟是传输/UX 关心点，不依赖评测开关）：
用户相位中采点；考官首帧音频出延迟并转考官相位（一轮只出一次）；
turn_complete / interrupted 回用户相位。
"""

import time
from array import array

# int16 幅值低于此视作静音帧（正常语音峰值通常 >2000，环境底噪 <300）
SILENCE_THRESHOLD = 500


def has_speech(data: bytes, threshold: int = SILENCE_THRESHOLD) -> bool:
    """近似语音检测：帧内任一采样幅值过阈即认为有语音（16-bit LE PCM）。"""
    usable = len(data) - (len(data) % 2)
    if usable < 2:
        return False
    samples = array("h", data[:usable])
    return max(max(samples), -min(samples)) >= threshold


class LatencyMeter:
    """单连接的延迟测量；bridge 泵内同步调用（只动内存，无 await 点）。"""

    def __init__(self, turn_mode: str, clock=time.monotonic) -> None:
        self._ptt = turn_mode == "ptt"
        self._clock = clock
        self._user_phase = True
        self._mark: float | None = None    # 用户停说时刻候选

    def on_user_frame(self, data: bytes) -> None:
        """natural：用户相位中的非静音帧持续刷新停说时刻；ptt 不看帧。"""
        if self._ptt or not self._user_phase:
            return
        if has_speech(data):
            self._mark = self._clock()

    def on_turn_end(self) -> None:
        """ptt：松开按键（turn_end 消费瞬间）即停说时刻。"""
        if self._ptt and self._user_phase:
            self._mark = self._clock()

    def on_model_audio(self) -> int | None:
        """考官音频帧。首帧返回延迟毫秒数（无采点则 None），转考官相位；后续帧 None。"""
        if not self._user_phase:
            return None
        self._user_phase = False
        if self._mark is None:
            return None     # 考官先开口（雅思开场）等没有用户停说点的轮次
        ms = round((self._clock() - self._mark) * 1000)
        self._mark = None
        return ms

    def on_turn_taken_back(self) -> None:
        """turn_complete / interrupted：地板归还用户，下一轮重新采点。"""
        self._user_phase = True
