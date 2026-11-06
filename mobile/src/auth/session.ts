import {Api, ApiError, connectionUrl, serverUrl} from '../api/client';
import type {User} from '../api/types';

export interface Credential {server: string; token: string}
export interface Vault {
  read(): Promise<Credential | null>;
  write(value: Credential): Promise<void>;
  clear(): Promise<void>;
  readServer(): Promise<string | null>;
  writeServer(server: string): Promise<void>;
}
export interface SessionState {
  status: 'anonymous' | 'restoring' | 'authenticated';
  server: string;
  token: string;
  user: User | null;
  error: string;
}
export type ApiFactory = (server: string, token: string, invalidate: (token: string) => void) => Api;

export class Session {
  private revision = 0;
  private pendingStorage: Promise<unknown> = Promise.resolve();
  private listeners = new Set<() => void>();
  private state: SessionState;

  constructor(private vault: Vault, private factory: ApiFactory, private development: boolean) {
    this.state = {status: 'anonymous', server: '', token: '', user: null, error: ''};
  }
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  snapshot = (): SessionState => this.state;
  private update(next: Partial<SessionState>): void {
    this.state = {...this.state, ...next};
    this.listeners.forEach(listener => listener());
  }
  private storage(action: () => Promise<unknown>): Promise<unknown> {
    const task = this.pendingStorage.catch(() => undefined).then(action);
    this.pendingStorage = task;
    return task;
  }
  api(): Api {return this.factory(this.state.server, this.state.token, this.invalidate);}

  async connect(address: string): Promise<string> {
    const server = connectionUrl(address, this.development);
    await this.factory(server, '', this.invalidate).health();
    // Keep the server independently of the JWT, including after logout.
    await this.storage(async () => {
      const saved = await this.vault.read();
      if (saved && saved.server !== server) {await this.vault.clear();}
      await this.vault.writeServer(server);
    });
    this.update({server, error: ''});
    return server;
  }

  invalidate = (token: string): void => {
    if (token !== this.state.token || !token) {return;}
    ++this.revision;
    this.update({status: 'anonymous', token: '', user: null, error: 'Сессия истекла или отозвана. Войдите снова.'});
    void this.storage(() => this.vault.clear()).catch(() => this.update({error: 'Не удалось очистить защищённое хранилище. Повторите выход.'}));
  };

  async restore(): Promise<void> {
    const revision = ++this.revision;
    this.update({status: 'restoring', token: '', user: null, error: ''});
    try {
      const stored = await this.storage(async () => ({
        server: await this.vault.readServer(), credential: await this.vault.read(),
      })) as {server: string | null; credential: Credential | null};
      if (revision !== this.revision) {return;}
      if (stored.server) {this.update({server: serverUrl(stored.server, this.development)});}
      const saved = stored.credential;
      if (!saved) {this.update({status: 'anonymous'}); return;}
      const server = serverUrl(saved.server, this.development);
      this.update({server, token: saved.token});
      const user = await this.api().me();
      if (revision === this.revision) {this.update({status: 'authenticated', user});}
    } catch (error) {
      if (revision !== this.revision) {return;}
      if (error instanceof ApiError && error.status === 401) {this.invalidate(this.state.token); return;}
      this.update({status: 'anonymous', token: '', user: null, error: message(error)});
      // Network failure preserves the credential, but never grants offline access.
    }
  }

  async login(address: string, username: string, password: string): Promise<void> {
    const server = serverUrl(address, this.development);
    const revision = ++this.revision;
    this.update({status: 'restoring', token: '', user: null, error: '', server});
    try {
      // A failed login to another server must not restore an older account later.
      await this.storage(() => this.vault.clear());
      if (revision !== this.revision) {return;}
      const result = await this.factory(server, '', this.invalidate).login(username, password);
      if (revision !== this.revision) {return;}
      this.update({token: result.access_token});
      const user = await this.api().me();
      if (revision !== this.revision) {return;}
      await this.storage(() => this.vault.write({server, token: result.access_token}));
      if (revision === this.revision) {this.update({status: 'authenticated', user});}
    } catch (error) {
      if (revision !== this.revision) {return;}
      this.update({status: 'anonymous', token: '', user: null, error: message(error)});
    }
  }

  async logout(): Promise<void> {
    const api = this.api();
    ++this.revision;
    this.update({status: 'anonymous', token: '', user: null, error: ''});
    const results = await Promise.allSettled([
      this.storage(() => this.vault.clear()),
      api.token ? api.logout() : Promise.resolve(),
    ]);
    if (results.some(result => result.status === 'rejected')) {
      this.update({error: 'Локальный выход выполнен. Очистка хранилища или отзыв на сервере не подтверждены; повторите выход при наличии сети.'});
    }
  }
}

export function message(error: unknown): string {return error instanceof Error ? error.message : 'Не удалось выполнить операцию.';}
