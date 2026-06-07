"""题库 TTS 预生成（IELTS.md §3：题目朗读音频离线生成，运行时零 TTS 调用）。

用法：`uv run python -m app.tts`（增量：已存在的 {id}.wav 跳过；--force 全量重生成）。
产物：data/tts/{id}.wav（24kHz/16-bit/mono，Gemini TTS 输出格式直封 WAV 头）。
GET /questions 按文件存在性回填 tts_url（免重启）；未生成时前端纯文字读题降级。
data/tts/ 为运行时生成物，gitignore 不入库。
"""

import argparse
import logging
import sys
import time
import wave

from google.genai import errors, types

from app.api.questions import TTS_DIR, VALID_PARTS, _load_bank
from app.config import settings
from app.judge.run import _client  # 复用懒加载单例（同一 API key / 代理配置）

logger = logging.getLogger(__name__)

# Gemini TTS 输出规格：24kHz / 16-bit / mono PCM（SDK 文档固定值）
TTS_SAMPLE_RATE = 24000

# 考官读题音色（demo 固定一个稳重声线，保持全题库一致）
TTS_VOICE = "Kore"

# 免费档配额 10 次/分钟（实测 429）：主动节流到 ~9 次/分，撞限再按建议延迟重试
TTS_THROTTLE_S = 6.5
TTS_429_RETRY_S = 15
TTS_429_MAX_RETRIES = 3


def compose_tts_text(question: dict) -> str:
    """题目 → 考官朗读文本：一律只读题面（方式 B 对齐拍板 D4/D5，2026-06-07）。

    p2 cue card 的 bullets 不口播——卡片上展示即可，与 live 考官同规
    （persona：bullets 在考生卡上、考官不念）；不加引导句式/考官口吻
    （裸题直读，刷题高效）。改动后 p2 旧音频需删除重生成（增量脚本只补缺）。
    """
    return question["text"]


def synthesize(text: str) -> bytes:
    """调一次 Gemini TTS，返回 24k/16-bit/mono 裸 PCM。"""
    resp = _client().models.generate_content(
        model=settings.tts_model,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
                )
            ),
        ),
    )
    # 防御取数：安全过滤/异常 finish 时 candidates/content 可为空，给出真实原因
    if not resp.candidates or resp.candidates[0].content is None:
        raise RuntimeError(f"TTS 响应无 candidates/content（可能被安全过滤）：{text[:50]!r}")
    part = resp.candidates[0].content.parts[0]
    data = part.inline_data and part.inline_data.data
    if not data:
        raise RuntimeError(f"TTS 未返回音频数据：{text[:50]!r}")
    return data


def write_wav(path, pcm: bytes) -> None:
    """裸 PCM 封 WAV 头落盘（24k/16-bit/mono）。"""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TTS_SAMPLE_RATE)
        w.writeframes(pcm)


def generate_all(*, force: bool = False) -> dict[str, int]:
    """逐题生成（增量幂等：已存在跳过，除非 force）。返回 {generated, skipped, failed}。

    单题失败只记日志继续——tts_url 对缺失文件诚实回 null，前端纯文字降级，
    一题失败不该拖死整个题库的音频。
    """
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"generated": 0, "skipped": 0, "failed": 0}
    for part in sorted(VALID_PARTS):
        for q in _load_bank()[part]:
            out = TTS_DIR / f"{q['id']}.wav"
            if out.exists() and not force:
                stats["skipped"] += 1
                continue
            try:
                pcm = _synthesize_with_quota_retry(compose_tts_text(q))
                write_wav(out, pcm)
                stats["generated"] += 1
                logger.info("TTS 生成: %s（%.1fs）", out.name, len(pcm) / 2 / TTS_SAMPLE_RATE)
                time.sleep(TTS_THROTTLE_S)   # 主动节流贴着 10/min 配额走
            except Exception:
                stats["failed"] += 1
                logger.exception("TTS 生成失败（跳过继续）: %s", q["id"])
    return stats


def _synthesize_with_quota_retry(text: str) -> bytes:
    """合成一题；429（配额/分钟限）按固定延迟重试，其余异常原样上抛。"""
    for attempt in range(TTS_429_MAX_RETRIES + 1):
        try:
            return synthesize(text)
        except errors.ClientError as e:
            if e.code != 429 or attempt == TTS_429_MAX_RETRIES:
                raise
            logger.warning("TTS 429 配额限，%ss 后重试（%d/%d）",
                           TTS_429_RETRY_S, attempt + 1, TTS_429_MAX_RETRIES)
            time.sleep(TTS_429_RETRY_S)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="题库 TTS 预生成")
    parser.add_argument("--force", action="store_true", help="忽略已存在文件全量重生成")
    args = parser.parse_args()
    result = generate_all(force=args.force)
    print(f"完成：生成 {result['generated']} / 跳过 {result['skipped']} / 失败 {result['failed']}")
    sys.exit(1 if result["failed"] else 0)
