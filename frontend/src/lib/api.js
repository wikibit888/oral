// Thin fetch wrapper around the backend. In dev all calls go through the Vite
// proxy at `/api` (see vite.config.js), which strips the prefix and forwards to
// the FastAPI server on :8000 — so the frontend never hardcodes backend host or
// route names. The backend is a read-only contract here (TODO.frontend 硬规则).
const BASE = import.meta.env.VITE_API_BASE ?? '/api';

export class ApiError extends Error {
  constructor(status, detail) {
    super(`HTTP ${status}: ${detailText(detail)}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

// detail → 可读字符串。后端自抛的 HTTPException 是中文字符串可直接展示；
// 但 FastAPI 原生 422 校验错误的 detail 是 [{loc, msg, type}] 对象数组，
// String() 会变成 "[object Object]"（review W5）——取每项 msg 拼接。
export function detailText(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d?.msg ?? JSON.stringify(d)).join('；');
  }
  if (detail == null) return '未知错误';
  return JSON.stringify(detail);
}

// 导出给 lib/sessionApi.js（F3 会话化接口）复用，避免双份 fetch 封装。
export async function request(path, { method = 'GET', body, headers, signal } = {}) {
  const res = await fetch(`${BASE}${path}`, { method, body, headers, signal });
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

// POST /recordings — multipart WAV + form fields. Returns { id, status, ... }.
export function createRecording({ blob, mode, subMode, scenarioCase }) {
  const form = new FormData();
  form.append('audio', blob, 'recording.wav');
  form.append('mode', mode);
  if (subMode) form.append('sub_mode', subMode);
  if (scenarioCase) form.append('scenario_case', scenarioCase);
  return request('/recordings', { method: 'POST', body: form });
}

// GET /reports/{id} — { id, mode, status, report }. report is set only when
// status === 'done' (uploaded | processing | done | failed).
export function getReport(sessionId, { signal } = {}) {
  return request(`/reports/${sessionId}`, { signal });
}

export function getHealth() {
  return request('/health');
}

// ---- F5 Library + Review（SCHEMA §6.2 / §6.4，handoff 007）----

// GET /sessions — started_at 倒序的会话列表（Library）。行 shape：
// {id, mode, sub_mode, scenario_case, started_at, duration_s, status,
//  overall_band, wpm, is_seed}；overall_band/wpm 未出报告为 null。
export function getSessions({ signal } = {}) {
  return request('/sessions', { signal });
}

// GET /progress — {band_series, fluency_series, target_band, latest_bands, gap}
// series 时间升序、只取 completed；band_series 仅雅思方式 A。
export function getProgress({ signal } = {}) {
  return request('/progress', { signal });
}

// GET /settings → {target_band}（未设置 null）
export function getSettings({ signal } = {}) {
  return request('/settings', { signal });
}

// PUT /settings {target_band}：0–9 且 0.5 倍数，null = 清除；非法 422 中文 detail
export function putSettings(targetBand) {
  return request('/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_band: targetBand }),
  });
}

// 错误 → 用户可读文案。本地 demo 最常见故障是后端没起：vite proxy 回 502/504，
// statusText（Bad Gateway）对用户无意义，换成可行动的提示；422 等 detail 是
// 后端中文校验文案，直接展示（FRONTEND_HANDOFF §3 / G2）。
export function errorText(e) {
  if (e instanceof ApiError) {
    if (e.status === 502 || e.status === 504) {
      return '连不上后端服务——请确认 FastAPI 在 :8000 运行（uv run python main.py）。';
    }
    return detailText(e.detail);
  }
  return `请求失败：${e?.message ?? e}`;
}
