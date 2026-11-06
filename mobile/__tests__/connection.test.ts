import {Api, connectionUrl} from '../src/api/client';
import {Session, type Vault} from '../src/auth/session';

it.each([
  ['http://192.168.1.20', 'http://192.168.1.20:3000/api'],
  [' http://192.168.1.20:3000/ ', 'http://192.168.1.20:3000/api'],
  ['http://192.168.1.20:3000/api/', 'http://192.168.1.20:3000/api'],
  ['http://192.168.1.20:8000', 'http://192.168.1.20:8000'],
  ['https://example.test/custom/api/', 'https://example.test/custom/api'],
])('normalizes the connection address %s', (input, expected) => {
  expect(connectionUrl(input, true)).toBe(expected);
});

it.each(['192.168.1.20', 'garbage', 'file:///tmp/api', 'http://user:pass@192.168.1.20', 'http://192.168.1.20?key=secret', 'http://192.168.1.20#fragment'])('rejects invalid or unsafe addresses: %s', input => {
  expect(() => connectionUrl(input, true)).toThrow();
});

it('keeps the HTTPS requirement for release builds', () => {
  expect(() => connectionUrl('http://192.168.1.20', false)).toThrow('HTTPS');
  expect(connectionUrl('https://example.test/api', false)).toBe('https://example.test/api');
});

function setup() {
  const vault: jest.Mocked<Vault> = {
    read: jest.fn().mockResolvedValue(null), write: jest.fn().mockResolvedValue(undefined),
    clear: jest.fn().mockResolvedValue(undefined), readServer: jest.fn().mockResolvedValue(null),
    writeServer: jest.fn().mockResolvedValue(undefined),
  };
  const api = {health: jest.fn().mockResolvedValue(undefined), me: jest.fn().mockResolvedValue({id: 'user'}), logout: jest.fn().mockResolvedValue(undefined)};
  const factory = jest.fn().mockReturnValue(api as unknown as Api);
  return {vault, api, factory, session: new Session(vault, factory, true)};
}

it('checks the API without credentials and saves its normalized address before login', async () => {
  const {vault, factory, api, session} = setup();
  expect(session.snapshot().server).toBe('');
  await expect(session.connect('http://192.168.1.20')).resolves.toBe('http://192.168.1.20:3000/api');
  expect(factory).toHaveBeenCalledWith('http://192.168.1.20:3000/api', '', expect.any(Function));
  expect(api.health).toHaveBeenCalledTimes(1);
  expect(vault.writeServer).toHaveBeenCalledWith('http://192.168.1.20:3000/api');
  expect(vault.write).not.toHaveBeenCalled();
  expect(session.snapshot()).toMatchObject({status: 'anonymous', server: 'http://192.168.1.20:3000/api', token: ''});
});

it('does not save an unreachable API address', async () => {
  const {vault, api, session} = setup();
  api.health.mockRejectedValue(new Error('Нет соединения'));
  await expect(session.connect('http://192.168.1.20')).rejects.toThrow('Нет соединения');
  expect(vault.writeServer).not.toHaveBeenCalled();
  expect(session.snapshot().server).toBe('');
});

it('clears an old server credential when switching to another server', async () => {
  const {vault, session} = setup();
  vault.read.mockResolvedValue({server: 'https://old.example.test/api', token: 'old-jwt'});
  await session.connect('http://192.168.1.20');
  expect(vault.clear).toHaveBeenCalledTimes(1);
  expect(vault.writeServer).toHaveBeenCalledWith('http://192.168.1.20:3000/api');
  expect(session.snapshot().token).toBe('');
});

it('restores an address saved without a login and preserves it after logout', async () => {
  const {vault, session} = setup();
  vault.readServer.mockResolvedValue('http://192.168.1.20:3000/api');
  await session.restore();
  expect(session.snapshot()).toMatchObject({status: 'anonymous', server: 'http://192.168.1.20:3000/api'});
  await session.logout();
  expect(vault.clear).toHaveBeenCalledTimes(1);
  expect(session.snapshot().server).toBe('http://192.168.1.20:3000/api');
});

it('restores the server of an existing credential when no separate preference exists', async () => {
  const {vault, factory, session} = setup();
  vault.read.mockResolvedValue({server: 'https://example.test/api', token: 'jwt'});
  await session.restore();
  expect(factory).toHaveBeenCalledWith('https://example.test/api', 'jwt', expect.any(Function));
  expect(session.snapshot()).toMatchObject({status: 'authenticated', server: 'https://example.test/api'});
});

it('keeps the saved address editable when restoring a session fails offline', async () => {
  const {vault, api, session} = setup();
  vault.read.mockResolvedValue({server: 'http://192.168.1.20:3000/api', token: 'jwt'});
  api.me.mockRejectedValue(new Error('Нет соединения'));
  await session.restore();
  expect(session.snapshot()).toMatchObject({status: 'anonymous', server: 'http://192.168.1.20:3000/api', token: '', error: 'Нет соединения'});
});

it.each([{status: 'ok'}, null, {status: 'ready'}])('validates the health response: %j', async body => {
  const fetcher = jest.fn().mockResolvedValue({status: 200, json: async () => body});
  const api = new Api('http://192.168.1.20:3000/api', '', jest.fn(), jest.fn(), fetcher);
  if (body?.status === 'ok') {await expect(api.health()).resolves.toBeUndefined();}
  else {await expect(api.health()).rejects.toThrow('не найден API');}
  expect(fetcher).toHaveBeenCalledWith('http://192.168.1.20:3000/api/health', expect.objectContaining({headers: {'Content-Type': 'application/json'}}));
});
