import { afterEach, expect, it, vi } from 'vitest';
import { request } from '../src/shared/infrastructure/http';
import { createFamily } from '../src/modules/families/infrastructure/api';
afterEach(() => vi.unstubAllGlobals());
it('sends bearer authentication to the family API', async () => {
 const fetch = vi.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({ id: 'family', name: 'Synthetic' }) }); vi.stubGlobal('fetch', fetch);
 await createFamily('private-token', 'Synthetic');
 expect(fetch).toHaveBeenCalledWith('/api/families', expect.objectContaining({ method: 'POST', headers: expect.objectContaining({ Authorization: 'Bearer private-token' }), body: JSON.stringify({ name: 'Synthetic' }) }));
});
it('explains expired sessions', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: 'Session expired' }) }));
 await expect(request('/families', 'expired')).rejects.toThrow('Войдите снова');
});
it('handles delete responses without attempting to parse JSON', async () => {
 const json = vi.fn(); vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 204, json }));
 expect(await request('/families/id', 'token', 'DELETE')).toBeUndefined(); expect(json).not.toHaveBeenCalled();
});
