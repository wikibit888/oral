"""情景 case 注册表单测：persona / judge_focus 内容契约 + 全链推导一致性。

prompt 是数据不是逻辑，单测 pin 的是**契约要点**（守角色 / 话少 / 自然收尾 /
方括号导演提示规则 / 禁切语言），不逐字 pin 文案——文案微调不该崩测试。
"""

from app.api.live_ws import VALID_SCENARIO_CASES
from app.judge.prompt import build_judge_prompt
from app.scenario_cases import CASES, judge_focus


def test_registry_covers_planned_cases():
    # PRD：先做点餐 + 会议两个 case
    assert set(CASES) == {"ordering", "meeting"}


def test_ws_whitelist_derived_from_registry():
    # 加 case 只改注册表，/ws/live 白名单自动跟随（SCENARIO.md §2）
    assert VALID_SCENARIO_CASES == frozenset(CASES)


def test_personas_share_conversation_contract():
    for name, case in CASES.items():
        p = " ".join(case.persona.split())   # 归一化折行，契约检查与排版无关
        # 方括号导演提示规则：ask_help 破壁（下个 PR）与自然收尾注入的前置
        assert "[square brackets]" in p and "stage directions" in p, name
        assert "NEVER read them aloud" in p, name
        # 话少 + 一次一问：用户才是说话主体
        assert "ONE" in p and "most of the talking" in p, name
        # 自然收尾指引（用户手动 End，对话本身要能体面结束）
        assert "naturally" in p, name
        # 卡壳 / 夹杂非英语时不切语言（破壁前的默认行为）
        assert "Never switch out of English" in p, name


def test_openers_contract():
    """开场模板契约：每 case ≥2 条（随机抽有意义）、方括号舞台指令形态、
    收尾于一个引导性问题（AI 说完用户知道接什么）。"""
    for name, case in CASES.items():
        assert len(case.openers) >= 2, name
        for opener in case.openers:
            o = " ".join(opener.split())
            assert o.startswith("[Stage direction:"), name
            assert o.endswith("]"), name
            # 「现在就开口」意图：不 pin 具体动词（Open/Start/Begin 均可，
            # 加 case 只写文本不该被措辞卡住），只查即时性信号词
            assert " now" in o, name
            assert "only that one question" in o, name        # 一个引导性问题收尾
    assert set(CASES["ordering"].openers).isdisjoint(CASES["meeting"].openers)


def test_cases_are_distinct_roles():
    assert "restaurant" in CASES["ordering"].persona
    assert "meeting" in CASES["meeting"].persona
    assert "点餐" in CASES["ordering"].judge_focus
    assert "会议" in CASES["meeting"].judge_focus
    assert CASES["ordering"].judge_focus != CASES["meeting"].judge_focus


def test_judge_focus_lookup():
    assert judge_focus("ordering") == CASES["ordering"].judge_focus
    assert judge_focus(None) is None         # 非情景会话
    assert judge_focus("bogus") is None      # 未知 case 降级（prompt 层有占位）


def test_case_focus_reaches_judge_prompt():
    # 注册表侧重段进入 judge prompt，不再落 P5 占位提示
    prompt = build_judge_prompt(
        "scenario",
        transcript_text="I would like a steak, medium rare please.",
        signals={},
        scenario_case="ordering",
        case_prompt=judge_focus("ordering"),
    )
    assert "点餐场景侧重" in prompt
    assert "P5 注入" not in prompt
