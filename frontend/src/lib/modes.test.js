import { describe, it, expect } from 'vitest'
import {
  IELTS_PARTS,
  MODE_IELTS,
  MODE_SCENARIO,
  SUB_MODE_EXAM,
  SCENARIO_CASES,
  scenarioLabel,
} from './modes.js'

// Contract pins: these strings MUST equal the backend's VALID_MODES /
// VALID_SUB_MODES / VALID_SCENARIO_CASES (app/api/recordings.py). If this test
// fails, someone drifted from the contract — fix the frontend, never the backend.
describe('backend contract pins', () => {
  it('modes match VALID_MODES', () => {
    expect(MODE_IELTS).toBe('ielts')
    expect(MODE_SCENARIO).toBe('scenario')
  })

  it('ielts sub_modes match VALID_SUB_MODES', () => {
    expect(IELTS_PARTS.map((p) => p.value)).toEqual(['module_p1', 'module_p2', 'module_p3'])
    expect(SUB_MODE_EXAM).toBe('exam')
  })

  it('scenario cases match VALID_SCENARIO_CASES', () => {
    expect(SCENARIO_CASES.map((c) => c.value)).toEqual(['ordering', 'meeting'])
  })

  it('case label 简洁英文（FRONTEND §4 / handoff 006）；契约外回退原值', () => {
    expect(SCENARIO_CASES.map((c) => c.label)).toEqual(['Ordering Food', 'Work Meeting'])
    expect(scenarioLabel('ordering')).toBe('Ordering Food')
    expect(scenarioLabel('nope')).toBe('nope')
  })
})
