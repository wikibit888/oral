"""情景 case 注册表单测：persona / judge_focus 内容契约 + 全链推导一致性。

prompt 是数据不是逻辑，单测 pin 的是**契约要点**（守角色 / 话少 / 自然收尾 /
方括号导演提示规则 / 禁切语言 / 教练协议 / 控制指令响应），不逐字 pin 文案——
文案微调不该崩测试。教练协议与控制指令的边际依据：docs/SCENARIO_CASE.md。
"""

from app.api.live_ws import VALID_SCENARIO_CASES
from app.judge.prompt import build_judge_prompt
from app.scenario_cases import (
    _SHARED_RULES,
    CASES,
    GRAMMAR_AFTER_HELP_DIRECTIVE,
    GRAMMAR_SILENT_DIRECTIVE,
    GRAMMAR_SPEAK_DIRECTIVES,
    HELP_DIRECTIVES,
    HELP_OVERUSE_DIRECTIVE,
    NUDGE_DIRECTIVES,
    judge_focus,
    language_help_tool,
)


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


def test_personas_compose_shared_rules():
    # persona = 场景差异段 + 共享规则段：共享段全 case 同一份（一处修正全员生效），
    # 场景段在前（角色定位先入为主）
    for name, case in CASES.items():
        assert case.persona.endswith(_SHARED_RULES), name
        assert not case.persona.startswith(_SHARED_RULES), name


def test_personas_coach_protocol():
    """教练协议契约（SCENARIO_CASE.md A/B 类）：recast / 整句中文等复述 /
    显式求助给词 + 场景例句 / 教学英文一句话、示范优先。"""
    for name, case in CASES.items():
        p = " ".join(case.persona.split())
        # 帽子切换总闸：出戏至多一两句、说完立刻回场景（与守角色规则的
        # "stepping out only briefly to coach" 互为引用，不自相矛盾）
        assert "one or two short English sentences" in p, name
        assert "return to the scene" in p, name
        assert "stepping out only briefly" in p, name
        # A2 夹中文 → recast 不打断（不变成翻译练习：只补实词）
        assert "recast" in p, name
        assert "key content words" in p, name
        # A1 整句中文 → 给示范 + 等用户自己说（不替说完推剧情）
        assert "whole sentence in Chinese" in p, name
        assert "invite them to try" in p, name
        # A4/C3 显式求助（中英文问法同协议）→ 给词 + 场景例句；A3 语境选词
        assert "How do I say" in p, name
        assert "example sentence" in p, name
        assert "one or two" in p, name
        # B1 教学一律英文、一句话量级、示范优先于讲解
        assert "in English" in p, name
        assert "demonstrate" in p, name


def test_personas_control_requests():
    """控制指令契约（SCENARIO_CASE.md C 类）：立即照做后接回原剧情点。"""
    for name, case in CASES.items():
        p = " ".join(case.persona.split())
        # C1 慢/重复/换说法——换说法要真降难度
        assert "Slower" in p and "simpler words" in p, name
        # C2 解释上一句 → 回被打断点，不重启场景
        assert "What does that mean" in p, name
        assert "where it was interrupted" in p, name
        # C4 难度调整即时生效并保持
        assert "Too hard / too easy" in p, name
        assert "keep the new level" in p, name
        # C5 口头暂停 / 重开当前场景
        assert "pause" in p and "start over" in p, name
        # C6 无关问题一句话作答、不展开、自然带回
        assert "unrelated to the scene" in p, name
        assert "ONE short sentence" in p, name


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


def test_language_help_tool_contract():
    """情景教练 tool 契约（双声明）：language_help（求助）+ grammar_note（纠错检出）；
    名称 / 必填参数 / kind 枚举与指令模板库一一对应；{scene} 槽已填场景标签。"""
    for case in CASES:
        tool = language_help_tool(case)
        label = CASES[case].scene_label
        decls = tool["function_declarations"]
        assert [d["name"] for d in decls] == ["language_help", "grammar_note"], case
        help_decl, grammar_decl = decls
        # —— language_help —— #
        params = help_decl["parameters"]
        assert set(params["required"]) == {"kind", "chinese", "english", "example"}
        # kind 枚举 = 模板库的键：模型传什么 kind，应答台就查得到什么模板
        assert set(params["properties"]["kind"]["enum"]) == set(HELP_DIRECTIVES)
        # 模型自带翻译进来（分工反转的核心约定）
        assert "Translate it yourself" in help_decl["description"], case
        # case 注入：场景标签进描述（选词/例句锚定当前场景）
        assert label in help_decl["description"], case
        assert label in params["properties"]["english"]["description"], case
        assert label in params["properties"]["example"]["description"], case
        # —— grammar_note：出现即报（用户决策），口语省略豁免、每轮至多一条 —— #
        gparams = grammar_decl["parameters"]
        assert set(gparams["required"]) == {"original", "fixed", "note"}
        # 对照式纠正的参数约束：original 逐字且短、fixed 同片段最小修正
        assert "verbatim" in gparams["properties"]["original"]["description"]
        assert "keep it short" in gparams["properties"]["original"]["description"]
        assert "minimal change" in gparams["properties"]["fixed"]["description"]
        assert "casual spoken shortcuts" in grammar_decl["description"], case
        assert "ONE error per turn" in grammar_decl["description"], case
        # 整句中文轮不调（中文句没有英语语法可纠）
        assert "Never call it for a sentence spoken in Chinese" in grammar_decl["description"]
        assert label in grammar_decl["description"], case
        # 全 tool 无残留槽
        assert "{scene}" not in str(tool), case
    # 两 case 的声明确实不同（场景标签注入生效）
    assert language_help_tool("ordering") != language_help_tool("meeting")


def test_language_help_tool_returns_fresh_copy():
    # 每次调用独立深拷贝：调用方/SDK 原地改动不污染模板常量
    a, b = language_help_tool("ordering"), language_help_tool("ordering")
    assert a == b and a is not b
    a["function_declarations"][0]["name"] = "mutated"
    assert language_help_tool("ordering")["function_declarations"][0]["name"] == (
        "language_help"
    )


def test_scene_labels_contract():
    # 英文短标签、带定冠词（模板 {scene} 槽语法依赖）、两 case 不同
    for name, case in CASES.items():
        assert case.scene_label.startswith("the "), name
        assert case.scene_label.isascii(), name
    assert CASES["ordering"].scene_label != CASES["meeting"].scene_label


def test_help_directives_contract():
    """指令模板契约：每 kind ≥2 条轮换；槽位只用 {english}/{example}/{scene}。"""
    for kind, variants in HELP_DIRECTIVES.items():
        assert len(variants) >= 2, kind
        for t in variants:
            assert "{english}" in t, kind        # 至少回填目标说法
            residue = (
                t.replace("{english}", "")
                .replace("{example}", "")
                .replace("{scene}", "")
            )
            assert "{" not in residue, kind      # 无未知槽位（replace 填不上会念出来）
    assert "{english}" in HELP_OVERUSE_DIRECTIVE
    assert "{" not in HELP_OVERUSE_DIRECTIVE.replace("{english}", "").replace(
        "{scene}", ""
    )


def test_grammar_directives_contract():
    """口头纠错指令三态契约（B1 + 用户决策的顺序/对照/控频规则）：
    说=回答最前对照纠正（say {fixed}, not {original}）、与中文同轮=放中文之后、
    静默=只入卡片不开口。"""
    # 说（单独）：≥2 变体轮换；对照式——正确形式在前、错误在后
    assert len(GRAMMAR_SPEAK_DIRECTIVES) >= 2
    for d in GRAMMAR_SPEAK_DIRECTIVES:
        assert "{fixed}" in d and "{original}" in d
        assert d.index("{fixed}") < d.index("{original}")   # say X, not Y 顺序
    assert "Before answering in character" in GRAMMAR_SPEAK_DIRECTIVES[0]
    # 说（与中文求助同轮）：中文应答之后，同样对照
    assert "Chinese language help first" in GRAMMAR_AFTER_HELP_DIRECTIVE
    assert "{fixed}" in GRAMMAR_AFTER_HELP_DIRECTIVE
    assert "{original}" in GRAMMAR_AFTER_HELP_DIRECTIVE
    # 静默：控频压掉 / recast 已覆盖时不开口
    assert "Do not mention this error" in GRAMMAR_SILENT_DIRECTIVE
    assert "{fixed}" not in GRAMMAR_SILENT_DIRECTIVE
    # 槽位只用 {fixed}/{original}/{scene}
    for d in (
        *GRAMMAR_SPEAK_DIRECTIVES,
        GRAMMAR_AFTER_HELP_DIRECTIVE,
        GRAMMAR_SILENT_DIRECTIVE,
    ):
        residue = (
            d.replace("{fixed}", "").replace("{original}", "").replace("{scene}", "")
        )
        assert "{" not in residue


def test_nudge_directives_contract():
    """D1 分级探询模板契约：三级渐进、方括号舞台指令形态、暂停互斥内置、
    槽位只用 {scene}（SCENARIO_CASE.md D1 + C5）。"""
    assert set(NUDGE_DIRECTIVES) == {1, 2, 3}
    for stage, d in NUDGE_DIRECTIVES.items():
        assert d.startswith("[Stage direction:"), stage
        assert d.endswith("]"), stage
        # C5 互斥：用户此前要求暂停则继续沉默（模型用上下文裁决）
        assert "pause" in d and "silent" in d, stage
        assert "{" not in d.replace("{scene}", ""), stage   # 无未知槽位
    # 分级语义：① 轻提示不教内容 ② 给句头 ③ 给选项 + 确认是否继续
    assert "check in" in NUDGE_DIRECTIVES[1]
    assert "starter" in NUDGE_DIRECTIVES[2]
    assert "continue" in NUDGE_DIRECTIVES[3]


def test_personas_wired_to_coach_tools():
    # persona 指挥模型调双 tool 并照 directive 行事；persona 默认条款保留为兜底
    for name, case in CASES.items():
        p = " ".join(case.persona.split())
        assert "language_help" in p, name
        assert "grammar_note" in p, name
        # 纠错规则进 persona：出现即调（口语省略豁免）、每轮至多一条
        assert "grammar or word-choice mistake" in p, name
        assert "at most one per turn" in p, name
        assert "follow the directive" in p, name
        assert "If the functions are unavailable" in p, name


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
