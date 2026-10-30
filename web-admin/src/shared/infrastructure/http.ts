import type { components } from './schema';

export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly timings?: Record<string, number>, readonly traceId?: string, readonly llmUsage?: components['schemas']['LlmUsage']) { super(message); }
}

export async function request<T>(path: string, token: string, method = 'GET', body?: unknown, acceptedStatuses: number[] = []): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000),
  });
  return readResponse<T>(response, token, acceptedStatuses);
}

export async function readResponse<T>(response: Response, token: string, acceptedStatuses: number[] = []): Promise<T> {
  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail : 'Проверьте заполнение полей.';
    if (response.status === 401 && token && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: token }));
    }
    const timings = data.timings && typeof data.timings === 'object' && !Array.isArray(data.timings)
      ? Object.fromEntries(Object.entries(data.timings).filter((entry): entry is [string, number] => typeof entry[1] === 'number' && Number.isFinite(entry[1]) && entry[1] >= 0))
      : undefined;
    throw new ApiError(response.status, response.status === 401 ? 'Токен истёк или неверный логин/пароль. Войдите снова.' : detail, timings, typeof data.trace_id === 'string' ? data.trace_id : undefined, data.llm_usage);
  }
  return response.status === 204 ? undefined as T : response.json();
}
