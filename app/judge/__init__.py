"""结构化 judge：prompt 组装（本 PR）+ Gemini 调用（后续 PR）。"""

from app.judge.prompt import build_judge_prompt, load_band_descriptors

__all__ = ["build_judge_prompt", "load_band_descriptors"]
