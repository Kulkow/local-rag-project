import type {Document, Family, Index, Job, LocalFile, LoginResult, User, Visibility} from './types';

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

export function serverUrl(value: string, development: boolean): string {
  let url: URL;
  try {url = new URL(value.trim());}
  catch {throw new Error('Укажите адрес API, например http://192.168.1.20:3000/api.');}
  if (url.username || url.password || url.search || url.hash || !url.hostname ||
      (url.protocol !== 'https:' && !(development && url.protocol === 'http:'))) {
    throw new Error('Укажите HTTPS-адрес API. HTTP доступен только в debug-сборке.');
  }
  return url.toString().replace(/\/+$/, '');
}

export function connectionUrl(value: string, development: boolean): string {
  const url = new URL(serverUrl(value, development));
  // A bare HTTP address uses the project's LAN-facing Compose proxy.
  if (url.protocol === 'http:' && url.pathname === '/' && (!url.port || url.port === '3000')) {
    return `http://${url.hostname}:3000/api`;
  }
  return url.toString().replace(/\/+$/, '');
}

export interface BinaryResponse {status: number; data: string}
export type BinaryUpload = (url: string, headers: Record<string, string>, uri: string) => Promise<BinaryResponse>;

export class Api {
  constructor(
    readonly baseUrl: string,
    readonly token: string,
    private readonly unauthorized: (token: string) => void,
    private readonly binary: BinaryUpload,
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  private async decode<T>(status: number, data: unknown): Promise<T> {
    if (status >= 200 && status < 300) {return data as T;}
    if (status === 401 && this.token) {this.unauthorized(this.token);}
    const messages: Record<number, string> = {
      401: 'Неверный логин/пароль или сессия истекла. Войдите снова.',
      403: 'Недостаточно прав для этого действия.',
      404: 'Документ или семья недоступны.',
      409: 'Конфликт операции. Обновите список и проверьте состояние документа.',
      413: 'Максимальный размер файла — 10 MiB.',
      415: 'Сервер принимает PDF, DOCX, HTML, PNG и JPEG. Проверьте формат файла и версию сервера.',
      422: 'Проверьте поля и формат файла.',
      429: 'Слишком много запросов. Повторите позже.',
      503: 'Сервис временно недоступен. Повторите позже.',
    };
    // Do not display raw server bodies: proxies can return HTML or sensitive diagnostics.
    throw new ApiError(status, messages[status] ?? `Ошибка сервера (${status}).`);
  }

  async request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const result = await this.fetcher(`${this.baseUrl}${path}`, {
        method,
        headers: {'Content-Type': 'application/json', ...(this.token ? {Authorization: `Bearer ${this.token}`} : {})},
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      return await this.decode<T>(result.status, result.status === 204 ? undefined : await result.json().catch(() => null));
    } catch (error) {
      if (error instanceof ApiError) {throw error;}
      throw new Error('Нет соединения с API или истекло время ожидания. Проверьте адрес и подключение.');
    } finally {clearTimeout(timer);}
  }

  login(username: string, password: string): Promise<LoginResult> {
    return this.request('/auth/login', 'POST', {username: username.trim().toLowerCase(), password});
  }
  async health(): Promise<void> {
    const result = await this.request<unknown>('/health');
    if (!result || typeof result !== 'object' || !('status' in result) || result.status !== 'ok') {
      throw new Error('По этому адресу не найден API платформы. Проверьте адрес, порт и путь /api.');
    }
  }
  me(): Promise<User> {return this.request('/auth/me');}
  logout(): Promise<void> {return this.request('/auth/logout', 'POST');}
  families(offset = 0): Promise<Family[]> {return this.request(`/families?offset=${offset}&limit=50`);}
  documents(family: string, offset = 0): Promise<Document[]> {
    return this.request(`/documents?family_id=${encodeURIComponent(family)}&offset=${offset}&limit=20`);
  }
  formats(): Promise<string[]> {return this.request('/documents/extraction-formats');}
  job(id: string): Promise<Job> {return this.request(`/documents/${encodeURIComponent(id)}/processing`);}
  index(id: string): Promise<Index> {return this.request(`/documents/${encodeURIComponent(id)}/index`);}
  process(id: string): Promise<Job> {return this.request(`/documents/${encodeURIComponent(id)}/process`, 'POST');}

  async upload(file: LocalFile, family: string, visibility: Visibility): Promise<Document> {
    const query = `family_id=${encodeURIComponent(family)}&filename=${encodeURIComponent(file.name)}&visibility=${visibility}`;
    let result: BinaryResponse;
    try {
      result = await this.binary(`${this.baseUrl}/documents?${query}`, {
        Authorization: `Bearer ${this.token}`,
        'Content-Type': file.type,
        'Idempotency-Key': file.key,
      }, file.uri);
    } catch {throw new Error('Не удалось отправить файл. Повторите с тем же ключом; копия не будет создана.');}
    let data: unknown;
    try {data = JSON.parse(result.data);} catch {data = null;}
    return this.decode<Document>(result.status, data);
  }
}
