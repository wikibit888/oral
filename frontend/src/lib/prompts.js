// 录音页（F3）的静态题目/cue card 数据 — demo 固定一套；正式产品应由题库下发。
// key 必须与 lib/modes.js 镜像的后端契约串一致，prompts.test.js pin 住防漂移。
import { MODE_IELTS, MODE_SCENARIO } from './modes.js'

export const IELTS_PROMPTS = {
  module_p1: {
    title: 'Part 1 · Hometown',
    intro: '考官就熟悉话题快问快答。依次回答下面的问题，每题说 2–3 句：',
    questions: [
      'Where is your hometown?',
      'What do you like most about it?',
      'Has your hometown changed much in recent years?',
    ],
  },
  module_p2: {
    title: 'Part 2 · Cue Card',
    intro: '先在心里准备 1 分钟（可列要点），然后围绕卡片连续讲 1–2 分钟：',
    cueCard: {
      topic: 'Describe a skill you would like to learn.',
      bullets: [
        'what the skill is',
        'why you want to learn it',
        'how you would learn it',
        'and explain how it would help you',
      ],
    },
  },
  module_p3: {
    title: 'Part 3 · Discussion',
    intro: '考官就 Part 2 话题深入追问。给出有论证的展开回答：',
    questions: [
      'Why do some people give up learning new skills quickly?',
      'Should schools focus more on practical skills?',
      'How has technology changed the way people learn?',
    ],
  },
}

export const SCENARIO_PROMPTS = {
  ordering: {
    title: '点餐 · At a Restaurant',
    intro: '你在一家西餐厅，服务员过来点单。用英语完成下面的任务：',
    tasks: [
      '询问招牌菜，点一份主菜和一杯饮品',
      '说明一个忌口（比如不要洋葱）',
      '礼貌地请服务员推荐甜品',
    ],
  },
  meeting: {
    title: '会议 · Project Update',
    intro: '你在项目周会上发言。用英语完成下面的任务：',
    tasks: [
      '汇报你这周完成了什么、卡在哪里',
      '向同事礼貌地提出一个请求（如帮忙 review）',
      '对一个你不同意的提议，委婉表达不同观点',
    ],
  },
}

// 按录音页 query 参数取题目；未命中返回 null（页面已挡未选定入口的情况）。
export function getPrompt(mode, subMode, scenarioCase) {
  if (mode === MODE_IELTS) return IELTS_PROMPTS[subMode] ?? null
  if (mode === MODE_SCENARIO) return SCENARIO_PROMPTS[scenarioCase] ?? null
  return null
}
