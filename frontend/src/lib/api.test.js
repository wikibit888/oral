import { describe, it, expect, vi, afterEach } from 'vitest';
import { ApiError, detailText, errorText, retryReport } from './api.js';

// review W5：FastAPI 原生 422 的 detail 是 [{loc, msg, type}] 对象数组，
// 直接 String() 会渲染成 "[object Object]"。pin 住 detailText 的归一化行为。
describe('detailText', () => {
  it('passes through backend Chinese string details', () => {
    expect(detailText('mode 必须是 [ielts, scenario] 之一')).toBe(
      'mode 必须是 [ielts, scenario] 之一',
    );
  });

  it('joins FastAPI 422 validation arrays by msg, never [object Object]', () => {
    const detail = [
      { loc: ['body', 'mode'], msg: 'Field required', type: 'missing' },
      { loc: ['body', 'audio'], msg: 'Field required', type: 'missing' },
    ];
    const text = detailText(detail);
    expect(text).toBe('Field required；Field required');
    expect(text).not.toContain('[object Object]');
  });

  it('stringifies object / null details readably', () => {
    expect(detailText({ error: 'boom' })).toBe('{"error":"boom"}');
    expect(detailText(null)).toBe('未知错误');
  });
});

describe('retryReport（失败恢复端点）', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('POST /reports/{id}/retry，返回 {status:processing}', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ status: 'processing' }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const res = await retryReport('abc123');
    expect(res).toEqual({ status: 'processing' });
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain('/reports/abc123/retry');
    expect(opts.method).toBe('POST');
  });

  it('409（状态不可重跑）抛 ApiError 带后端中文文案', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 409,
        json: async () => ({ detail: '会话当前状态 completed 不可重跑' }),
      })),
    );
    await expect(retryReport('done1')).rejects.toMatchObject({ status: 409 });
  });
});

describe('errorText', () => {
  it('maps 502/504 to the backend-not-running hint', () => {
    expect(errorText(new ApiError(502, 'Bad Gateway'))).toContain('FastAPI');
  });

  it('renders ApiError array detail without [object Object]', () => {
    const e = new ApiError(422, [{ loc: ['body'], msg: 'Field required', type: 'missing' }]);
    expect(errorText(e)).toBe('Field required');
    expect(e.message).not.toContain('[object Object]');
  });

  it('falls back to message for non-ApiError', () => {
    expect(errorText(new Error('boom'))).toBe('请求失败：boom');
  });
});
