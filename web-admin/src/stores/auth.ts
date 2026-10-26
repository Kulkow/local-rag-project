import { defineStore } from 'pinia';
import { ApiError, login, request, type User } from '../management-api';

const TOKEN_KEY = 'rag.access_token';
function savedToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}

export const useAuth = defineStore('auth', {
  state: () => ({ token: '', user: null as User | null, restoring: false, restoreError: '', persistenceWarning: '', revision: 0 }),
  getters: {
    isAdmin: state => state.user?.role === 'admin',
    canManage: state => state.user?.role === 'admin' || state.user?.role === 'manager',
  },
  actions: {
    async restore() {
      if (this.restoring) return;
      const token = savedToken();
      if (!token) return;
      const revision = ++this.revision;
      this.restoring = true;
      this.restoreError = '';
      try {
        // Persist only the JWT. Permissions always come from the authenticated API.
        const user = await request<User>('/auth/me', token);
        if (revision !== this.revision) return;
        this.token = token;
        this.user = user;
      } catch (error) {
        if (revision !== this.revision) return;
        if (error instanceof ApiError && error.status === 401) this.invalidate(token);
        this.restoreError = error instanceof Error ? error.message : 'Не удалось проверить токен';
      } finally {
        if (revision === this.revision) this.restoring = false;
      }
    },
    async signIn(username: string, password: string) {
      const revision = ++this.revision;
      this.restoring = false;
      this.restoreError = '';
      const result = await login(username, password);
      if (revision !== this.revision) return;
      this.token = result.access_token;
      this.user = result.user;
      this.persistenceWarning = '';
      try { localStorage.setItem(TOKEN_KEY, this.token); }
      catch { this.persistenceWarning = 'Хранилище браузера недоступно: вход сохранится только в памяти вкладки.'; }
    },
    invalidate(expectedToken: string, message = '') {
      // A delayed 401 for an old JWT must not erase a newer login.
      if (this.token ? expectedToken !== this.token : expectedToken !== savedToken()) return;
      ++this.revision;
      this.token = '';
      this.user = null;
      this.restoring = false;
      this.restoreError = message;
      this.persistenceWarning = '';
      try { localStorage.removeItem(TOKEN_KEY); } catch { /* Storage may be disabled. */ }
    },
    async signOut() {
      const token = this.token || savedToken();
      try {
        if (token) await request('/auth/logout', token, 'POST');
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) throw error;
      } finally {
        this.invalidate(token);
      }
    },
  },
});
