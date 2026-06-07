// Fixtures mirroring the FROZEN Report schema (app/report.py / PRD §6.2). They
// let the report page be built + demoed with zero backend dependency
// (TODO.frontend F2). Two shapes: IELTS (with 4-dim band + overall) and Scenario
// (dimensions/overall_band = null — 情景不出 band).

export const ieltsReport = {
  practice_summary: { speaking_time_s: 132.4, sessions: 1, recordings: 3 },
  overall_band: 6.5,
  unscorable: false,
  unscorable_reason: null,
  dimensions: {
    fluency_coherence: {
      band: 6.0,
      evidence: [
        "I think... I think the main reason is, um, because of the technology",
        "and then, you know, people they start to, to use it everyday",
      ],
      descriptor_match:
        "命中 band 6「willing to speak at length, though may lose coherence」；卡在 band 7 的「speaks fluently with only occasional repetition」——重复与填充词偏多。",
      suggestions: [
        "用 first / then / as a result 等连接词替代 'and then' 串句",
        "录音前花 30 秒列 2–3 个要点，减少中途卡顿",
      ],
    },
    lexical_resource: {
      band: 6.5,
      evidence: [
        "it's a kind of convenient way to communicate",
        "the impact on society is quite significant",
      ],
      descriptor_match:
        "命中 band 6–7「resource flexible enough to discuss a variety of topics」；搭配多样性不足，卡在 band 7 上界。",
      suggestions: [
        "把 'significant' 扩成搭配：a profound impact / far-reaching consequences",
        "积累话题词族（technology: cutting-edge, obsolete, accessibility）",
      ],
    },
    grammatical_range_accuracy: {
      band: 6.5,
      evidence: [
        "if I would have more time, I will practice more",
        "there are many people uses this app",
      ],
      descriptor_match:
        "命中 band 6「mix of simple and complex structures with some errors」；条件句与主谓一致仍有硬错，卡在 band 7。",
      suggestions: [
        "复习第二条件句：If I had more time, I would practice more",
        "主谓一致：many people use（复数主语用动词原形）",
      ],
    },
    pronunciation: {
      band: 7.0,
      evidence: [
        "clear articulation of 'technology' and 'communicate'",
        "occasional flat intonation on longer sentences",
      ],
      descriptor_match:
        "命中 band 7「easy to understand throughout；L1 口音对可懂度影响很小」；长句语调偏平可再提升。",
      suggestions: [
        "在长句重音词上加音高变化，避免整句平读",
        "注意词尾辅音 -ed / -s 的清晰度",
      ],
    },
  },
  diagnostics: {
    common_patterns: [
      { pattern: "以填充词 'um / you know' 开头", count: 9 },
      { pattern: "'and then' 串接长句", count: 6 },
      { pattern: "主谓一致错误", count: 4 },
    ],
    syntactic_analysis: {
      observation: "句式以并列简单句为主，复杂从句出现但常伴随时态 / 一致错误。",
      suggestion: "刻意练习 1–2 种复杂句式（条件句、定语从句），放慢语速保证准确度。",
    },
    frequent_errors: [
      { category: "语法", desc: "条件句结构混用（would + will）", count: 3 },
      { category: "语法", desc: "可数名词主谓一致", count: 4 },
      { category: "词汇", desc: "高频词复用、搭配单一", count: 5 },
    ],
    fossilized_errors: [
      {
        desc: "第二条件句主句误用 will 而非 would",
        occurrences: [
          "if I would have more time, I will practice",
          "if it is cheaper, I will buy it",
        ],
      },
    ],
    self_corrections: [
      { initial: "people they start to use", corrected: "people start to use" },
      { initial: "more convenienter", corrected: "more convenient" },
    ],
    vocabulary_diversity_pct: 48.6,
    top_priorities: [
      {
        title: "修正第二条件句",
        severity: "high",
        explanation: "假设语气主句反复用 will，限制准确度维度上探到 band 7。",
        examples: ["if I would have more time, I will practice more"],
        quick_fix: "公式记忆：If + 过去式, would + 动词原形。",
      },
      {
        title: "减少填充词与 'and then' 串句",
        severity: "medium",
        explanation: "高频填充词与并列串句拉低流利度与连贯。",
        examples: ["um, you know, and then people they..."],
        quick_fix: "用连接词替换，并在开口前默列要点。",
      },
      {
        title: "丰富搭配与话题词汇",
        severity: "low",
        explanation: "词汇多样性偏低（48.6%），搭配单一限制词汇维度。",
        examples: ["a convenient way", "quite significant"],
        quick_fix: "每个话题准备 5 个高阶搭配，主动替换高频词。",
      },
    ],
    rewrites: [
      {
        original: "If I would have more time, I will practice more.",
        rewrite: "If I had more time, I would practice more.",
        reason: "第二条件句：条件用过去式，主句用 would + 原形。",
      },
      {
        original: "There are many people uses this app and then they like it.",
        rewrite: "Many people use this app, and as a result they enjoy it.",
        reason: "修正主谓一致，用 as a result 替代 'and then' 串句。",
      },
    ],
    summary: null, // 雅思恒 null（后端强制剥除，handoff 014）——显式置 null 对齐 shape，防 undefined 分叉
  },
};

// 雅思方式 B（分模块）：descriptor 对齐诊断但**无数字 band**（IELTS.md §3）——
// dimensions / overall_band 置空、unscorable=false，与情景共用"无 band"渲染分支。
// 也是 F3 mock 模式 Get Review 后的落点（/report/demo-ielts-b）。
export const ieltsModuleReport = {
  practice_summary: { speaking_time_s: 95.7, sessions: 1, recordings: 3 },
  dimensions: null, // 方式 B 不出 band（设计如此，区别于 unscorable）
  overall_band: null,
  unscorable: false,
  unscorable_reason: null,
  diagnostics: {
    common_patterns: [
      { pattern: "回答以 'I think maybe' 开头", count: 7 },
      { pattern: "短答后不展开（缺 because / for example）", count: 5 },
    ],
    syntactic_analysis: {
      observation:
        "Part 1 短答以简单句为主，符合 band 6 descriptor「willing to give extended answers but limited complexity」——回答长度够但从句少。",
      suggestion: "每题至少给一个 because 从句或 for example 展开，把短答拉成 2–3 句。",
    },
    frequent_errors: [
      { category: "语法", desc: "一般现在时第三人称 -s 脱落", count: 4 },
      { category: "词汇", desc: "形容词单一（nice / good 高频复用）", count: 6 },
      { category: "发音", desc: "词尾辅音 /t/ /d/ 吞音，影响清晰度", count: 3 },
    ],
    fossilized_errors: [
      {
        desc: "hometown 相关表达持续漏冠词",
        occurrences: ["I come from small city", "it is very famous place"],
      },
    ],
    self_corrections: [{ initial: "it have many", corrected: "it has many" }],
    vocabulary_diversity_pct: 44.3,
    top_priorities: [
      {
        title: "短答展开成 2–3 句",
        severity: "high",
        explanation:
          "descriptor「gives extended answers」是 Part 1 的核心要求，单句短答压低流利与连贯证据量。",
        examples: ["Yes, I like it."],
        quick_fix: "公式：观点 + because + 一个具体例子。",
      },
      {
        title: "替换 nice / good",
        severity: "medium",
        explanation: "形容词复用限制词汇面，descriptor 要求「flexible enough to discuss topics」。",
        examples: ["it is a nice place, the food is nice"],
        quick_fix: "每个话题备 3 个精确形容词（vibrant / historic / laid-back）。",
      },
    ],
    rewrites: [
      {
        original: "I come from small city, it is very famous place for food.",
        rewrite: "I come from a small city, which is quite famous for its food.",
        reason: "补冠词 + which 从句串接，单句升级为复杂句。",
      },
    ],
    summary: null, // 雅思（方式 B 同样）恒 null（handoff 014）
  },
};

// 雅思不可评（静音/非英语，judge 依 grounding 铁律拒评）：band 全 null +
// unscorable=true + 诊断层近空结构 —— G3 渲染分支的零后端预览（/report/demo-unscorable）。
export const unscorableReport = {
  practice_summary: { speaking_time_s: 31.0, sessions: 1, recordings: 1 },
  dimensions: null,
  overall_band: null,
  unscorable: true,
  unscorable_reason:
    '录音几乎为静音，未识别出有效英语语音，无法可靠评分。请在安静环境靠近麦克风重录。',
  diagnostics: {
    common_patterns: [],
    syntactic_analysis: {
      observation: '有效语音过少，无法分析句式结构。',
      suggestion: '确认麦克风正常工作后重录，建议至少连续说 30 秒。',
    },
    frequent_errors: [],
    fossilized_errors: [],
    self_corrections: [],
    vocabulary_diversity_pct: 0,
    top_priorities: [],
    rewrites: [], // 空列表 → 改写示范整节隐藏（014 按内容显隐，unscorable 受益分支）
    summary: null,
  },
};

export const scenarioReport = {
  practice_summary: { speaking_time_s: 86.2, sessions: 1, recordings: 1 },
  dimensions: null, // 情景不出 band（设计如此，区别于 unscorable）
  overall_band: null,
  unscorable: false,
  unscorable_reason: null,
  diagnostics: {
    common_patterns: [
      { pattern: "点单时省略冠词（'I want burger'）", count: 5 },
      { pattern: "用 'give me' 直述请求，礼貌度偏低", count: 4 },
    ],
    syntactic_analysis: {
      observation: "请求多为祈使句直述，缺少 could / would 软化结构。",
      suggestion: "练习 'Could I have… / I'd like… / Would it be possible to…' 三个点餐高频句型。",
    },
    frequent_errors: [
      { category: "冠词", desc: "可数名词前漏 a / the", count: 5 },
      { category: "语用", desc: "请求未软化，显得生硬", count: 4 },
      { category: "词汇", desc: "menu / order 相关词汇有限", count: 3 },
    ],
    fossilized_errors: [
      {
        desc: "可数名词单数前持续漏冠词",
        occurrences: ["I want burger", "can I get coffee"],
      },
    ],
    self_corrections: [
      { initial: "give me the, the chicken", corrected: "Could I have the chicken" },
    ],
    vocabulary_diversity_pct: 41.2,
    top_priorities: [
      {
        title: "用软化句型替代直述请求",
        severity: "high",
        explanation: "点餐场景里 'give me' 偏生硬，影响得体度。",
        examples: ["give me a coke", "I want burger"],
        quick_fix: "固定替换：Could I have… / I'd like…",
      },
      {
        title: "补齐可数名词冠词",
        severity: "medium",
        explanation: "单数可数名词前持续漏 a/the，是石化错误。",
        examples: ["I want burger", "can I get coffee"],
        quick_fix: "点单名词前默念 a / an / the。",
      },
    ],
    // 情景不出改写示范（rewrites 后端强制空列表——会话内 grammar_note 纠错
    // 卡片已承担逐句纠正）；summary 仅情景非空（handoff 014）
    rewrites: [],
    summary:
      "全程主动完成点单、应答不冷场，交流意愿很好。主要问题是请求句式偏生硬——'give me' 直述最高频，可数名词冠词（a burger / a coke）也持续缺失。下次开口优先用 Could I have… / I'd like… 软化句型，并在点单名词前默念 a / the，礼貌度和准确度都会立刻上一个台阶。",
  },
};
