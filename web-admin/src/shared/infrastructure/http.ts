export class ApiError extends Error { constructor(readonly status: number, message: string) { super(message); } }

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
    throw new ApiError(response.status, response.status === 401 ? 'Токен истёк или неверный логин/пароль. Войдите снова.' : detail);
  }
  return response.status === 204 ? undefined as T : response.json();
}
