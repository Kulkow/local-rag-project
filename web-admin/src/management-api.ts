import type { components } from './schema';
export type User = components['schemas']['UserView'];
export type Family = components['schemas']['FamilyView'];
export type Member = components['schemas']['MemberView'];
export type CreateUser = components['schemas']['CreateUser'];
export type UpdateUser = components['schemas']['UpdateUser'];
export type MemberInput = components['schemas']['MemberInput'];
export type LoginResult = components['schemas']['LoginResult'];

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
export const login = (username: string, password: string) => request<LoginResult>('/auth/login', '', 'POST', { username, password });
export const listFamilies = (token: string, offset = 0) => request<Family[]>(`/families?offset=${offset}&limit=20`, token);
export const createFamily = (token: string, name: string) => request<Family>('/families', token, 'POST', { name });
export const renameFamily = (token: string, id: string, name: string) => request<Family>(`/families/${id}`, token, 'PUT', { name });
export const deleteFamily = (token: string, id: string) => request<void>(`/families/${id}`, token, 'DELETE');
export const listMembers = (token: string, id: string, offset = 0) => request<Member[]>(`/families/${id}/members?offset=${offset}&limit=20`, token);
export const addMember = (token: string, id: string, body: MemberInput) => request<Member>(`/families/${id}/members`, token, 'POST', body);
export const changeMember = (token: string, id: string, memberId: string, role: string) => request<Member>(`/families/${id}/members/${memberId}`, token, 'PATCH', { role });
export const removeMember = (token: string, id: string, memberId: string) => request<void>(`/families/${id}/members/${memberId}`, token, 'DELETE');
export const listUsers = (token: string, offset = 0) => request<User[]>(`/users?offset=${offset}&limit=20`, token);
export const createUser = (token: string, body: CreateUser) => request<User>('/users', token, 'POST', body);
export const updateUser = (token: string, id: string, body: UpdateUser) => request<User>(`/users/${id}`, token, 'PUT', body);

export const sessionReadiness = (token: string) => request<components['schemas']['Readiness']>('/ready', token, 'GET', undefined, [503]);
