"""导入当前季雅思题库：joespeaking 季题文件 → 本项目 topic 分组 schema。

joespeaking 的 `/data/ielts-questions-*.json` 是 `const topics = [...]` 的 JS 壳,
每个 topic 仅 `{number, questions}`,不标 Part:
  - questions[0] 含 "describe a/..." 或 "you should say:" → Part2/3 话题
    (questions[0]=题卡,questions[1..]=Part3 追问)
  - 否则 → Part1 话题(questions 全是独立小问题)

本脚本去壳 + 推断 Part + 拆题卡(主干 / bullets) + 生成文件名安全 id,
产出 data/questions.json(新 schema,见下)。旧 data/questions.json(精选库)
若 data/questions_fallback.json 尚不存在则备份过去,作 §7"新库优先、精选回退"的回退源。

新 schema:
  { "season": "may-aug-2026",
    "p1":  [ {"topic_id","title","questions":[{"id","text"}]} ],
    "p2_3":[ {"topic_id","title",
              "cue_card":{"id","text","bullets":[...]},
              "part3":[{"id","text"}]} ] }

用法:
  uv run python scripts/import_ielts_season.py                       # 抓当前季默认版
  uv run python scripts/import_ielts_season.py --source /tmp/x.json  # 用本地文件
  uv run python scripts/import_ielts_season.py --season sep-dec-2026 # 换季

⚠️ 合规:题库为考生回忆机经(非官方),站点声明 ai-train=no;仅本地自用,勿公开/再分发。
"""

import argparse
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = _REPO_ROOT / "data"
DEFAULT_OUT = DATA_DIR / "questions.json"
FALLBACK_OUT = DATA_DIR / "questions_fallback.json"

DEFAULT_SEASON = "may-aug-2026"
DEFAULT_URL = "https://joespeaking.com/data/ielts-questions-may-aug-2026.json"
_UA = {"user-agent": "study-archiver/1.0 (personal use)"}

# id 必须文件名安全(既进 question_id 校验,又进 data/tts/{id}.wav 文件名)
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_P2_MARKERS = ("describe a", "describe an", "describe the", "you should say:")


def _read_source(source: str) -> str:
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers=_UA)
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (固定可信域)
            return resp.read().decode("utf-8")
    return Path(source).read_text(encoding="utf-8")


def _deshell(text: str) -> list[dict]:
    """去掉 `const topics = ` 前缀与结尾 `;`,解析为 topic 数组。"""
    body = text.strip()
    if body.startswith("const"):
        body = re.sub(r"^const\s+\w+\s*=\s*", "", body)
        body = re.sub(r";?\s*$", "", body)
    parsed = json.loads(body)
    # 兼容未来 {metadata, topics} 包裹
    return parsed["topics"] if isinstance(parsed, dict) and "topics" in parsed else parsed


def _is_part2(questions: list[str]) -> bool:
    return bool(questions) and any(m in questions[0].lower() for m in _P2_MARKERS)


def _title(number: str) -> str:
    return number.split(":", 1)[1].strip() if ":" in number else number.strip()


def split_cue_card(first: str) -> tuple[str, list[str]]:
    """题卡 → (主干, bullets)。"You should say:" 后逗号分隔为要点;无则 bullets 空。"""
    if "You should say:" not in first:
        return first.strip(), []
    main, rest = first.split("You should say:", 1)
    bullets = [b.strip() for b in rest.split(",") if b.strip()]
    return main.strip(), bullets


def convert(topics: list[dict], season: str) -> dict:
    out: dict = {"season": season, "p1": [], "p2_3": []}
    p1_n = p23_n = 0
    for topic in topics:
        title = _title(topic["number"])
        qs = topic["questions"]
        if _is_part2(qs):
            p23_n += 1
            nn = f"{p23_n:02d}"
            main, bullets = split_cue_card(qs[0])
            out["p2_3"].append({
                "topic_id": f"t{nn}",
                "title": title,
                "cue_card": {"id": f"s-p2-t{nn}", "text": main, "bullets": bullets},
                "part3": [
                    {"id": f"s-p3-t{nn}-q{m + 1:02d}", "text": q}
                    for m, q in enumerate(qs[1:])
                ],
            })
        else:
            p1_n += 1
            nn = f"{p1_n:02d}"
            out["p1"].append({
                "topic_id": f"p1-t{nn}",
                "title": title,
                "questions": [
                    {"id": f"s-p1-t{nn}-q{m + 1:02d}", "text": q}
                    for m, q in enumerate(qs)
                ],
            })
    return out


def _iter_ids(bank: dict):
    for t in bank["p1"]:
        for q in t["questions"]:
            yield q["id"]
    for t in bank["p2_3"]:
        yield t["cue_card"]["id"]
        for q in t["part3"]:
            yield q["id"]


def validate(bank: dict) -> None:
    ids = list(_iter_ids(bank))
    if len(ids) != len(set(ids)):
        raise ValueError("id 不唯一")
    bad = [i for i in ids if not _ID_RE.match(i)]
    if bad:
        raise ValueError(f"非文件名安全 id: {bad[:5]}")
    if not bank["p1"] or not bank["p2_3"]:
        raise ValueError("p1 或 p2_3 为空,导入异常")


def main() -> int:
    ap = argparse.ArgumentParser(description="导入当前季雅思题库 → topic 分组 schema")
    ap.add_argument("--source", default=DEFAULT_URL, help="季题文件 URL 或本地路径")
    ap.add_argument("--season", default=DEFAULT_SEASON, help="题季标签(写入 schema)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出路径")
    args = ap.parse_args()

    topics = _deshell(_read_source(args.source))
    bank = convert(topics, args.season)
    validate(bank)

    out_path = Path(args.out)
    # 备份旧精选库作回退(仅当回退文件尚不存在,避免被季文件覆盖)
    if out_path == DEFAULT_OUT and DEFAULT_OUT.exists() and not FALLBACK_OUT.exists():
        shutil.copyfile(DEFAULT_OUT, FALLBACK_OUT)
        print(f"已备份精选库 → {FALLBACK_OUT.name}")

    out_path.write_text(
        json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    n_p1 = sum(len(t["questions"]) for t in bank["p1"])
    n_p2 = len(bank["p2_3"])
    n_p3 = sum(len(t["part3"]) for t in bank["p2_3"])
    print(
        f"导入完成 [{args.season}] → {out_path.name}: "
        f"P1 {len(bank['p1'])}话题/{n_p1}题 · P2 {n_p2}卡 · P3 {n_p3}追问 "
        f"(共 {n_p1 + n_p2 + n_p3} 条待 TTS)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
