"""LatencyMeter 单测（假时钟，确定性）：停说采点 × 轮次相位 × 一轮一次。"""

from app.live.latency import SILENCE_THRESHOLD, LatencyMeter, has_speech

LOUD = b"\x00\x08" * 100      # 采样值 0x0800=2048 > 阈值
QUIET = b"\x01\x00" * 100     # 采样值 1 < 阈值（接近全静音）


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


# ---------- has_speech ----------


def test_has_speech_threshold():
    assert has_speech(LOUD)
    assert not has_speech(QUIET)
    assert not has_speech(b"")
    assert not has_speech(b"\x01")                    # 奇数字节裁掉后不足一个采样
    # 负向满幅也算语音（取绝对值）
    assert has_speech(b"\x00\x80" * 4)                # -32768
    boundary = SILENCE_THRESHOLD.to_bytes(2, "little", signed=True)
    assert has_speech(boundary * 4)                   # 恰到阈值（≥）


# ---------- natural：最后非静音帧近似 ----------


def test_natural_marks_last_speech_frame():
    clock = FakeClock()
    m = LatencyMeter("natural", clock)

    m.on_user_frame(LOUD)
    clock.now = 1.0
    m.on_user_frame(LOUD)         # 停说点刷新到 1.0
    clock.now = 1.5
    m.on_user_frame(QUIET)        # 尾部静音帧不刷新（用户已停说）
    clock.now = 2.0
    assert m.on_model_audio() == 1000   # 2.0 - 1.0
    assert m.on_model_audio() is None   # 一轮只出一次


def test_natural_echo_during_examiner_phase_not_marked():
    clock = FakeClock()
    m = LatencyMeter("natural", clock)
    m.on_user_frame(LOUD)
    clock.now = 0.5
    assert m.on_model_audio() == 500
    # 考官相位中的麦克风回声不采点
    clock.now = 1.0
    m.on_user_frame(LOUD)
    m.on_turn_taken_back()
    clock.now = 2.0
    # 考官连说（上一轮归还后用户没说话）：无停说点，不出数
    assert m.on_model_audio() is None


def test_natural_second_round_measures_again():
    clock = FakeClock()
    m = LatencyMeter("natural", clock)
    m.on_user_frame(LOUD)
    clock.now = 1.0
    assert m.on_model_audio() == 1000
    m.on_turn_taken_back()
    clock.now = 5.0
    m.on_user_frame(LOUD)
    clock.now = 5.25
    assert m.on_model_audio() == 250


# ---------- ptt：turn_end 为准 ----------


def test_ptt_uses_turn_end_not_frames():
    clock = FakeClock()
    m = LatencyMeter("ptt", clock)
    m.on_user_frame(LOUD)         # ptt 不看帧幅值
    clock.now = 1.0
    m.on_turn_end()               # 松开按键 = 停说时刻
    clock.now = 1.25
    assert m.on_model_audio() == 250


def test_ptt_examiner_first_turn_no_value():
    clock = FakeClock()
    m = LatencyMeter("ptt", clock)
    assert m.on_model_audio() is None   # 考官先开口（雅思开场）：无停说点
    m.on_turn_taken_back()
    m.on_turn_end()
    clock.now = 0.4
    assert m.on_model_audio() == 400
