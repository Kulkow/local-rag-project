import { afterEach, expect, it, vi } from 'vitest';
import { getReadiness } from '../src/modules/operations/infrastructure/basic-readiness';
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

it('preserves safe RAG error timings and trace metadata', async () => {
 const { readResponse, ApiError } = await import('../src/shared/infrastructure/http');
 const response = new Response(JSON.stringify({detail:'Model unavailable',trace_id:'trace',timings:{generation_ms:65000,invalid:'secret',negative:-1}}), {status:503});
 const error = await readResponse(response, 'token').catch(error => error);
 expect(error).toBeInstanceOf(ApiError);
 expect(error.timings).toEqual({generation_ms:65000});
 expect(error.traceId).toBe('trace');
});
