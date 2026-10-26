// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import PrimeVue from 'primevue/config';
import { flushPromises, mount } from '@vue/test-utils';
import Families from '../src/views/Families.vue';
import SessionAccess from '../src/components/SessionAccess.vue';
import Users from '../src/views/Users.vue';
import { useAuth } from '../src/stores/auth';
import * as api from '../src/management-api';
vi.mock('../src/management-api', () => ({
 ApiError: class ApiError extends Error { constructor(readonly status: number, message: string) { super(message); } }, login: vi.fn(), request: vi.fn(), listFamilies: vi.fn(), listMembers: vi.fn(), createFamily: vi.fn(),
 renameFamily: vi.fn(), deleteFamily: vi.fn(), addMember: vi.fn(), changeMember: vi.fn(), removeMember: vi.fn(),
 listUsers: vi.fn(), createUser: vi.fn(), updateUser: vi.fn(),
}));
let pinia: ReturnType<typeof createPinia>;
let wrapper: ReturnType<typeof mount> | undefined;
beforeEach(() => {
 localStorage.clear(); vi.resetAllMocks(); pinia = createPinia(); setActivePinia(pinia);
 vi.mocked(api.listFamilies).mockResolvedValue([]); vi.mocked(api.listMembers).mockResolvedValue([]); vi.mocked(api.listUsers).mockResolvedValue([]);
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; });
function signIn(role: api.User['role'] = 'admin') {
 const auth = useAuth(); auth.token = 'test-token'; auth.user = { id: 'user-id', username: 'synthetic-admin', role, family_member_id: null, is_active: true };
}
const global = () => ({ plugins: [pinia, PrimeVue], stubs: { Dialog: true } });
describe('family view', () => {
 it('requires sign-in before requesting family data', async () => {
  wrapper = mount(Families, { global: global() }); await flushPromises();
  expect(wrapper.text()).toContain('Вход в управление семьями');
  expect(api.listFamilies).not.toHaveBeenCalled();
 });
 it('creates a family and shows the resulting selection', async () => {
  signIn(); vi.mocked(api.createFamily).mockResolvedValue({ id: 'family-id', name: 'Семья Тест' });
  wrapper = mount(Families, { global: global() }); await flushPromises();
  const form = wrapper.find('form'); await form.find('input').setValue('Семья Тест'); await form.trigger('submit'); await flushPromises();
  expect(api.createFamily).toHaveBeenCalledWith('test-token', 'Семья Тест');
  expect(api.listMembers).toHaveBeenCalledWith('test-token', 'family-id', 0);
  expect(wrapper.text()).toContain('Семья создана');
 });
 it('shows API errors and restores the form after a failure', async () => {
  signIn(); vi.mocked(api.createFamily).mockRejectedValue(new Error('Database unavailable'));
  wrapper = mount(Families, { global: global() }); await flushPromises();
  await wrapper.find('form input').setValue('Synthetic family'); await wrapper.find('form').trigger('submit'); await flushPromises();
  expect(wrapper.find('[role="alert"]').text()).toContain('Database unavailable');
  expect(wrapper.find('form button').attributes('disabled')).toBeUndefined();
 });
 it('does not offer creation or writes to read-only members', async () => {
  signIn('member'); wrapper = mount(Families, { global: global() }); await flushPromises();
  expect(wrapper.text()).not.toContain('Создать семью');
  expect(wrapper.text()).not.toContain('Добавить участника');
 });
});
describe('users view', () => {
 it('denies the users screen to non-admins without fetching accounts', async () => {
  signIn('manager'); wrapper = mount(Users, { global: global() }); await flushPromises();
  expect(wrapper.text()).toContain('только администратору'); expect(api.listUsers).not.toHaveBeenCalled();
 });
 it('reports user-list API failures', async () => {
  signIn(); vi.mocked(api.listUsers).mockRejectedValue(new Error('Access denied'));
  wrapper = mount(Users, { global: global() }); await flushPromises();
  expect(wrapper.find('[role="alert"]').text()).toContain('Access denied');
 });
});

describe('session access', () => {
 it('signs in through the real Pinia action and clears the password field', async () => {
  vi.mocked(api.login).mockResolvedValue({ access_token: 'new-token', token_type: 'bearer', expires_in: 28800, user: { id: 'id', username: 'test-admin', role: 'admin', family_member_id: null, is_active: true } });
  wrapper = mount(SessionAccess, { global: global() });
  const fields = wrapper.findAll('input'); await fields[0].setValue('test-admin'); await fields[1].setValue('synthetic-password');
  await wrapper.find('form').trigger('submit'); await flushPromises();
  expect(api.login).toHaveBeenCalledWith('test-admin', 'synthetic-password');
  expect(useAuth().token).toBe('new-token'); expect(localStorage.getItem('rag.access_token')).toBe('new-token'); expect(wrapper.text()).toContain('test-admin');
 });
 it('shows login failures without keeping the submitted password', async () => {
  vi.mocked(api.login).mockRejectedValue(new Error('Invalid credentials'));
  wrapper = mount(SessionAccess, { global: global() });
  const fields = wrapper.findAll('input'); await fields[0].setValue('test-admin'); await fields[1].setValue('incorrect');
  await wrapper.find('form').trigger('submit'); await flushPromises();
  expect(wrapper.find('[role="alert"]').text()).toContain('Invalid credentials');
  expect((wrapper.find('input[type="password"]').element as HTMLInputElement).value).toBe('');
  expect(useAuth().token).toBe('');
 });
 it('revokes the session on sign out and clears the account', async () => {
  signIn(); localStorage.setItem('rag.access_token', 'test-token'); vi.mocked(api.request).mockResolvedValue(undefined);
  wrapper = mount(SessionAccess, { global: global() }); await wrapper.find('button').trigger('click'); await flushPromises();
  expect(api.request).toHaveBeenCalledWith('/auth/logout', 'test-token', 'POST'); expect(useAuth().user).toBeNull(); expect(useAuth().token).toBe(''); expect(localStorage.getItem('rag.access_token')).toBeNull();
 });
});

describe('persistent JWT state', () => {
 it('restores a saved JWT only after the server verifies the user', async () => {
  localStorage.setItem('rag.access_token', 'saved-jwt');
  const user: api.User = { id: 'id', username: 'verified', role: 'member', family_member_id: 'member-id', is_active: true };
  vi.mocked(api.request).mockResolvedValue(user);
  const auth = useAuth(); const restoring = auth.restore();
  expect(auth.user).toBeNull(); expect(auth.isAdmin).toBe(false);
  await restoring;
  expect(api.request).toHaveBeenCalledWith('/auth/me', 'saved-jwt');
  expect(auth.token).toBe('saved-jwt'); expect(auth.user?.username).toBe('verified');
 });
 it('removes a rejected JWT from localStorage', async () => {
  localStorage.setItem('rag.access_token', 'expired');
  vi.mocked(api.request).mockRejectedValue(new api.ApiError(401, 'Expired JWT'));
  const auth = useAuth(); await auth.restore();
  expect(auth.user).toBeNull(); expect(auth.token).toBe(''); expect(auth.restoring).toBe(false);
  expect(localStorage.getItem('rag.access_token')).toBeNull();
 });
 it('keeps the saved JWT on a network failure but grants no permissions', async () => {
  localStorage.setItem('rag.access_token', 'saved-jwt'); vi.mocked(api.request).mockRejectedValue(new TypeError('offline'));
  const auth = useAuth(); await auth.restore();
  expect(localStorage.getItem('rag.access_token')).toBe('saved-jwt'); expect(auth.user).toBeNull(); expect(auth.isAdmin).toBe(false);
 });
 it('ignores delayed failures for a previous JWT', () => {
  signIn(); const auth = useAuth(); localStorage.setItem('rag.access_token', 'test-token'); auth.invalidate('old-token');
  expect(auth.token).toBe('test-token'); expect(localStorage.getItem('rag.access_token')).toBe('test-token');
 });
 it('does not restore an account after a concurrent logout', async () => {
  localStorage.setItem('rag.access_token', 'saved-jwt'); let resolve!: (value: api.User) => void;
  vi.mocked(api.request).mockReturnValueOnce(new Promise(r => { resolve = r; }));
  const auth = useAuth(); const restoring = auth.restore(); auth.invalidate('saved-jwt');
  resolve({ id: 'id', username: 'old', role: 'admin', family_member_id: null, is_active: true }); await restoring;
  expect(auth.user).toBeNull(); expect(auth.token).toBe('');
 });
});
