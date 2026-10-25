import { afterEach, expect, it, vi } from 'vitest';
import { getReadiness } from '../src/api';
afterEach(() => vi.unstubAllGlobals());
it('reports authentication failure', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue({status: 401}));
 await expect(getReadiness('wrong', 'wrong')).rejects.toThrow('credentials');
});
it('accepts degraded readiness for dashboard display', async () => {
 const data = {status: 'degraded', services: {postgresql: false}};
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue({status: 503, json: async () => data}));
 expect(await getReadiness('admin', 'secret')).toEqual(data);
});
