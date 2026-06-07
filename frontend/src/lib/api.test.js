import { describe, it, expect } from 'vitest';
import { ApiError, detailText, errorText } from './api.js';

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
