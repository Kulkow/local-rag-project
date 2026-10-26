import type { components } from '../../../shared/infrastructure/schema';
import { request } from '../../../shared/infrastructure/http';
export type User = components['schemas']['UserView'];
export type CreateUser = components['schemas']['CreateUser'];
export type UpdateUser = components['schemas']['UpdateUser'];
export type LoginResult = components['schemas']['LoginResult'];
export const login = (username: string, password: string) => request<LoginResult>('/auth/login', '', 'POST', { username, password });
export const listUsers = (token: string, offset = 0) => request<User[]>(`/users?offset=${offset}&limit=20`, token);
export const createUser = (token: string, body: CreateUser) => request<User>('/users', token, 'POST', body);
export const updateUser = (token: string, id: string, body: UpdateUser) => request<User>(`/users/${id}`, token, 'PUT', body);

export const getCurrentUser = (token: string) => request<User>('/auth/me', token);
export const logout = (token: string) => request<void>('/auth/logout', token, 'POST');
